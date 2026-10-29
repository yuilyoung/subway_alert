"""Release integrity and lifecycle tests; Docker and HTTP are external boundaries."""

import contextlib
import hashlib
import importlib.util
import io
import json
import socket
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy"))
SPEC = importlib.util.find_spec("release")
release = importlib.util.module_from_spec(SPEC) if SPEC else None
if SPEC:
    SPEC.loader.exec_module(release)
SHA = "a" * 40
TOKEN = "server-private-" + "x" * 40


def image_id(config=b"{}"):
    return "sha256:" + hashlib.sha256(config).hexdigest()


def write_image(path, config=b"{}"):
    name = hashlib.sha256(config).hexdigest() + ".json"
    with tarfile.open(path, "w") as archive:
        for filename, data in (
            (name, config),
            (
                "manifest.json",
                json.dumps([{"Config": name, "RepoTags": [], "Layers": []}]).encode(),
            ),
        ):
            entry = tarfile.TarInfo(filename)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))


class DockerBoundary:
    def __init__(self):
        self.configs = {image_id(): b"{}", image_id(b'{"new":true}'): b'{"new":true}'}
        self.events = []
        self.active = None
        self.fail_next_start = False
        self.stop_failure = None
        self.wrong_container = False
        self.wrong_loaded = False

    def __call__(self, args, **kwargs):
        if not kwargs.get("capture_output") or kwargs.get("check"):
            raise AssertionError("engine output must remain private")
        env = kwargs.get("env", {})
        self.events.append((list(args), dict(env)))
        output = ""
        if args[:3] == ["docker", "image", "inspect"]:
            output = image_id(b'{"new":true}') if self.wrong_loaded else args[-1]
        elif args[:3] == ["docker", "image", "save"]:
            write_image(args[args.index("--output") + 1], self.configs[args[-1]])
        elif args[:2] == ["docker", "load"]:
            pass
        elif args[:2] == ["docker", "version"]:
            output = "28.3.3"
        elif args[:3] == ["docker", "compose", "version"]:
            output = "2.39.4"
        elif args[:2] == ["docker", "compose"]:
            if "up" in args:
                if self.active is not None:
                    raise AssertionError("two singleton backends would run together")
                if "--no-build" not in args or "--pull" not in args:
                    raise AssertionError("deployment may not build or substitute a tag")
                try:
                    with socket.socket() as listener:
                        listener.bind(("127.0.0.1", int(env["BACKEND_PORT"])))
                except OSError:
                    return subprocess.CompletedProcess(args, 1, TOKEN, TOKEN)
                if self.fail_next_start:
                    self.fail_next_start = False
                    return subprocess.CompletedProcess(args, 1, TOKEN, TOKEN)
                self.active = (env["SUBWAY_IMAGE"], env["BACKEND_PORT"])
            elif "down" in args:
                failure, self.stop_failure = self.stop_failure, None
                if failure == "before":
                    return subprocess.CompletedProcess(args, 1, TOKEN, TOKEN)
                self.active = None
                if failure == "after":
                    return subprocess.CompletedProcess(args, 1, TOKEN, TOKEN)
            elif "ps" in args:
                output = "f" * 64 if self.active else ""
            else:
                raise AssertionError("unexpected compose operation")
        elif args[:2] == ["docker", "inspect"]:
            identity, port = self.active
            output = json.dumps(
                {
                    "image": image_id(b'{"new":true}') if self.wrong_container else identity,
                    "running": True,
                    "health": "healthy",
                    "healthcheck": True,
                    "readonly": True,
                    "cap_drop": ["ALL"],
                    "security_opt": ["no-new-privileges:true"],
                    "tmpfs": {"/tmp": "rw"},
                    "ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]},
                    "sample": True,
                    "fcm_disabled": True,
                    "memory": True,
                }
            )
        elif args[:2] == ["docker", "exec"]:
            output = "10001\n"
        else:
            raise AssertionError("unexpected Docker command: " + repr(args))
        return subprocess.CompletedProcess(args, 0, output, "")


