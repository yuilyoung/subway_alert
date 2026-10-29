#!/usr/bin/env python3
"""Exercise real pinned loopback SSH and Docker deployment on a disposable CI host.

This deliberately requires an empty, precreated /srv/subway-alert and explicit
--allow-ci-host-test. It installs nothing and never repairs existing host data.
Only generated keys, this daemon, this Compose project and allowlisted files
created under the previously empty test root are eligible for cleanup.
Every Docker operation uses the standard Linux local socket and default context;
rootless and remote daemons are outside this driver's supported CI environment.
"""

import argparse
import contextlib
import hashlib
import json
import os
import pwd
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import host_init
import release
import ssh_deploy

HOST_ROOT = Path("/srv/subway-alert")
HERE = Path(__file__).resolve().parent


class SmokeFailure(Exception):
    """Fixed public stage; external errors must never become report content."""


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        raise SmokeFailure("arguments")


def require(condition, stage):
    if not condition:
        raise SmokeFailure(stage)


def child_environment():
    result = {"PATH": os.environ.get("PATH", os.defpath), "LANG": "C", "LC_ALL": "C"}
    for name in ("HOME", "DOCKER_CONTEXT", "DOCKER_HOST"):
        if name in os.environ:
            result[name] = os.environ[name]
    return result


@contextlib.contextmanager
def local_engine_environment():
    """Pin release helpers and child processes without changing Docker config."""
    home = pwd.getpwuid(os.geteuid()).pw_dir
    require(Path(home).is_absolute(), "engine")
    pinned = {
        "HOME": home,
        "DOCKER_CONTEXT": "default",
        "DOCKER_HOST": "unix:///var/run/docker.sock",
    }
    previous = {name: os.environ.get(name) for name in pinned}
    try:
        os.environ.update(pinned)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def external(args, timeout=30, environment=None):
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        stdin=subprocess.DEVNULL,
        env=environment or child_environment(),
        timeout=timeout,
    )
    require(result.returncode == 0, "external")
    return result.stdout


def host_root(empty=True, identity=None):
    root = HOST_ROOT
    for path in (*reversed(root.parents), root):
        info = path.lstat()
        require(stat.S_ISDIR(info.st_mode), "host-root")
    info = root.lstat()
    require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700, "host-root")
    require(identity is None or identity == (info.st_dev, info.st_ino), "host-root")
    require(not empty or not any(root.iterdir()), "host-root")
    return info.st_dev, info.st_ino


def project_name():
    return "subway-staging-" + hashlib.sha256(str(HOST_ROOT.resolve()).encode()).hexdigest()[:16]


def project_empty():
    label = "label=com.docker.compose.project=" + project_name()
    for resource in ("container", "network", "volume"):
        output = external(["docker", resource, "ls", "-q", "--filter", label])
        require(not output.strip(), "existing-project")


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def daemon_config(directory, port, user):
    config = directory / "sshd_config"
    ssh_deploy.private_file(
        config,
        "\n".join(
            (
                "AddressFamily inet",
                "ListenAddress 127.0.0.1",
                "Port " + str(port),
                "HostKey " + str(directory / "host"),
                "PidFile " + str(directory / "sshd.pid"),
                "AuthorizedKeysFile " + str(directory / "authorized_keys"),
                "AllowUsers " + user,
                "AuthenticationMethods publickey",
                "PubkeyAuthentication yes",
                "PasswordAuthentication no",
                "KbdInteractiveAuthentication no",
                "UsePAM no",
                "PermitRootLogin prohibit-password",
                "StrictModes yes",
                "PermitUserEnvironment no",
                "PermitUserRC no",
                "DisableForwarding yes",
                "PermitTTY no",
                "MaxAuthTries 2",
                "Subsystem sftp internal-sftp",
                "LogLevel ERROR",
            )
        ),
    )
    return config


def wait_daemon(daemon, port):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        require(daemon.poll() is None, "daemon")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                require(daemon.poll() is None, "daemon")
                return
        except OSError:
            time.sleep(0.05)
    raise SmokeFailure("daemon")


def stop_daemon(daemon):
    if daemon.poll() is None:
        daemon.terminate()
        try:
            daemon.wait(timeout=10)
        except subprocess.TimeoutExpired:
            daemon.kill()
            daemon.wait(timeout=10)
    require(daemon.poll() is not None, "daemon-cleanup")


