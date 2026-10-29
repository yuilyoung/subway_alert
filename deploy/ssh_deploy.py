#!/usr/bin/env python3
"""Promote one verified staging bundle using an explicitly pinned SSH identity.

The host must already be initialized at /srv/subway-alert. SSH credentials and
all external output remain private; reports contain fixed stages and validated
source/run identities only. Image replacement and rollback belong to release.py.
Deployment uses Linux's local default Docker daemon; rootless and remote Docker
daemons are unsupported by this transport.
"""

import argparse
import ipaddress
import json
import os
import re
import shlex
import stat
import subprocess
import tempfile
from pathlib import Path

import release

REMOTE_ROOT = "/srv/subway-alert"
FILES = ("compose.staging.yaml", "image.tar", "manifest.json", "release.py", "SHA256SUMS")
# This script only prepares/removes a private upload directory. It never edits
# host configuration, release snapshots, or deployment state.
REMOTE_DIRECTORY = """import json, os, re, stat, sys, tempfile
from pathlib import Path
action, root, value = sys.argv[1:]
root = Path(root)
def check(condition):
    if not condition:
        raise ValueError('directory policy')
def private(path, mode, directory):
    info = path.lstat()
    check(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
    check(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == mode)
private(root, 0o700, True)
private(root / '.env', 0o600, False)
for name in ('incoming', 'configs', 'releases'):
    private(root / name, 0o700, True)
if action == 'prepare':
    check(re.fullmatch(r'[0-9a-f]{40}-[1-9][0-9]{0,14}', value))
    path = tempfile.mkdtemp(prefix=value + '-', dir=root / 'incoming')
    os.chmod(path, 0o700)
    print(json.dumps({'incoming': path}))
elif action == 'cleanup':
    path = Path(value)
    check(path.parent == root / 'incoming')
    check(re.fullmatch(r'[0-9a-f]{40}-[1-9][0-9]{0,14}-[a-z0-9_]{8}', path.name))
    private(path, 0o700, True)
    names = {'compose.staging.yaml', 'image.tar', 'manifest.json', 'release.py', 'SHA256SUMS'}
    children = list(path.iterdir())
    check(all(child.name in names for child in children))
    for child in children:
        info = child.lstat()
        check(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid())
    for child in children:
        child.unlink()
    path.rmdir()
else:
    raise ValueError('operation')
"""


class TransportFailure(Exception):
    """An allowlisted public stage, never an external error message."""


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        raise TransportFailure("arguments")


def require(condition, stage):
    if not condition:
        raise TransportFailure(stage)


def child_environment():
    # Do not pass tokens, private keys, agent sockets, askpass commands, or
    # ambient application/Compose configuration to any child process.
    return {"PATH": os.environ.get("PATH", os.defpath), "LANG": "C", "LC_ALL": "C"}


def external(args, stage, timeout, accepted=(0,)):
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            stdin=subprocess.DEVNULL,
            env=child_environment(),
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        raise TransportFailure(stage) from None
    require(result.returncode in accepted, stage)
    return result


