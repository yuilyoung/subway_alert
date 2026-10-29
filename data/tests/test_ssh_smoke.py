"""Loopback driver policy tests; SSH/Docker processes and HTTP are boundaries."""

import contextlib
import importlib.util
import io
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy"))
import release
from test_release import DockerBoundary, http_ok, image_id, write_image

SPEC = importlib.util.find_spec("smoke_ssh")
smoke_ssh = importlib.util.module_from_spec(SPEC) if SPEC else None
if SPEC:
    SPEC.loader.exec_module(smoke_ssh)
SHA = "a" * 40
SECRET = "ssh-smoke-private-sentinel"


class Daemon:
    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.terminated = True

    def wait(self, timeout):
        return 0


class SmokeBoundary:
    def __init__(self, root, bundle):
        self.root, self.bundle = root, bundle
        self.calls = []
        self.docker = DockerBoundary()
        self.daemon = Daemon()
        self.key_paths = []
        self.config = ""
        self.fail = None
        self.existing_project = False

    def popen(self, args, **kwargs):
        self.config = Path(args[args.index("-f") + 1]).read_text()
        self.calls.append((list(args), kwargs))
        if self.fail == "daemon":
            raise OSError(SECRET)
        return self.daemon

    def run(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        if args[0] == "ssh-keygen":
            path = Path(args[args.index("-f") + 1])
            self.key_paths.append(path)
            path.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n" + SECRET + "\n")
            path.chmod(0o600)
            path.with_suffix(".pub").write_text("ssh-ed25519 AAAA" + path.name + " local\n")
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0].endswith("sshd"):
            return subprocess.CompletedProcess(args, 0, SECRET, SECRET)
        if args[0] == sys.executable:
            if self.fail == "transport":
                return subprocess.CompletedProcess(args, 1, SECRET, SECRET)
            self.transport_environment = kwargs["env"]
            result = release.deploy_bundle(self.root, self.bundle, SHA, 17)
            if result["status"] != "passed":
                raise AssertionError("test release did not deploy")
            if self.fail == "readiness":
                self.docker.wrong_container = True
            if self.fail == "unexpected-file":
                (self.root / "operator-data").write_text(SECRET)
            if self.fail == "response":
                return subprocess.CompletedProcess(args, 0, SECRET, SECRET)
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "status": "passed",
                        "stage": "complete",
                        "sourceSHA": SHA,
                        "runID": 17,
                    }
                ),
                SECRET,
            )
        if args[:3] in (
            ["docker", "container", "ls"],
            ["docker", "network", "ls"],
            ["docker", "volume", "ls"],
        ):
            return subprocess.CompletedProcess(
                args, 0, "existing" if self.existing_project else "", ""
            )
        if self.fail == "cleanup" and args[:2] == ["docker", "compose"] and "down" in args:
            return subprocess.CompletedProcess(args, 1, SECRET, SECRET)
        return self.docker(args, **kwargs)


class SSHSmokeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(smoke_ssh, "the real loopback SSH smoke CLI is missing")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        self.root = self.parent / "host"
        self.root.mkdir(mode=0o700)
        self.bundle = self.parent / "bundle"
        self.bundle.mkdir()
        for name in ("release.py", "compose.staging.yaml"):
            shutil.copyfile(ROOT / "deploy" / name, self.bundle / name)
        write_image(self.bundle / "image.tar")
        release.write_metadata(self.bundle, SHA, 17, image_id())
        self.boundary = SmokeBoundary(self.root, self.bundle)
        for target, name, value in (
            (smoke_ssh, "HOST_ROOT", self.root),
            (smoke_ssh.subprocess, "run", self.boundary.run),
            (smoke_ssh.subprocess, "Popen", self.boundary.popen),
            (release, "http_request", http_ok),
        ):
            mocked = patch.object(target, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        connected = patch.object(smoke_ssh.socket, "create_connection")
        connected.start()
        self.addCleanup(connected.stop)
        baseline = {
            name: value for name, value in os.environ.items() if not name.startswith("DOCKER_")
        }
        baseline.update(GITHUB_TOKEN=SECRET, SUBWAY_API_TOKENS=SECRET)
        environment = patch.dict(os.environ, baseline, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def invoke(self, *extra, opt_in=True):
        output = io.StringIO()
        args = ["--bundle", str(self.bundle), "--source-sha", SHA, "--run-id", "17"]
        if opt_in:
            args.append("--allow-ci-host-test")
        with contextlib.redirect_stdout(output):
            code = smoke_ssh.main([*args, *extra])
        self.assertNotIn(SECRET, output.getvalue())
        return code, json.loads(output.getvalue())

    def assert_failed(self, result, stage):
        self.assertEqual(result[0], 1)
        self.assertEqual(result[1]["status"], "failed")
        self.assertEqual(result[1]["stage"], stage)

    def test_explicit_opt_in_precedes_all_processes_or_host_mutation(self):
        self.assert_failed(self.invoke(opt_in=False), "opt-in")
        self.assertEqual(self.boundary.calls, [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_nonempty_host_is_preserved_without_starting_processes(self):
        marker = self.root / "operator-data"
        marker.write_text(SECRET)
        self.assert_failed(self.invoke(), "host-root")
        self.assertEqual(marker.read_text(), SECRET)
        self.assertEqual(self.boundary.calls, [])

    def test_nonprivate_or_symlink_host_and_ancestor_are_rejected(self):
        self.root.chmod(0o755)
        self.assert_failed(self.invoke(), "host-root")
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o755)
        self.root.rmdir()
        target = self.parent / "target"
        target.mkdir(mode=0o700)
        self.root.symlink_to(target, target_is_directory=True)
        self.assert_failed(self.invoke(), "host-root")
        self.assertEqual(list(target.iterdir()), [])
        self.root.unlink()
        self.root = self.parent / "linked" / "host"
        (self.parent / "linked").symlink_to(target, target_is_directory=True)
        (target / "host").mkdir(mode=0o700)
        with patch.object(smoke_ssh, "HOST_ROOT", self.root):
            self.assert_failed(self.invoke(), "host-root")
        self.assertEqual(self.boundary.calls, [])

    def test_missing_root_is_not_created(self):
        self.root.rmdir()
        self.assert_failed(self.invoke(), "host-root")
        self.assertFalse(self.root.exists())

    def test_wrong_owner_is_rejected(self):
        with patch.object(smoke_ssh.os, "geteuid", return_value=os.geteuid() + 1):
            self.assert_failed(self.invoke(), "host-root")
        self.assertEqual(self.boundary.calls, [])

    def test_valid_driver_invokes_transport_and_cleans_own_project_files_and_keys(self):
        report_path = self.parent / "report.json"
        code, report = self.invoke("--report", str(report_path))
        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["stage"], "complete")
        self.assertEqual(set(report["checks"].values()), {"passed"})
        self.assertEqual(set(report["cleanup"].values()), {"passed"})
        self.assertEqual(json.loads(report_path.read_text()), report)
        self.assertEqual(stat.S_IMODE(report_path.stat().st_mode), 0o600)
        self.assertTrue(self.boundary.daemon.terminated)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertTrue(self.boundary.key_paths)
        self.assertTrue(all(not path.parent.exists() for path in self.boundary.key_paths))
        self.assertIsNone(self.boundary.docker.active)
        transport = [args for args, _ in self.boundary.calls if args[0] == sys.executable]
        self.assertEqual(len(transport), 1)
        self.assertEqual(transport[0][1], str(ROOT / "deploy" / "ssh_deploy.py"))
        self.assertEqual(transport[0][-4:], ["--source-sha", SHA, "--run-id", "17"])
        environment = self.boundary.transport_environment
        self.assertEqual(environment["SSH_HOST"], "127.0.0.1")
        self.assertIn("PRIVATE KEY", environment["SSH_PRIVATE_KEY"])
        self.assertTrue(environment["SSH_KNOWN_HOSTS"].startswith("[127.0.0.1]:"))
        self.assertEqual(
            set(environment),
            {
                "PATH",
                "LANG",
                "LC_ALL",
                "HOME",
                "DOCKER_CONTEXT",
                "DOCKER_HOST",
                "SSH_HOST",
                "SSH_PORT",
                "SSH_USER",
                "SSH_PRIVATE_KEY",
                "SSH_KNOWN_HOSTS",
            },
        )
        for required in (
            "ListenAddress 127.0.0.1",
            "AddressFamily inet",
            "AllowUsers ",
            "PasswordAuthentication no",
            "UsePAM no",
            "DisableForwarding yes",
            "Subsystem sftp internal-sftp",
        ):
            self.assertIn(required, self.boundary.config)
        self.assertFalse(any(args[0] == "ssh-keyscan" for args, _ in self.boundary.calls))

    def test_bundle_failure_precedes_all_processes_and_host_initialization(self):
        (self.bundle / "release.py").write_text(SECRET)
        self.assert_failed(self.invoke(), "bundle")
        self.assertEqual(self.boundary.calls, [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_docker_project_is_not_touched(self):
        self.boundary.existing_project = True
        self.assert_failed(self.invoke(), "existing-project")
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertFalse(any("down" in args for args, _ in self.boundary.calls))
        self.assertFalse(self.boundary.key_paths)

    def test_engine_overrides_fail_before_mutation(self):
        for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_HTTP_PROXY"):
            with self.subTest(variable=name), patch.dict(os.environ, {name: SECRET}):
                self.assert_failed(self.invoke(), "engine")
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.boundary.calls, [])

    def test_different_home_context_cannot_redirect_any_engine_or_cleanup_and_is_restored(self):
        alternate_home = self.parent / "alternate-home"
        config = alternate_home / ".docker" / "config.json"
        config.parent.mkdir(parents=True)
        original = '{"currentContext":"operator-remote-daemon"}\n'
        config.write_text(original)
        real_home = pwd.getpwuid(os.geteuid()).pw_dir
        with patch.dict(os.environ, {"HOME": str(alternate_home)}):
            parent_environment = dict(os.environ)
            for failure in (None, "transport", "cleanup"):
                with self.subTest(failure=failure):
                    self.boundary.fail = failure
                    self.boundary.daemon = Daemon()
                    start = len(self.boundary.calls)
                    result = self.invoke()
                    self.assertEqual(result[0], 0 if failure is None else 1)
                    self.assertEqual(dict(os.environ), parent_environment)
                    self.assertEqual(config.read_text(), original)
                    calls = self.boundary.calls[start:]
                    self.assertTrue(any("down" in args for args, _ in calls))
                    for args, kwargs in calls:
                        with self.subTest(command=args[0]):
                            environment = kwargs["env"]
                            self.assertEqual(environment.get("HOME"), real_home)
                            self.assertEqual(environment.get("DOCKER_CONTEXT"), "default")
                            self.assertEqual(
                                environment.get("DOCKER_HOST"), "unix:///var/run/docker.sock"
                            )

    def test_daemon_failure_cleans_initialized_files_and_generated_keys(self):
        self.boundary.fail = "daemon"
        result = self.invoke()
        self.assert_failed(result, "daemon")
        self.assertEqual(result[1]["cleanup"]["host"], "passed")
        self.assertEqual(result[1]["cleanup"]["keys"], "passed")
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertTrue(all(not path.parent.exists() for path in self.boundary.key_paths))

    def test_transport_failure_or_untrusted_response_is_redacted_and_cleaned(self):
        for failure in ("transport", "response"):
            with self.subTest(failure=failure):
                self.boundary.fail = failure
                self.boundary.daemon = Daemon()
                result = self.invoke()
                self.assert_failed(result, "ssh-deploy")
                self.assertEqual(set(result[1]["cleanup"].values()), {"passed"})
                self.assertEqual(list(self.root.iterdir()), [])
                self.assertIsNone(self.boundary.docker.active)

    def test_readiness_checks_exact_image_after_transport_success(self):
        self.boundary.fail = "readiness"
        result = self.invoke()
        self.assert_failed(result, "same-image-readiness")
        self.assertEqual(result[1]["checks"]["ssh-deploy"], "passed")
        self.assertEqual(set(result[1]["cleanup"].values()), {"passed"})
        self.assertEqual(list(self.root.iterdir()), [])

    def test_project_cleanup_failure_preserves_host_files_but_removes_keys_and_daemon(self):
        self.boundary.fail = "cleanup"
        result = self.invoke()
        self.assert_failed(result, "cleanup")
        self.assertEqual(
            result[1]["cleanup"],
            {
                "daemon": "passed",
                "project": "failed",
                "host": "failed",
                "keys": "passed",
            },
        )
        self.assertTrue((self.root / ".env").is_file())
        self.assertTrue((self.root / "state.json").is_file())
        self.assertTrue(self.boundary.daemon.terminated)
        self.assertTrue(all(not path.parent.exists() for path in self.boundary.key_paths))

    def test_unexpected_host_file_aborts_all_file_deletion(self):
        self.boundary.fail = "unexpected-file"
        result = self.invoke()
        self.assert_failed(result, "cleanup")
        self.assertEqual(result[1]["cleanup"]["host"], "failed")
        self.assertEqual((self.root / "operator-data").read_text(), SECRET)
        self.assertTrue((self.root / ".env").is_file())
        self.assertTrue((self.root / "state.json").is_file())
        self.assertIsNone(self.boundary.docker.active)

    def test_cleanup_rejects_symlink_hardlink_and_replaced_root_without_deleting_data(self):
        identity = smoke_ssh.host_root()
        marker = self.root / ".env"
        outside = self.parent / "private-file"
        outside.write_text(SECRET)
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    marker.symlink_to(outside)
                else:
                    os.link(outside, marker)
                with self.assertRaises(smoke_ssh.SmokeFailure):
                    smoke_ssh.cleanup_host(identity, SHA, 17)
                self.assertEqual(outside.read_text(), SECRET)
                self.assertTrue(marker.exists())
                marker.unlink()
        self.root.rename(self.parent / "original")
        self.root.mkdir(mode=0o700)
        marker.write_text(SECRET)
        with self.assertRaises(smoke_ssh.SmokeFailure):
            smoke_ssh.cleanup_host(identity, SHA, 17)
        self.assertEqual(marker.read_text(), SECRET)

    def test_bad_arguments_and_report_destinations_do_not_echo_values_or_touch_host(self):
        self.assert_failed(self.invoke("--source-sha", SECRET), "input")
        self.assert_failed(self.invoke("--sshd", SECRET), "input")
        self.assert_failed(self.invoke("--unexpected", SECRET), "arguments")
        self.assert_failed(self.invoke("--report", str(self.root / "report.json")), "report")
        target = self.parent / "target-report"
        target.write_text(SECRET)
        link = self.parent / "report-link"
        link.symlink_to(target)
        self.assert_failed(self.invoke("--report", str(link)), "report")
        self.assertEqual(target.read_text(), SECRET)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.boundary.calls, [])


if __name__ == "__main__":
    unittest.main()