def http_ok(port, path, token=None, session_token=None):
    if path == "/api/health":
        return 200, {"content-type": "application/json"}, b'{"status":"ok"}'
    if path == "/api/lines":
        return (200, {}, b"[]") if token else (401, {}, b"{}")
    return (
        404,
        {"content-type": "application/json"},
        json.dumps({"status": 404, "error": "Not Found", "path": path}).encode(),
    )


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(release, "the strict release bundle/deployment CLI is missing")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.docker = DockerBoundary()
        self.engine = patch.object(release.subprocess, "run", side_effect=self.docker)
        self.engine.start()
        self.addCleanup(self.engine.stop)

    def bundle(self, run=17, image=None):
        path = self.root / ("bundle-" + str(run))
        release.build_bundle(path, SHA, run, image or image_id())
        return path

    def host(self):
        path = self.root / "host"
        path.mkdir(mode=0o700)
        (path / ".env").write_text("BACKEND_PORT=43127\nSUBWAY_API_TOKENS=" + TOKEN + "\n")
        (path / ".env").chmod(0o600)
        return path

    def test_bundle_records_exact_source_run_image_and_payload_hashes(self):
        bundle = self.bundle()
        manifest = release.verify_bundle(bundle, SHA, 17)
        self.assertEqual(manifest["sourceSHA"], SHA)
        self.assertEqual(manifest["runID"], 17)
        self.assertEqual(manifest["imageID"], image_id())
        self.assertEqual(
            set(p.name for p in bundle.iterdir()),
            {"manifest.json", "SHA256SUMS", "image.tar", "release.py", "compose.staging.yaml"},
        )

    def test_tampering_missing_extra_and_symlink_files_are_rejected(self):
        for mutation in ("changed", "missing", "extra", "symlink", "manifest", "checksums"):
            with self.subTest(mutation=mutation):
                bundle = self.bundle(17 + len(list(self.root.iterdir())))
                if mutation == "changed":
                    (bundle / "image.tar").write_bytes(b"tampered")
                elif mutation == "missing":
                    (bundle / "image.tar").unlink()
                elif mutation == "extra":
                    (bundle / ".env").write_text(TOKEN)
                elif mutation == "symlink":
                    (bundle / "image.tar").unlink()
                    (bundle / "image.tar").symlink_to("/etc/passwd")
                elif mutation == "manifest":
                    (bundle / "manifest.json").write_text("{}")
                else:
                    (bundle / "SHA256SUMS").write_text("")
                with self.assertRaises(release.ReleaseFailure):
                    release.verify_bundle(bundle, SHA, int(bundle.name.split("-")[-1]))

    def test_wrong_source_run_and_mutable_or_invalid_image_are_rejected(self):
        bundle = self.bundle()
        for sha, run in (("b" * 40, 17), (SHA, 18), ("short", 17), (SHA, 0)):
            with self.subTest(sha=sha, run=run), self.assertRaises(release.ReleaseFailure):
                release.verify_bundle(bundle, sha, run)
        for identity in ("backend:latest", "sha256:abc", "sha256:" + "A" * 64, ""):
            with self.subTest(identity=identity), self.assertRaises(release.ReleaseFailure):
                release.build_bundle(self.root / "invalid", SHA, 20, identity)

    def test_rehashed_wrong_image_archive_is_rejected(self):
        bundle = self.bundle()
        write_image(bundle / "image.tar", b'{"wrong":true}')
        release.write_metadata(bundle, SHA, 17, image_id())
        with self.assertRaises(release.ReleaseFailure):
            release.verify_bundle(bundle, SHA, 17)

    def test_loaded_image_identity_must_match_before_stopping_current_service(self):
        bundle = self.bundle()
        host = self.host()
        self.docker.wrong_loaded = True
        result = release.deploy_bundle(host, bundle, SHA, 17)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(any("up" in args for args, _ in self.docker.events))
        self.assertIsNone(self.docker.active)

    def test_success_checks_monitor_store_and_preserves_private_configuration(self):
        bundle, host = self.bundle(), self.host()
        seen = []

        def request(*args):
            seen.append(args)
            return http_ok(*args)

        with patch.object(release, "http_request", side_effect=request):
            result = release.deploy_bundle(host, bundle, SHA, 17)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(self.docker.active, (image_id(), "43127"))
        monitor = [args for args in seen if args[1].startswith("/api/monitor-sessions/")]
        self.assertEqual(len(monitor), 1)
        self.assertEqual(monitor[0][2], TOKEN)
        self.assertGreaterEqual(len(monitor[0][3]), 32)
        self.assertEqual((host / "configs" / ("17-" + SHA + ".env")).stat().st_mode & 0o777, 0o600)
        self.assertNotIn(TOKEN, json.dumps(result))

    def test_storage_failure_does_not_pass_liveness_only_and_first_failure_cleans_candidate(self):
        bundle, host = self.bundle(), self.host()

        def broken_store(port, path, token=None, secret=None):
            if path.startswith("/api/monitor-sessions/"):
                return 503, {"content-type": "application/json"}, b'{"status":503}'
            return http_ok(port, path, token, secret)

        with patch.object(release, "http_request", side_effect=broken_store):
            result = release.deploy_bundle(host, bundle, SHA, 17)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["rollback"], "not-needed")
        self.assertIsNone(self.docker.active)
        self.assertFalse((host / "state.json").exists())

    def test_runtime_image_mismatch_is_rejected(self):
        bundle, host = self.bundle(), self.host()
        self.docker.wrong_container = True
        with patch.object(release, "http_request", side_effect=http_ok):
            result = release.deploy_bundle(host, bundle, SHA, 17)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(self.docker.active)

    def test_failed_candidate_rolls_back_prior_image_and_configuration_and_checks_it(self):
        old, candidate, host = (
            self.bundle(),
            self.bundle(18, image_id(b'{"new":true}')),
            self.host(),
        )
        with patch.object(release, "http_request", side_effect=http_ok):
            self.assertEqual(release.deploy_bundle(host, old, SHA, 17)["status"], "passed")
            (host / ".env").write_text("BACKEND_PORT=43128\nSUBWAY_API_TOKENS=" + "y" * 48 + "\n")
            self.docker.fail_next_start = True
            result = release.deploy_bundle(host, candidate, SHA, 18)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["rollback"], "passed")
        self.assertEqual(self.docker.active, (image_id(), "43127"))
        state = json.loads((host / "state.json").read_text())
        self.assertEqual(state["current"], "17-" + SHA)
        self.assertTrue((host / "releases" / ("17-" + SHA) / "image.tar").exists())
        self.assertFalse(any("build" in args for args, _ in self.docker.events))

    def test_failed_stop_restores_current_after_partial_or_no_container_removal(self):
        for failure in ("before", "after"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                old, candidate = self.bundle(17), self.bundle(18, image_id(b'{"new":true}'))
                host = Path(directory)
                (host / ".env").write_text("BACKEND_PORT=43127\nSUBWAY_API_TOKENS=" + TOKEN + "\n")
                (host / ".env").chmod(0o600)
                with patch.object(release, "http_request", side_effect=http_ok):
                    self.assertEqual(release.deploy_bundle(host, old, SHA, 17)["status"], "passed")
                    self.docker.stop_failure = failure
                    result = release.deploy_bundle(host, candidate, SHA, 18)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["rollback"], "passed")
                self.assertEqual(self.docker.active, (image_id(), "43127"))
                self.assertEqual(
                    json.loads((host / "state.json").read_text())["current"], "17-" + SHA
                )
                self.assertFalse((host / "releases" / ("18-" + SHA)).exists())
                self.docker.active = None
                release.shutil.rmtree(old)
                release.shutil.rmtree(candidate)

    def test_manual_rollback_recovers_current_when_stop_partially_fails(self):
        old, candidate, host = (
            self.bundle(),
            self.bundle(18, image_id(b'{"new":true}')),
            self.host(),
        )
        with patch.object(release, "http_request", side_effect=http_ok):
            release.deploy_bundle(host, old, SHA, 17)
            release.deploy_bundle(host, candidate, SHA, 18)
            for failure in ("before", "after"):
                with self.subTest(failure=failure):
                    self.docker.stop_failure = failure
                    result = release.rollback(host)
                    self.assertEqual(result["status"], "failed")
                    self.assertEqual(result["rollback"], "restored-current")
                    self.assertEqual(self.docker.active, (image_id(b'{"new":true}'), "43127"))
                    self.assertEqual(
                        json.loads((host / "state.json").read_text())["current"], "18-" + SHA
                    )

    def test_incomplete_candidate_preparation_is_removed_and_retry_can_deploy(self):
        bundle = self.bundle()
        real_write = release.private_write
        for failure in ("copy", "config"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                host = Path(directory)
                (host / ".env").write_text("BACKEND_PORT=43127\nSUBWAY_API_TOKENS=" + TOKEN + "\n")
                (host / ".env").chmod(0o600)

                def fail_copy(source, destination):
                    destination.mkdir()
                    (destination / "partial").write_bytes(b"incomplete")
                    raise OSError("injected partial copy failure")

                def fail_config(path, text):
                    if path.parent.name == "configs":
                        raise OSError("injected snapshot failure")
                    return real_write(path, text)

                with (
                    patch.object(release.shutil, "copytree", side_effect=fail_copy)
                    if failure == "copy"
                    else patch.object(release, "private_write", side_effect=fail_config)
                ):
                    result = release.deploy_bundle(host, bundle, SHA, 17)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(list((host / "releases").iterdir()), [])
                self.assertEqual(list((host / "configs").iterdir()), [])
                self.assertFalse((host / "state.json").exists())
                with patch.object(release, "http_request", side_effect=http_ok):
                    retry = release.deploy_bundle(host, bundle, SHA, 17)
                self.assertEqual(retry["status"], "passed")
                self.assertEqual(self.docker.active, (image_id(), "43127"))
                self.docker.active = None

    def test_failed_rollback_readiness_is_reported_failed(self):
        old, candidate, host = (
            self.bundle(),
            self.bundle(18, image_id(b'{"new":true}')),
            self.host(),
        )
        with patch.object(release, "http_request", side_effect=http_ok):
            release.deploy_bundle(host, old, SHA, 17)
        self.docker.fail_next_start = True
        with patch.object(release, "http_request", return_value=(503, {}, b"{}")):
            result = release.deploy_bundle(host, candidate, SHA, 18)
        self.assertEqual(result["rollback"], "failed")
        self.assertEqual(result["status"], "failed")

    def test_manual_rollback_restores_previous_saved_image(self):
        old, candidate, host = (
            self.bundle(),
            self.bundle(18, image_id(b'{"new":true}')),
            self.host(),
        )
        with patch.object(release, "http_request", side_effect=http_ok):
            release.deploy_bundle(host, old, SHA, 17)
            release.deploy_bundle(host, candidate, SHA, 18)
            result = release.rollback(host)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(self.docker.active[0], image_id())
        self.assertEqual(json.loads((host / "state.json").read_text())["previous"], "18-" + SHA)

    def test_untrusted_env_and_corrupt_state_fail_before_any_start(self):
        bundle = self.bundle()
        for case in ("permissions", "live-key", "empty-token", "oversized-token", "state"):
            with self.subTest(case=case):
                host = self.root / case
                host.mkdir(mode=0o700)
                config = host / ".env"
                config.write_text("BACKEND_PORT=43127\nSUBWAY_API_TOKENS=" + TOKEN + "\n")
                config.chmod(0o644 if case == "permissions" else 0o600)
                if case == "live-key":
                    config.write_text(config.read_text() + "SEOUL_SUBWAY_KEY=live-secret\n")
                elif case == "empty-token":
                    config.write_text("BACKEND_PORT=43127\nSUBWAY_API_TOKENS=\n")
                elif case == "oversized-token":
                    config.write_text("BACKEND_PORT=43127\nSUBWAY_API_TOKENS=" + "z" * 129 + "\n")
                elif case == "state":
                    (host / "state.json").write_text('{"current":"../../outside","previous":null}')
                    (host / "state.json").chmod(0o600)
                before = len(self.docker.events)
                result = release.deploy_bundle(host, bundle, SHA, 17)
                self.assertEqual(result["status"], "failed")
                self.assertIsNone(self.docker.active)
                self.assertFalse(any("up" in args for args, _ in self.docker.events[before:]))

    def test_rehashed_changed_execution_tool_is_rejected(self):
        bundle = self.bundle()
        (bundle / "release.py").write_text("print('untrusted code')\n")
        release.write_metadata(bundle, SHA, 17, image_id())
        with self.assertRaises(release.ReleaseFailure):
            release.verify_bundle(bundle, SHA, 17)

    def test_readiness_rejects_open_auth_and_non_json_unknown_route(self):
        for case in ("open", "html", "wrong-path", "wrong-status"):
            with self.subTest(case=case):
                bundle = self.bundle(17 + len(list(self.root.iterdir())))
                host = self.root / ("host-" + case)
                host.mkdir(mode=0o700)
                (host / ".env").write_text("BACKEND_PORT=43127\nSUBWAY_API_TOKENS=" + TOKEN + "\n")
                (host / ".env").chmod(0o600)

                def response(port, path, token=None, secret=None):
                    if case == "open" and path == "/api/lines" and not token:
                        return 200, {}, b"[]"
                    if path.startswith("/api/monitor-sessions/"):
                        if case == "html":
                            return 404, {"content-type": "text/html"}, b"not found"
                        if case == "wrong-path":
                            return (
                                404,
                                {"content-type": "application/json"},
                                b'{"status":404,"path":"/wrong"}',
                            )
                        if case == "wrong-status":
                            return 404, {"content-type": "application/json"}, b'{"status":503}'
                    return http_ok(port, path, token, secret)

                with patch.object(release, "http_request", side_effect=response):
                    result = release.deploy_bundle(
                        host, bundle, SHA, int(bundle.name.split("-")[-1])
                    )
                self.assertEqual(result["status"], "failed")
                self.assertIsNone(self.docker.active)

    def test_concurrent_host_deployment_is_rejected_before_start(self):
        bundle, host = self.bundle(), self.host()
        with release.host_lock(host), patch.object(release, "http_request", side_effect=http_ok):
            result = release.deploy_bundle(host, bundle, SHA, 17)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(self.docker.active)

    def test_ambient_application_and_compose_configuration_cannot_reach_docker(self):
        bundle, host = self.bundle(), self.host()
        with (
            patch.dict(
                release.os.environ,
                {
                    "COMPOSE_FILE": "hostile.yaml",
                    "FCM_ENABLED": "true",
                    "SPRING_APPLICATION_JSON": "private-settings",
                    "SEOUL_SUBWAY_KEY": "live-key",
                    "MONITOR_DB_URL": "private-db",
                    "JAVA_TOOL_OPTIONS": "private-options",
                },
            ),
            patch.object(release, "http_request", side_effect=http_ok),
        ):
            result = release.deploy_bundle(host, bundle, SHA, 17)
        self.assertEqual(result["status"], "passed")
        for _, environment in self.docker.events:
            for key in (
                "COMPOSE_FILE",
                "FCM_ENABLED",
                "SPRING_APPLICATION_JSON",
                "SEOUL_SUBWAY_KEY",
                "MONITOR_DB_URL",
                "JAVA_TOOL_OPTIONS",
            ):
                self.assertNotIn(key, environment)

    def test_smoke_runs_readiness_rollback_and_cleanup_using_one_immutable_image(self):
        bundle = self.bundle()
        with patch.object(release, "http_request", side_effect=http_ok):
            report = release.smoke_bundle(bundle, SHA, 17)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["rollback"], "passed")
        self.assertEqual(report["cleanup"], "passed")
        self.assertIsNone(self.docker.active)
        self.assertFalse(any("build" in args or "rm" in args for args, _ in self.docker.events))

    def test_cli_redacts_external_failures(self):
        with (
            patch.object(release.subprocess, "run", side_effect=OSError(TOKEN)),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = release.main(
                [
                    "bundle",
                    "--output",
                    str(self.root / "out"),
                    "--source-sha",
                    SHA,
                    "--run-id",
                    "17",
                    "--image",
                    image_id(),
                ]
            )
        self.assertEqual(code, 1)
        self.assertNotIn(TOKEN, stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