def settings():
    values = {
        name: os.environ.get("SSH_" + name, "")
        for name in ("HOST", "PORT", "USER", "PRIVATE_KEY", "KNOWN_HOSTS")
    }
    host = values["HOST"]
    require(isinstance(host, str) and 1 <= len(host) <= 253, "input")
    if re.fullmatch(r"[0-9.]+", host):
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            raise TransportFailure("input") from None
    else:
        require(
            all(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in host.split(".")
            ),
            "input",
        )
    require(re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", values["USER"]), "input")
    require(re.fullmatch(r"[0-9]{1,5}", values["PORT"]), "input")
    require(1 <= int(values["PORT"]) <= 65535, "input")
    for name in ("PRIVATE_KEY", "KNOWN_HOSTS"):
        require(
            values[name].strip() and "\0" not in values[name] and len(values[name]) <= 1024 * 1024,
            "credential",
        )
    values["PORT"] = str(int(values["PORT"]))
    return values


def private_file(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(value.rstrip() + "\n")


def pinned_identity(directory, values):
    key, hosts, selected = (directory / name for name in ("key", "known_hosts", "pinned_hosts"))
    private_file(key, values["PRIVATE_KEY"])
    private_file(hosts, values["KNOWN_HOSTS"])
    external(["ssh-keygen", "-y", "-P", "", "-f", str(key)], "credential", 15)
    host = values["HOST"]
    lookup = host if values["PORT"] == "22" else "[" + host + "]:" + values["PORT"]
    match = external(["ssh-keygen", "-F", lookup, "-f", str(hosts)], "pin", 15)
    lines = [line for line in match.stdout.splitlines() if line and not line.startswith("#")]
    require(lines, "pin")
    for line in lines:
        parts = line.split()
        require(len(parts) >= 3, "pin")
        # Exact host lists and OpenSSH's hashed exact-host format are allowed.
        # Wildcards, negations, CA trust, and revoked keys are not host pins.
        names = parts[0]
        require(
            (lookup in names.split(",") and not any(c in names for c in "*!?"))
            or re.fullmatch(r"\|1\|[A-Za-z0-9+/=]+\|[A-Za-z0-9+/=]+", names),
            "pin",
        )
    private_file(selected, "\n".join(lines))
    fingerprints = external(
        ["ssh-keygen", "-l", "-E", "sha256", "-f", str(selected)], "pin", 15
    ).stdout.splitlines()
    require(
        len(fingerprints) == len(lines)
        and all(
            re.match(r"^[0-9]+ SHA256:[A-Za-z0-9+/]{43}(?:=)? ", line) for line in fingerprints
        ),
        "pin",
    )
    return key, selected


def ssh_options(key, pins):
    result = ["-F", "/dev/null", "-i", str(key)]
    for value in (
        "BatchMode=yes",
        "StrictHostKeyChecking=yes",
        "IdentitiesOnly=yes",
        "ConnectTimeout=15",
        "ConnectionAttempts=1",
        "IdentityAgent=none",
        "GlobalKnownHostsFile=/dev/null",
        "UserKnownHostsFile=" + str(pins),
        "VerifyHostKeyDNS=no",
        "UpdateHostKeys=no",
        "PasswordAuthentication=no",
        "KbdInteractiveAuthentication=no",
        "PreferredAuthentications=publickey",
        "ClearAllForwardings=yes",
        "ControlMaster=no",
        "ControlPath=none",
    ):
        result.extend(("-o", value))
    return result


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "deploy")
        result[key] = value
    return result


def remote_json(output, stage):
    try:
        require(len(output) <= 4096, stage)
        result = json.loads(output, object_pairs_hook=unique_object)
    except (ValueError, TransportFailure):
        raise TransportFailure(stage) from None
    require(isinstance(result, dict), stage)
    return result


def deployment_status(result):
    report = remote_json(result.stdout, "deploy")
    require(set(report) in ({"status", "rollback"}, {"status", "rollback", "failure"}), "deploy")
    require(report.get("status") in ("passed", "failed"), "deploy")
    require(report.get("rollback") in ("not-needed", "passed", "failed"), "deploy")
    if report["status"] == "passed":
        require(
            result.returncode == 0
            and report["rollback"] == "not-needed"
            and "failure" not in report,
            "deploy",
        )
        return
    require(report.get("failure") in ("preflight", "candidate", "candidate-cleanup"), "deploy")
    raise TransportFailure("rollback" if report["rollback"] == "failed" else "deploy")


def transport(bundle, source, run):
    try:
        release.verify_bundle(bundle, source, run)
    except Exception:
        raise TransportFailure("bundle") from None
    values = settings()
    with tempfile.TemporaryDirectory(prefix="subway-staging-ssh-") as temporary:
        Path(temporary).chmod(0o700)
        key, pins = pinned_identity(Path(temporary), values)
        options = ssh_options(key, pins)
        target = values["USER"] + "@" + values["HOST"]
        ssh = ["ssh", *options, "-T", "-p", values["PORT"], "--", target]

        def directory_command(action, value):
            return shlex.join(["python3", "-I", "-c", REMOTE_DIRECTORY, action, REMOTE_ROOT, value])

        prepared = external(
            [*ssh, directory_command("prepare", source + "-" + str(run))], "prepare", 60
        )
        payload = remote_json(prepared.stdout, "prepare")
        incoming = payload.get("incoming")
        require(
            set(payload) == {"incoming"}
            and isinstance(incoming, str)
            and re.fullmatch(
                re.escape(REMOTE_ROOT + "/incoming/" + source + "-" + str(run) + "-")
                + r"[a-z0-9_]{8}",
                incoming,
            ),
            "prepare",
        )
        failure = None
        try:
            external(
                [
                    "scp",
                    *options,
                    "-P",
                    values["PORT"],
                    "--",
                    *(str(Path(bundle).resolve() / name) for name in FILES),
                    target + ":" + incoming + "/",
                ],
                "transfer",
                300,
            )
            command = (
                "cd "
                + shlex.quote(REMOTE_ROOT)
                + " && "
                + shlex.join(
                    [
                        "env",
                        "DOCKER_CONTEXT=default",
                        "DOCKER_HOST=unix:///var/run/docker.sock",
                        "python3",
                        "-I",
                        incoming + "/release.py",
                        "hostdeploy",
                        "--bundle",
                        incoming,
                        "--source-sha",
                        source,
                        "--run-id",
                        str(run),
                    ]
                )
            )
            result = external([*ssh, command], "deploy", 900, accepted=(0, 1))
            deployment_status(result)
        except TransportFailure as error:
            failure = error
        finally:
            try:
                external([*ssh, directory_command("cleanup", incoming)], "cleanup", 60)
            except TransportFailure:
                stage = {
                    "transfer": "transfer-cleanup",
                    "deploy": "deploy-cleanup",
                    "rollback": "rollback-cleanup",
                }.get(str(failure), "cleanup")
                failure = TransportFailure(stage)
        if failure is not None:
            raise failure


def report_destination(path):
    require(not path.is_symlink(), "report")
    if path.exists():
        require(stat.S_ISREG(path.lstat().st_mode), "report")
    for parent in path.absolute().parents:
        require(not parent.is_symlink() and (not parent.exists() or parent.is_dir()), "report")


def main(argv=None):
    parser = PrivateParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--report", type=Path)
    report = {"status": "failed", "stage": "arguments"}
    args = None
    try:
        args = parser.parse_args(argv)
        require(
            re.fullmatch(r"[0-9a-f]{40}", args.source_sha)
            and re.fullmatch(r"[1-9][0-9]{0,14}", args.run_id),
            "input",
        )
        run = int(args.run_id)
        report.update(sourceSHA=args.source_sha, runID=run)
        if args.report is not None:
            report_destination(args.report)
        transport(args.bundle, args.source_sha, run)
        report.update(status="passed", stage="complete")
    except TransportFailure as error:
        report["stage"] = str(error)
    except Exception:
        # File errors and temporary-directory cleanup can also contain secrets.
        report["stage"] = "local"
    if args is not None and args.report is not None:
        try:
            report_destination(args.report)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            release.private_write(args.report, json.dumps(report, sort_keys=True, indent=2) + "\n")
        except Exception:
            report.update(status="failed", stage="report")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
