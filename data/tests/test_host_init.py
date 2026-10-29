"""Host initialization uses real private files; Docker is an external boundary."""

import contextlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy"))
SPEC = importlib.util.find_spec("host_init")
host_init = importlib.util.module_from_spec(SPEC) if SPEC else None
if SPEC:
    SPEC.loader.exec_module(host_init)
TOKEN = "private-" + "x" * 40


class HostInitializationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(host_init, "host initialization CLI is missing")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.parent = Path(self.directory.name)
        self.root = self.parent / "staging"

    def invoke(self, action="init", *arguments, root=None):
        with (
            contextlib.redirect_stdout(io.StringIO()) as stdout,
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            code = host_init.main([action, "--root", str(root or self.root), *arguments])
        return code, stdout.getvalue(), stderr.getvalue()

    def existing(self, port="8080", token=TOKEN):
        self.root.mkdir(mode=0o700)
        for name in ("incoming", "configs", "releases"):
            (self.root / name).mkdir(mode=0o700)
        config = self.root / ".env"
        config.write_text(f"BACKEND_PORT={port}\nSUBWAY_API_TOKENS={token}\n")
        config.chmod(0o600)
        return config

    def assert_failed(self, result):
        code, stdout, stderr = result
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["status"], "failed")
        self.assertNotIn(TOKEN, stdout + stderr)
        self.assertNotIn("Traceback", stdout + stderr)

    def test_new_host_has_only_owner_directory_and_single_private_generated_token(self):
        code, stdout, stderr = self.invoke("init", "--port", "43127")
        self.assertEqual(code, 0, stdout + stderr)
        self.assertEqual(json.loads(stdout)["status"], "passed")
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(self.root.stat().st_uid, os.geteuid())
        self.assertEqual(
            {p.name for p in self.root.iterdir()}, {".env", "incoming", "configs", "releases"}
        )
        for name in ("incoming", "configs", "releases"):
            self.assertEqual(stat.S_IMODE((self.root / name).stat().st_mode), 0o700)
            self.assertEqual((self.root / name).stat().st_uid, os.geteuid())
        config = self.root / ".env"
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
        self.assertEqual(config.stat().st_uid, os.geteuid())
        content = config.read_text()
        self.assertRegex(content, r"\ABACKEND_PORT=43127\nSUBWAY_API_TOKENS=[A-Za-z0-9_-]{43}\n\Z")
        token = content.split("SUBWAY_API_TOKENS=", 1)[1].strip()
        self.assertNotIn(token, stdout + stderr)
        self.assertEqual(host_init.release.read_config(config)["BACKEND_PORT"], "43127")

    def test_second_initialization_and_check_preserve_existing_bytes_and_metadata(self):
        config = self.existing()
        marker = self.root / "operator-data"
        marker.write_bytes(b"keep")
        snapshots = [(p.read_bytes(), p.stat()) for p in (config, marker)]
        root_info = self.root.stat()
        with (
            patch.object(
                host_init.secrets, "token_urlsafe", side_effect=AssertionError("new token")
            ),
            patch.object(host_init.os, "chmod", side_effect=AssertionError("chmod")),
            patch.object(host_init.os, "fchmod", side_effect=AssertionError("fchmod")),
        ):
            for action in ("init", "check"):
                with self.subTest(action=action):
                    self.assertEqual(self.invoke(action)[0], 0)
        for path, (content, info) in zip((config, marker), snapshots):
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(path.stat().st_mtime_ns, info.st_mtime_ns)
            self.assertEqual(path.stat().st_ctime_ns, info.st_ctime_ns)
            self.assertEqual(path.stat().st_ino, info.st_ino)
        self.assertEqual(self.root.stat().st_mtime_ns, root_info.st_mtime_ns)
        self.assertEqual(self.root.stat().st_ctime_ns, root_info.st_ctime_ns)

    def test_existing_private_directory_can_be_initialized_without_removing_operator_data(self):
        self.root.mkdir(mode=0o700)
        marker = self.root / "operator-data"
        marker.write_bytes(b"keep")
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(marker.read_bytes(), b"keep")
        self.assertTrue((self.root / ".env").is_file())

    def test_check_does_not_create_missing_root_or_configuration(self):
        self.assert_failed(self.invoke("check"))
        self.assertFalse(self.root.exists())
        self.root.mkdir(mode=0o700)
        self.assert_failed(self.invoke("check"))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_requested_ports_fail_without_mutation_or_echoing_input(self):
        for port in ("0", "65536", "-1", "08080", "1.2", TOKEN):
            for action in ("init", "check"):
                with self.subTest(port=port, action=action):
                    self.assert_failed(self.invoke(action, "--port", port))
                    self.assertFalse(self.root.exists())

    def test_lowest_and_highest_valid_ports_are_accepted(self):
        for port in ("1", "65535"):
            with self.subTest(port=port), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "host"
                self.assertEqual(self.invoke("init", "--port", port, root=root)[0], 0)
                self.assertTrue(
                    (root / ".env").read_text().startswith("BACKEND_PORT=" + port + "\n")
                )

    def test_existing_port_mismatch_fails_without_changing_configuration(self):
        config = self.existing(port="43127")
        before = config.read_bytes()
        for action in ("init", "check"):
            with self.subTest(action=action):
                self.assert_failed(self.invoke(action))
                self.assertEqual(config.read_bytes(), before)
                self.assertEqual(self.invoke(action, "--port", "43127")[0], 0)

    def test_symlink_root_and_ancestor_and_configuration_are_rejected(self):
        target = self.parent / "target"
        target.mkdir(mode=0o700)
        for case in ("root", "ancestor", "config", "dangling"):
            with self.subTest(case=case):
                if case == "root":
                    self.root.symlink_to(target, target_is_directory=True)
                    root = self.root
                elif case == "ancestor":
                    link = self.parent / "ancestor"
                    link.symlink_to(target, target_is_directory=True)
                    root = link / "child"
                else:
                    self.root.mkdir(mode=0o700)
                    destination = target / ("missing" if case == "dangling" else "config")
                    if case == "config":
                        destination.write_text(TOKEN)
                        destination.chmod(0o600)
                    (self.root / ".env").symlink_to(destination)
                    root = self.root
                for action in ("init", "check"):
                    self.assert_failed(self.invoke(action, root=root))
                self.assertFalse((target / "child").exists())
                if self.root.is_symlink():
                    self.root.unlink()
                elif self.root.exists():
                    (self.root / ".env").unlink()
                    self.root.rmdir()
        self.assertEqual((target / "config").read_text(), TOKEN)

    def test_wrong_root_types_and_permissions_are_rejected_without_repair(self):
        self.root.write_text(TOKEN)
        self.assert_failed(self.invoke())
        self.assertEqual(self.root.read_text(), TOKEN)
        self.root.unlink()
        for mode in (0o777, 0o750, 0o755):
            with self.subTest(mode=mode):
                self.root.mkdir(mode=mode)
                self.root.chmod(mode)
                self.assert_failed(self.invoke())
                self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), mode)
                self.assertEqual(list(self.root.iterdir()), [])
                self.root.rmdir()

    def test_configuration_hard_links_are_rejected_without_changing_the_shared_file(self):
        config = self.existing()
        alias = self.parent / "shared-config"
        os.link(config, alias)
        before = alias.read_bytes()
        for action in ("init", "check"):
            with self.subTest(action=action):
                self.assert_failed(self.invoke(action))
        self.assertEqual(alias.read_bytes(), before)
        self.assertEqual(config.stat().st_nlink, 2)

    def test_directory_failure_removes_only_new_entries_and_allows_retry(self):
        self.root.mkdir(mode=0o700)
        releases = self.root / "releases"
        releases.mkdir(mode=0o700)
        (releases / "operator-data").write_bytes(b"keep")
        real_mkdir = host_init.os.mkdir

        def failed_mkdir(path, *args, **kwargs):
            if Path(path).name == "configs":
                raise OSError(TOKEN)
            return real_mkdir(path, *args, **kwargs)

        with patch.object(host_init.os, "mkdir", side_effect=failed_mkdir):
            self.assert_failed(self.invoke())
        self.assertEqual({p.name for p in self.root.iterdir()}, {"releases"})
        self.assertEqual((releases / "operator-data").read_bytes(), b"keep")
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual((releases / "operator-data").read_bytes(), b"keep")

    def test_wrong_configuration_types_permissions_and_contents_are_not_changed(self):
        cases = (
            "directory",
            "fifo",
            "permissions",
            "missing-key",
            "unknown-key",
            "duplicate-key",
            "multiple-tokens",
            "invalid-port",
            "invalid-encoding",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                root.chmod(0o700)
                config = root / ".env"
                if case == "directory":
                    config.mkdir(mode=0o700)
                elif case == "fifo":
                    os.mkfifo(config, 0o600)
                else:
                    content = f"BACKEND_PORT=8080\nSUBWAY_API_TOKENS={TOKEN}\n".encode()
                    if case == "missing-key":
                        content = b"BACKEND_PORT=8080\n"
                    elif case == "unknown-key":
                        content += b"SEOUL_SUBWAY_KEY=private\n"
                    elif case == "duplicate-key":
                        content += b"BACKEND_PORT=8081\n"
                    elif case == "multiple-tokens":
                        content = content.replace(TOKEN.encode(), TOKEN.encode() + b",another")
                    elif case == "invalid-port":
                        content = content.replace(b"8080", b"0")
                    elif case == "invalid-encoding":
                        content += b"\xff"
                    config.write_bytes(content)
                    config.chmod(0o644 if case == "permissions" else 0o600)
                before = config.lstat()
                for action in ("init", "check"):
                    self.assert_failed(self.invoke(action, root=root))
                self.assertEqual(config.lstat().st_ino, before.st_ino)
                self.assertEqual(config.lstat().st_mode, before.st_mode)
                self.assertEqual(config.lstat().st_mtime_ns, before.st_mtime_ns)
                if stat.S_ISREG(before.st_mode):
                    self.assertEqual(config.read_bytes(), content)

    def test_existing_runtime_directories_are_validated_without_modifying_their_data(self):
        for name in ("incoming", "configs", "releases"):
            for kind in ("symlink", "file", "permissions"):
                with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    root.chmod(0o700)
                    path = root / name
                    if kind == "symlink":
                        target = root / "target"
                        target.mkdir(mode=0o700)
                        path.symlink_to(target, target_is_directory=True)
                    elif kind == "file":
                        path.write_text(TOKEN)
                    else:
                        path.mkdir(mode=0o777)
                        path.chmod(0o777)
                        (path / "operator-data").write_bytes(b"keep")
                    before = {p.name for p in root.iterdir()}
                    for action in ("init", "check"):
                        self.assert_failed(self.invoke(action, root=root))
                        self.assertEqual({p.name for p in root.iterdir()}, before)
                    if kind == "permissions":
                        self.assertEqual((path / "operator-data").read_bytes(), b"keep")
                        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o777)

    def test_wrong_owner_root_or_configuration_is_rejected(self):
        self.existing()
        # A changed effective UID lets the real stat results exercise both checks
        # without requiring privileged chown in the test environment.
        uid = os.geteuid()
        with patch.object(host_init.os, "geteuid", return_value=uid + 1):
            self.assert_failed(self.invoke())
        real_regular = host_init.release.regular

        def wrong_config_owner(path, private=False):
            with patch.object(host_init.release.os, "geteuid", return_value=uid + 1):
                return real_regular(path, private)

        with patch.object(host_init.release, "regular", side_effect=wrong_config_owner):
            self.assert_failed(self.invoke())

    def test_engine_checks_are_optional_and_failure_precedes_any_mutation(self):
        with patch.object(host_init.release.subprocess, "run", side_effect=OSError(TOKEN)):
            self.assert_failed(self.invoke("init", "--check-engine"))
            self.assertFalse(self.root.exists())
            self.assertEqual(self.invoke()[0], 0)
            before = (self.root / ".env").read_bytes()
            self.assert_failed(self.invoke("check", "--check-engine"))
            self.assertEqual((self.root / ".env").read_bytes(), before)

    def test_engine_check_uses_existing_docker_version_and_compose_policy(self):
        calls = []

        def engine(args, **kwargs):
            calls.append(args)
            if args == ["docker", "version", "--format", "{{.Server.Version}}"]:
                return subprocess.CompletedProcess(args, 0, "28.0.0\n", "")
            if args == ["docker", "compose", "version", "--short"]:
                return subprocess.CompletedProcess(args, 0, "2.40.0\n", "")
            raise AssertionError("unexpected external command")

        with patch.object(host_init.release.subprocess, "run", side_effect=engine):
            self.assertEqual(self.invoke("init", "--check-engine")[0], 0)
        self.assertEqual(len(calls), 2)

    def test_engine_check_pins_local_linux_daemon_and_restores_environment_before_creation(self):
        calls = []
        creation_environments = []
        ambient = {
            "DOCKER_HOST": "tcp://production.invalid:2376",
            "DOCKER_CONTEXT": "production",
            "DOCKER_CONFIG": "/private/docker-config",
            "DOCKER_TLS": "1",
            "DOCKER_TLS_VERIFY": "1",
            "DOCKER_CERT_PATH": "/private/docker-certs",
            "HOST_INIT_KEEP": "preserved",
        }

        def engine(args, **kwargs):
            calls.append((args, kwargs["env"].copy()))
            self.assertFalse(self.root.exists())
            version = "28.0.0\n" if args[1] == "version" else "2.40.0\n"
            return subprocess.CompletedProcess(args, 0, version, "")

        def token(size):
            creation_environments.append(dict(os.environ))
            return "t" * 43

        with patch.dict(host_init.os.environ, ambient):
            before = dict(os.environ)
            with (
                patch.object(host_init.release.subprocess, "run", side_effect=engine),
                patch.object(host_init.secrets, "token_urlsafe", side_effect=token),
            ):
                self.assertEqual(self.invoke("init", "--check-engine")[0], 0)
            self.assertTrue(dict(os.environ) == before, "environment was not restored")
            self.assertTrue(
                creation_environments == [before], "engine environment leaked into host creation"
            )
        self.assertEqual(len(calls), 2)
        for _, environment in calls:
            self.assertEqual(environment.get("DOCKER_HOST"), "unix:///var/run/docker.sock")
            self.assertEqual(environment.get("DOCKER_CONTEXT"), "default")
            for name in ("DOCKER_CONFIG", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
                self.assertNotIn(name, environment)

    def test_engine_failure_restores_full_environment_and_creates_nothing(self):
        observed = []
        ambient = {
            "DOCKER_HOST": "tcp://production.invalid:2376",
            "DOCKER_CONTEXT": "production",
            "DOCKER_CONFIG": "/private/docker-config",
            "DOCKER_TLS": "1",
            "DOCKER_TLS_VERIFY": "1",
            "DOCKER_CERT_PATH": "/private/docker-certs",
            "HOST_INIT_KEEP": "preserved",
        }

        def failure(args, **kwargs):
            observed.append(kwargs["env"].copy())
            os.environ["DOCKER_CONTEXT"] = "changed-by-engine"
            os.environ["HOST_INIT_CHECK_ONLY"] = "temporary"
            os.environ.pop("HOST_INIT_KEEP", None)
            raise OSError(TOKEN)

        with patch.dict(host_init.os.environ, ambient):
            before = dict(os.environ)
            with patch.object(host_init.release.subprocess, "run", side_effect=failure):
                self.assert_failed(self.invoke("init", "--check-engine"))
            self.assertTrue(dict(os.environ) == before, "environment was not restored")
        self.assertFalse(self.root.exists())
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0].get("DOCKER_HOST"), "unix:///var/run/docker.sock")
        self.assertEqual(observed[0].get("DOCKER_CONTEXT"), "default")
        for name in ("DOCKER_CONFIG", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
            self.assertNotIn(name, observed[0])

    def test_partial_configuration_write_is_removed_and_retry_succeeds(self):
        real_fdopen = host_init.os.fdopen

        @contextlib.contextmanager
        def partial_write(descriptor, *args, **kwargs):
            with real_fdopen(descriptor, *args, **kwargs) as stream:
                stream.write("SUBWAY_API_TOKENS=" + TOKEN)
                stream.flush()
                raise OSError(TOKEN)
                yield stream

        for preexisting in (False, True):
            with self.subTest(preexisting=preexisting):
                if preexisting:
                    self.root.mkdir(mode=0o700)
                    (self.root / "operator-data").write_bytes(b"keep")
                with patch.object(host_init.os, "fdopen", side_effect=partial_write):
                    self.assert_failed(self.invoke())
                self.assertEqual(self.root.exists(), preexisting)
                if preexisting:
                    self.assertEqual((self.root / "operator-data").read_bytes(), b"keep")
                    self.assertEqual({p.name for p in self.root.iterdir()}, {"operator-data"})
                self.assertEqual(self.invoke()[0], 0)
                (self.root / ".env").unlink()
                for name in ("incoming", "configs", "releases"):
                    (self.root / name).rmdir()
                if preexisting:
                    (self.root / "operator-data").unlink()
                self.root.rmdir()

    def test_new_files_get_exact_private_permissions_even_with_restrictive_umask(self):
        previous = os.umask(0o777)
        try:
            self.assertEqual(self.invoke()[0], 0)
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.root / ".env").stat().st_mode), 0o600)
        for name in ("incoming", "configs", "releases"):
            self.assertEqual(stat.S_IMODE((self.root / name).stat().st_mode), 0o700)

    def test_external_failure_and_secret_values_never_reach_cli_output(self):
        with patch.object(host_init.secrets, "token_urlsafe", side_effect=OSError(TOKEN)):
            self.assert_failed(self.invoke())
        self.assertFalse(self.root.exists())
        with patch.object(host_init.secrets, "token_urlsafe", return_value=TOKEN):
            # A generator violating its 43-character contract fails closed.
            self.assert_failed(self.invoke())
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