def cleanup_host(identity, source, run):
    """Validate the entire allowlisted tree before removing any created entry."""
    host_root(empty=False, identity=identity)
    release_id = str(run) + "-" + source
    upload = re.compile(re.escape(source + "-" + str(run) + "-") + r"[a-z0-9_]{8}")
    entries = []

    def visit(path, parts):
        info = path.lstat()
        require(info.st_uid == os.geteuid(), "host-cleanup")
        if stat.S_ISDIR(info.st_mode):
            require(not info.st_mode & 0o022, "host-cleanup")
            children = list(path.iterdir())
            names = {child.name for child in children}
            if not parts:
                require(
                    names
                    <= {"incoming", "configs", "releases", ".env", ".deploy.lock", "state.json"},
                    "host-cleanup",
                )
            elif parts == ("incoming",):
                require(all(upload.fullmatch(name) for name in names), "host-cleanup")
            elif parts == ("releases",):
                require(names <= {release_id}, "host-cleanup")
            elif parts == ("configs",):
                require(names <= {release_id + ".env"}, "host-cleanup")
            else:
                require(
                    len(parts) == 2
                    and parts[0] in ("incoming", "releases")
                    and names <= release.BUNDLE_FILES,
                    "host-cleanup",
                )
            if parts:
                entries.append((path, info.st_dev, info.st_ino, True))
            for child in children:
                visit(child, (*parts, child.name))
        else:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "host-cleanup")
            require(
                (len(parts) == 1 and parts[0] in (".env", ".deploy.lock", "state.json"))
                or (len(parts) == 2 and parts[0] == "configs")
                or (len(parts) == 3 and parts[0] in ("incoming", "releases")),
                "host-cleanup",
            )
            entries.append((path, info.st_dev, info.st_ino, False))

    visit(HOST_ROOT, ())
    for path, device, inode, directory in reversed(entries):
        info = path.lstat()
        require((info.st_dev, info.st_ino) == (device, inode), "host-cleanup")
        path.rmdir() if directory else path.unlink()
    host_root(identity=identity)


