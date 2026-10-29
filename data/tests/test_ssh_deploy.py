"""Real bundle/key/file checks with only the SSH/SCP host boundary replaced."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy"))
import release

SPEC = importlib.util.find_spec("ssh_deploy")
ssh_deploy = importlib.util.module_from_spec(SPEC) if SPEC else None
if SPEC:
    SPEC.loader.exec_module(ssh_deploy)
SHA = "a" * 40
SECRET = "transport-private-sentinel"
REAL_RUN = subprocess.run


class SSHBoundary:
    """Run remote filesystem preparation locally, never contact an SSH host."""

    def __init__(self, root):
        self.root = root
        self.calls = []
        self.private_paths = set()
        self.fail = None
        self.timeout = None
        self.remote_stdout = '{"status":"passed","rollback":"not-needed"}'
        self.remote_code = 0
        self.prepare_stdout = None
        self.optimize_remote = False

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), dict(kwargs)))
        if not kwargs.get("capture_output") or kwargs.get("check"):
            raise AssertionError("external output must remain captured")
        if not 0 < kwargs.get("timeout", 0) <= 900:
            raise AssertionError("every external operation needs a bounded timeout")
        environment = kwargs.get("env", {})
        for name in (
            "SSH_PRIVATE_KEY",
            "SSH_KNOWN_HOSTS",
            "GITHUB_TOKEN",
            "SUBWAY_API_TOKENS",
            "DOCKER_CONTEXT",
            "DOCKER_HOST",
            "DOCKER_CONFIG",
        ):
            if name in environment:
                raise AssertionError("ambient credentials reached a child")
        if args[0] == "ssh-keygen":
            filename = Path(args[args.index("-f") + 1])
            self.private_paths.add(filename)
            if filename.stat().st_mode & 0o777 != 0o600:
                raise AssertionError("temporary credentials must be owner-only")
            if filename.parent.stat().st_mode & 0o777 != 0o700:
                raise AssertionError("temporary directory must be owner-only")
            stage = "credential" if "-y" in args else "pin"
            if self.timeout == stage:
                raise subprocess.TimeoutExpired(args, kwargs["timeout"], SECRET, SECRET)
            return REAL_RUN(args, **kwargs)
        if args[0] not in ("ssh", "scp"):
            raise AssertionError("unexpected external command")
        options = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "-o"]
        for required in (
            "BatchMode=yes",
            "StrictHostKeyChecking=yes",
            "IdentitiesOnly=yes",
            "GlobalKnownHostsFile=/dev/null",
            "IdentityAgent=none",
            "VerifyHostKeyDNS=no",
        ):
            if required not in options:
                raise AssertionError("SSH identity policy was weakened")
        if args[args.index("-F") + 1] != "/dev/null":
            raise AssertionError("ambient SSH configuration is not allowed")
        key = Path(args[args.index("-i") + 1])
        self.private_paths.add(key)
        if key.stat().st_mode & 0o777 != 0o600:
            raise AssertionError("private key permissions changed")
        if args[0] == "scp":
            stage = "transfer"
        elif " hostdeploy " in args[-1]:
            stage = "deploy"
        else:
            words = shlex.split(args[-1])
            stage = words[words.index("-c") + 2]
        if self.timeout == stage:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"], SECRET, SECRET)
        if self.fail == stage:
            return subprocess.CompletedProcess(args, 255, SECRET, SECRET)
        if stage == "deploy":
            return subprocess.CompletedProcess(args, self.remote_code, self.remote_stdout, SECRET)
        if stage == "transfer":
            # Materialize only the files the real transport selected.
            destination = args[-1].split(":", 1)[1].rstrip("/")
            local = self.root / Path(destination).relative_to("/srv/subway-alert")
            for source in args[args.index("--") + 1 : -1]:
                shutil.copyfile(source, local / Path(source).name)
            return subprocess.CompletedProcess(args, 0, SECRET, SECRET)
        words = shlex.split(args[-1])
        root_index = words.index("-c") + 3
        if words[0] != "python3" or words[root_index] != "/srv/subway-alert":
            raise AssertionError("remote preparation must stay below the fixed host root")
        words[root_index] = str(self.root)
        if stage == "cleanup":
            words[root_index + 1] = str(
                self.root / Path(words[root_index + 1]).relative_to("/srv/subway-alert")
            )
        if self.optimize_remote:
            words.insert(1, "-O")
        result = REAL_RUN(words, **kwargs)
        result.stdout = result.stdout.replace(str(self.root), "/srv/subway-alert")
        if stage == "prepare" and self.prepare_stdout is not None:
            result.stdout = self.prepare_stdout
        return result


class SSHDeployTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.keys.cleanup)
        key = Path(cls.keys.name) / "id"
        REAL_RUN(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        cls.private_key = key.read_text()
        cls.public_key = key.with_suffix(".pub").read_text().strip()

    def setUp(self):
        self.assertIsNotNone(ssh_deploy, "the safe SSH transport CLI is missing")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        for name in ("release.py", "compose.staging.yaml"):
            shutil.copyfile(ROOT / "deploy" / name, self.bundle / name)
        config = b"{}"
        identity = hashlib.sha256(config).hexdigest()
        with tarfile.open(self.bundle / "image.tar", "w") as archive:
            for name, data in (
                (identity + ".json", config),
                (
                    "manifest.json",
                    json.dumps(
                        [{"Config": identity + ".json", "RepoTags": [], "Layers": []}]
                    ).encode(),
                ),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        release.write_metadata(self.bundle, SHA, 17, "sha256:" + identity)
        self.host = self.root / "host"
        self.host.mkdir(mode=0o700)
        for name in ("incoming", "releases", "configs"):
            (self.host / name).mkdir(mode=0o700)
        (self.host / ".env").write_text("SUBWAY_API_TOKENS=" + SECRET)
        (self.host / ".env").chmod(0o600)
        self.boundary = SSHBoundary(self.host)
        self.environment = {
            "PATH": os.environ["PATH"],
            "SSH_HOST": "staging.example",
            "SSH_PORT": "2222",
            "SSH_USER": "deploy",
            "SSH_PRIVATE_KEY": self.private_key,
            "SSH_KNOWN_HOSTS": "[staging.example]:2222 " + self.public_key + "\n",
            "GITHUB_TOKEN": SECRET,
            "SUBWAY_API_TOKENS": SECRET,
        }

    def invoke(self, arguments=None):
        argv = (
            arguments
            if arguments is not None
            else ["--bundle", str(self.bundle), "--source-sha", SHA, "--run-id", "17"]
        )
        with (
            patch.dict(os.environ, self.environment, clear=True),
            patch.object(ssh_deploy.subprocess, "run", side_effect=self.boundary),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            code = ssh_deploy.main(argv)
        output = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(SECRET, output)
        self.assertNotIn(self.private_key, output)
        self.assertNotIn(self.public_key, output)
        result = json.loads(stdout.getvalue())
        self.assertLessEqual(set(result), {"stage", "status", "sourceSHA", "runID"})
        for path in self.boundary.private_paths:
            self.assertFalse(path.exists(), "temporary SSH material was not removed")
            self.assertFalse(path.parent.exists(), "temporary SSH directory was not removed")
        return code, result

    def connections(self):
        return [args for args, _ in self.boundary.calls if args[0] in ("ssh", "scp")]

    def test_verifies_and_transfers_exact_bundle_before_invoking_existing_lifecycle(self):
        code, report = self.invoke()
        self.assertEqual(
            (code, report),
            (0, {"status": "passed", "stage": "complete", "sourceSHA": SHA, "runID": 17}),
        )
        connections = self.connections()
        self.assertEqual([args[0] for args in connections], ["ssh", "scp", "ssh", "ssh"])
        transfer = connections[1]
        self.assertEqual(
            {Path(name).name for name in transfer[transfer.index("--") + 1 : -1]},
            {"image.tar", "release.py", "compose.staging.yaml", "manifest.json", "SHA256SUMS"},
        )
        self.assertIn(" hostdeploy ", connections[2][-1])
        self.assertEqual(list((self.host / "incoming").iterdir()), [])
        self.assertEqual(list((self.host / "releases").iterdir()), [])
        self.assertEqual(list((self.host / "configs").iterdir()), [])
        self.assertEqual((self.host / ".env").read_text(), "SUBWAY_API_TOKENS=" + SECRET)

    def test_remote_deployment_pins_local_docker_without_client_environment_leaks(self):
        self.environment.update(
            DOCKER_CONTEXT=SECRET,
            DOCKER_HOST="ssh://" + SECRET,
            DOCKER_CONFIG="/private/" + SECRET,
        )
        self.assertEqual(self.invoke()[0], 0)
        connections = self.connections()
        deploy = next(args[-1] for args in connections if " hostdeploy " in args[-1])
        self.assertEqual(
            shlex.split(deploy)[:8],
            [
                "cd",
                "/srv/subway-alert",
                "&&",
                "env",
                "DOCKER_CONTEXT=default",
                "DOCKER_HOST=unix:///var/run/docker.sock",
                "python3",
                "-I",
            ],
        )
        self.assertNotIn(SECRET, repr(connections))
        for args in connections:
            if args[0] == "ssh" and " hostdeploy " not in args[-1]:
                self.assertNotIn("DOCKER_", args[-1])

    def test_invalid_host_user_port_and_source_run_never_connect(self):
        for key, value in (
            ("SSH_HOST", "staging;touch /tmp/injected"),
            ("SSH_HOST", "-oProxyCommand=bad"),
            ("SSH_HOST", "999.1.2.3"),
            ("SSH_HOST", "a..example"),
            ("SSH_USER", "root@other"),
            ("SSH_PORT", "22;id"),
            ("SSH_PORT", "0"),
            ("SSH_PORT", "65536"),
        ):
            with self.subTest(key=key, value=value):
                original = self.environment[key]
                self.environment[key] = value
                self.assertEqual(self.invoke()[0], 1)
                self.assertEqual(self.connections(), [])
                self.environment[key] = original
        for source, run in (("$(touch bad)", "17"), (SHA, "17;id"), (SHA, "0"), (SHA, "01")):
            with self.subTest(source=source, run=run):
                self.assertEqual(
                    self.invoke(
                        ["--bundle", str(self.bundle), "--source-sha", source, "--run-id", run]
                    )[0],
                    1,
                )
                self.assertEqual(self.connections(), [])

    def test_missing_or_invalid_credentials_never_connect(self):
        for key in ("SSH_HOST", "SSH_USER", "SSH_PORT", "SSH_PRIVATE_KEY", "SSH_KNOWN_HOSTS"):
            with self.subTest(key=key):
                original = self.environment.pop(key)
                self.assertEqual(self.invoke()[0], 1)
                self.assertEqual(self.connections(), [])
                self.environment[key] = original
        self.environment["SSH_PRIVATE_KEY"] = SECRET
        self.assertEqual(self.invoke()[0], 1)
        self.assertEqual(self.connections(), [])

    def test_tampered_bundle_is_rejected_before_credentials_or_connections(self):
        (self.bundle / "image.tar").write_bytes(b"changed")
        self.assertEqual(self.invoke()[1]["stage"], "bundle")
        self.assertEqual(self.boundary.calls, [])

    def test_wrong_host_or_port_pin_has_no_trust_fallback(self):
        for host in ("other.example", "staging.example", "[staging.example]:22", "*.example"):
            with self.subTest(host=host):
                self.environment["SSH_KNOWN_HOSTS"] = host + " " + self.public_key
                self.assertEqual(self.invoke()[1]["stage"], "pin")
                self.assertEqual(self.connections(), [])

    def test_invalid_pinned_key_is_rejected_before_connecting(self):
        self.environment["SSH_KNOWN_HOSTS"] = "[staging.example]:2222 ssh-ed25519 invalid-key"
        self.assertEqual(self.invoke()[1]["stage"], "pin")
        self.assertEqual(self.connections(), [])

    def test_hashed_exact_pin_is_supported_without_key_scanning(self):
        pin = self.root / "hashed"
        pin.write_text(self.environment["SSH_KNOWN_HOSTS"])
        REAL_RUN(["ssh-keygen", "-q", "-H", "-f", str(pin)], capture_output=True, check=True)
        self.environment["SSH_KNOWN_HOSTS"] = pin.read_text()
        self.assertEqual(self.invoke()[0], 0)
        keygen = [args for args, _ in self.boundary.calls if args[0] == "ssh-keygen"]
        self.assertTrue(any("-F" in args and "[staging.example]:2222" in args for args in keygen))
        self.assertTrue(any("-l" in args and "sha256" in args for args in keygen))

    def test_default_port_uses_unbracketed_host_pin(self):
        self.environment["SSH_PORT"] = "22"
        self.environment["SSH_KNOWN_HOSTS"] = "staging.example " + self.public_key
        self.assertEqual(self.invoke()[0], 0)

    def test_host_must_be_initialized_before_transfer(self):
        (self.host / ".env").unlink()
        self.assertEqual(self.invoke()[1]["stage"], "prepare")
        self.assertEqual([args[0] for args in self.connections()], ["ssh"])
        self.assertEqual(list((self.host / "incoming").iterdir()), [])

    def test_symlink_or_public_incoming_directory_is_rejected(self):
        for kind in ("public", "symlink"):
            with self.subTest(kind=kind):
                incoming = self.host / "incoming"
                if kind == "public":
                    incoming.chmod(0o755)
                else:
                    incoming.rmdir()
                    incoming.symlink_to(self.root, target_is_directory=True)
                self.assertEqual(self.invoke()[1]["stage"], "prepare")
                self.assertFalse(any(args[0] == "scp" for args in self.connections()))
                if kind == "public":
                    incoming.chmod(0o700)

    def test_untrusted_prepare_path_never_reaches_transfer_or_cleanup(self):
        self.boundary.prepare_stdout = json.dumps({"incoming": "/tmp/" + SECRET})
        self.assertEqual(self.invoke()[1]["stage"], "prepare")
        self.assertEqual([args[0] for args in self.connections()], ["ssh"])

    def test_remote_permissions_cannot_be_bypassed_with_python_optimization(self):
        self.boundary.optimize_remote = True
        (self.host / "incoming").chmod(0o755)
        self.assertEqual(self.invoke()[1]["stage"], "prepare")
        self.assertFalse(any(args[0] == "scp" for args in self.connections()))

    def test_repeated_deployments_use_fresh_private_incoming_directories(self):
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(self.invoke()[0], 0)
        targets = [args[-1] for args in self.connections() if args[0] == "scp"]
        self.assertEqual(len(set(targets)), 2)
        self.assertEqual(list((self.host / "incoming").iterdir()), [])

    def test_transfer_failure_cleans_remote_candidate_and_never_deploys(self):
        self.boundary.fail = "transfer"
        self.assertEqual(self.invoke()[1]["stage"], "transfer")
        self.assertFalse(any(" hostdeploy " in args[-1] for args in self.connections()))
        self.assertEqual(list((self.host / "incoming").iterdir()), [])

    def test_remote_failed_rollback_has_fixed_public_stage(self):
        self.boundary.remote_code = 1
        self.boundary.remote_stdout = (
            '{"status":"failed","rollback":"failed","failure":"candidate"}'
        )
        self.assertEqual(self.invoke()[1]["stage"], "rollback")
        self.assertEqual(list((self.host / "incoming").iterdir()), [])

    def test_failed_rollback_and_cleanup_are_both_visible_as_a_fixed_stage(self):
        self.boundary.remote_code = 1
        self.boundary.remote_stdout = (
            '{"status":"failed","rollback":"failed","failure":"candidate"}'
        )
        self.boundary.fail = "cleanup"
        self.assertEqual(self.invoke()[1]["stage"], "rollback-cleanup")
        self.assertEqual(len(list((self.host / "incoming").iterdir())), 1)

    def test_new_secret_files_and_upload_directory_survive_restrictive_umask(self):
        previous = os.umask(0o777)
        try:
            self.assertEqual(self.invoke()[0], 0)
        finally:
            os.umask(previous)

    def test_remote_success_is_not_inferred_from_exit_code_or_raw_output(self):
        for output in (
            SECRET,
            '{"status":"passed"}',
            '{"status":"passed","rollback":"not-needed","secret":"' + SECRET + '"}',
            '{"status":"passed","status":"failed","rollback":"not-needed"}',
            '{"status":"failed","rollback":"passed","failure":"candidate"}',
        ):
            with self.subTest(output=output):
                self.boundary.remote_stdout = output
                self.assertEqual(self.invoke()[0], 1)
                self.assertEqual(list((self.host / "incoming").iterdir()), [])

    def test_timeout_at_each_connection_stage_cleans_local_secrets(self):
        for stage in ("credential", "pin", "prepare", "transfer", "deploy", "cleanup"):
            with self.subTest(stage=stage):
                self.boundary.timeout = stage
                code, report = self.invoke()
                self.assertEqual((code, report["stage"]), (1, stage))
                self.boundary.timeout = None
                # A timeout cannot prove the remote command finished; do not assume cleanup.
                for path in (self.host / "incoming").iterdir():
                    shutil.rmtree(path)

    def test_external_launch_errors_do_not_escape_or_print_exception_details(self):
        with (
            patch.dict(os.environ, self.environment, clear=True),
            patch.object(ssh_deploy.subprocess, "run", side_effect=OSError(SECRET)),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            code = ssh_deploy.main(
                ["--bundle", str(self.bundle), "--source-sha", SHA, "--run-id", "17"]
            )
        self.assertEqual(code, 1)
        self.assertNotIn(SECRET, stdout.getvalue() + stderr.getvalue())

    def test_report_file_has_only_public_status_and_identity(self):
        report_path = self.root / "reports" / "deployment.json"
        code, report = self.invoke(
            [
                "--bundle",
                str(self.bundle),
                "--source-sha",
                SHA,
                "--run-id",
                "17",
                "--report",
                str(report_path),
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(report_path.read_text()), report)

    def test_parser_rejects_secret_argument_without_echoing_it(self):
        self.assertEqual(self.invoke(["--unknown", SECRET])[1]["stage"], "arguments")
        self.assertEqual(self.boundary.calls, [])

    def test_report_symlink_is_rejected_before_connecting(self):
        path = self.root / "report.json"
        path.symlink_to(self.host / ".env")
        self.assertEqual(
            self.invoke(
                [
                    "--bundle",
                    str(self.bundle),
                    "--source-sha",
                    SHA,
                    "--run-id",
                    "17",
                    "--report",
                    str(path),
                ]
            )[1]["stage"],
            "report",
        )
        self.assertEqual(self.connections(), [])
        self.assertEqual((self.host / ".env").read_text(), "SUBWAY_API_TOKENS=" + SECRET)


if __name__ == "__main__":
    unittest.main()