def run_smoke(bundle, source, run, sshd, allow_ci_host_test, report):
    daemon = temporary = identity = manifest = values = None
    initialized = attempted = False
    engine_scope = contextlib.ExitStack()
    try:
        report["stage"] = "opt-in"
        require(allow_ci_host_test, "opt-in")
        report["stage"] = "host-root"
        identity = host_root()
        report["stage"] = "bundle"
        manifest = release.verify_bundle(bundle, source, run)
        report["checks"]["bundle"] = "passed"
        report["stage"] = "engine"
        require(
            not any(name.startswith("DOCKER_") and value for name, value in os.environ.items()),
            "engine",
        )
        # Match ssh_deploy's explicit Linux local/default endpoint. A saved
        # currentContext or an alternate ambient HOME must not redirect checks
        # or destructive Compose cleanup to an unchecked daemon.
        engine_scope.enter_context(local_engine_environment())
        release.engine_check()
        report["stage"] = "existing-project"
        project_empty()
        report["stage"] = "host-initialization"
        initialized = True
        host_init.prepare("init", HOST_ROOT, str(unused_port()))
        host_init.prepare(
            "check", HOST_ROOT, release.read_config(HOST_ROOT / ".env")["BACKEND_PORT"]
        )
        values = release.read_config(HOST_ROOT / ".env")
        report["checks"]["host-initialization"] = "passed"
        report["stage"] = "keys"
        # OpenSSH StrictModes checks every ancestor of AuthorizedKeysFile;
        # /tmp is world-writable, whereas this root and its parents are trusted.
        temporary = tempfile.TemporaryDirectory(prefix=".ssh-smoke-", dir=HOST_ROOT)
        directory = Path(temporary.name)
        for name in ("host", "client"):
            external(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(directory / name)])
        public = (directory / "client.pub").read_text().split()
        ssh_deploy.private_file(
            directory / "authorized_keys", 'restrict,from="127.0.0.1" ' + " ".join(public[:2])
        )
        user = pwd.getpwuid(os.geteuid()).pw_name
        require(re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user), "user")
        port = unused_port()
        config = daemon_config(directory, port, user)
        report["stage"] = "daemon"
        external([str(sshd), "-t", "-f", str(config)])
        daemon = subprocess.Popen(
            [str(sshd), "-D", "-e", "-f", str(config)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=child_environment(),
        )
        wait_daemon(daemon, port)
        host_public = (directory / "host.pub").read_text().split()
        environment = child_environment()
        environment.update(
            SSH_HOST="127.0.0.1",
            SSH_PORT=str(port),
            SSH_USER=user,
            SSH_PRIVATE_KEY=(directory / "client").read_text(),
            SSH_KNOWN_HOSTS="[127.0.0.1]:" + str(port) + " " + " ".join(host_public[:2]) + "\n",
        )
        report["stage"] = "ssh-deploy"
        attempted = True
        output = external(
            [
                sys.executable,
                str(HERE / "ssh_deploy.py"),
                "--bundle",
                str(bundle.resolve()),
                "--source-sha",
                source,
                "--run-id",
                str(run),
            ],
            timeout=1200,
            environment=environment,
        )
        result = json.loads(output)
        require(
            result == {"status": "passed", "stage": "complete", "sourceSHA": source, "runID": run},
            "ssh-deploy",
        )
        report["checks"]["ssh-deploy"] = "passed"
        report["stage"] = "same-image-readiness"
        state = release.state_read(HOST_ROOT)
        require(state == {"current": str(run) + "-" + source, "previous": None}, "state")
        saved = release.saved_release(HOST_ROOT, state["current"])
        require(saved[1]["imageID"] == manifest["imageID"], "image")
        release.check_ready(HOST_ROOT, saved)
        require(not any((HOST_ROOT / "incoming").iterdir()), "incoming-cleanup")
        report["checks"]["same-image-readiness"] = "passed"
        report.update(status="passed", stage="complete")
    except Exception:
        report["status"] = "failed"
    finally:
        if daemon is not None:
            try:
                stop_daemon(daemon)
                report["cleanup"]["daemon"] = "passed"
            except Exception:
                report["cleanup"]["daemon"] = "failed"
        if attempted:
            try:
                host_root(empty=False, identity=identity)
                args, environment = release.compose_command(HOST_ROOT, bundle, manifest, values)
                # Failed deployment may already have removed its saved config.
                args[args.index("--env-file") + 1] = str(HOST_ROOT / ".env")
                release.command(
                    args + ["down", "--remove-orphans", "--timeout", "20"], "cleanup", environment
                )
                project_empty()
                report["cleanup"]["project"] = "passed"
            except Exception:
                report["cleanup"]["project"] = "failed"
        if temporary is not None:
            try:
                temporary.cleanup()
                report["cleanup"]["keys"] = "passed"
            except Exception:
                report["cleanup"]["keys"] = "failed"
        if initialized:
            try:
                require(report["cleanup"]["project"] != "failed", "host-cleanup")
                cleanup_host(identity, source, run)
                report["cleanup"]["host"] = "passed"
            except Exception:
                report["cleanup"]["host"] = "failed"
        if "failed" in report["cleanup"].values():
            if report["status"] == "passed":
                report["stage"] = "cleanup"
            report["status"] = "failed"
        engine_scope.close()


def main(argv=None):
    report = {
        "status": "failed",
        "stage": "arguments",
        "checks": {
            name: "not-run"
            for name in ("bundle", "host-initialization", "ssh-deploy", "same-image-readiness")
        },
        "cleanup": {name: "not-needed" for name in ("daemon", "project", "host", "keys")},
    }
    args = None
    write_report = False
    try:
        parser = PrivateParser(description=__doc__)
        parser.add_argument("--bundle", required=True, type=Path)
        parser.add_argument("--source-sha", required=True)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--report", type=Path)
        parser.add_argument("--sshd", type=Path, default=Path("/usr/sbin/sshd"))
        parser.add_argument("--allow-ci-host-test", action="store_true")
        args = parser.parse_args(argv)
        report["stage"] = "input"
        require(
            re.fullmatch(r"[0-9a-f]{40}", args.source_sha)
            and re.fullmatch(r"[1-9][0-9]{0,14}", args.run_id)
            and args.sshd.is_absolute(),
            "input",
        )
        if args.report is not None:
            report["stage"] = "report"
            args.report = Path(os.path.abspath(args.report))
            ssh_deploy.report_destination(args.report)
            require(
                args.report.absolute() != HOST_ROOT
                and HOST_ROOT not in args.report.absolute().parents,
                "report",
            )
            write_report = True
        run_smoke(
            args.bundle,
            args.source_sha,
            int(args.run_id),
            args.sshd,
            args.allow_ci_host_test,
            report,
        )
    except Exception:
        pass
    if write_report:
        try:
            ssh_deploy.report_destination(args.report)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            release.private_write(args.report, json.dumps(report, sort_keys=True, indent=2) + "\n")
        except Exception:
            report.update(status="failed", stage="report")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
