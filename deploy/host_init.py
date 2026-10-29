#!/usr/bin/env python3
"""Create or validate a private POSIX staging root without printing credentials.

Only entries created by this invocation are eligible for failure cleanup. Existing
configuration, permissions, release history and operator files are never repaired.
Docker validation is optional and runs before any filesystem mutation.
"""

import argparse
import contextlib
import json
import os
import re
import secrets
import stat
from pathlib import Path

import release

DIRECTORIES = ("incoming", "configs", "releases")


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's usual error includes untrusted argument values.
        raise release.ReleaseFailure("arguments")


def private_directory(path):
    info = path.lstat()
    release.require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700,
        "host-directory",
    )


def private_config(path):
    release.require(path.lstat().st_nlink == 1, "private-file")
    return release.read_config(path)


def exists(path):
    # A dangling link is an existing entry, too.
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def host_path(root):
    root = Path(root)
    release.require(".." not in root.parts, "host-directory")
    root = root.absolute()
    # Reject links in every existing component; resolving first would hide them.
    for parent in reversed(root.parents):
        release.require(stat.S_ISDIR(parent.lstat().st_mode), "host-directory")
    return root


def remember(path, created):
    info = path.lstat()
    created.append((path, info.st_dev, info.st_ino, stat.S_ISDIR(info.st_mode)))


def create_directory(path, created):
    path.mkdir(mode=0o700)
    remember(path, created)
    # umask may remove owner bits. Only a newly created entry is ever chmodded.
    os.chmod(path, 0o700, follow_symlinks=False)
    private_directory(path)


def create_config(path, port, token, created):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        remember(path, created)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"BACKEND_PORT={port}\nSUBWAY_API_TOKENS={token}\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        # fdopen normally owns the descriptor, including when writing fails.
        try:
            os.close(descriptor)
        except OSError:
            pass


def cleanup(created):
    for path, device, inode, directory in reversed(created):
        try:
            info = path.lstat()
            if (info.st_dev, info.st_ino) == (device, inode):
                # rmdir never recursively removes data another process added.
                path.rmdir() if directory else path.unlink()
        except OSError:
            pass


@contextlib.contextmanager
def local_engine_environment():
    previous = dict(os.environ)
    try:
        # Match SSH staging: operator contexts and TLS settings must not redirect
        # this read-only validation to a production or rootless daemon.
        for name in ("DOCKER_CONFIG", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
            os.environ.pop(name, None)
        os.environ.update(DOCKER_HOST="unix:///var/run/docker.sock", DOCKER_CONTEXT="default")
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def prepare(action, root, port="8080", check_engine=False):
    release.require(
        isinstance(port, str) and re.fullmatch(r"[1-9][0-9]{0,4}", port) and int(port) <= 65535,
        "port",
    )
    root = host_path(root)
    missing = []
    if exists(root):
        private_directory(root)
    else:
        release.require(action == "init", "host-directory")
        missing.append(root)
    # Validate every preexisting entry before creating anything.
    for name in DIRECTORIES:
        path = root / name
        if exists(path):
            private_directory(path)
        else:
            missing.append(path)
    config = root / ".env"
    need_config = not exists(config)
    if not need_config:
        values = private_config(config)
        release.require(values["BACKEND_PORT"] == port, "port")
    release.require(action == "init" or (not missing and not need_config), "host-incomplete")
    if check_engine:
        with local_engine_environment():
            release.engine_check()
    token = None
    if need_config:
        token = secrets.token_urlsafe(32)
        release.require(
            isinstance(token, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", token), "token"
        )
    created = []
    try:
        for path in missing:
            create_directory(path, created)
        if need_config:
            create_config(config, port, token, created)
        private_config(config)
    except Exception:
        cleanup(created)
        raise


def main(argv=None):
    report = {"status": "failed", "failure": "host-initialization"}
    try:
        parser = PrivateParser(description=__doc__)
        parser.add_argument("action", choices=("init", "check"))
        parser.add_argument("--root", type=Path, required=True)
        parser.add_argument("--port", default="8080")
        parser.add_argument("--check-engine", action="store_true")
        args = parser.parse_args(argv)
        prepare(args.action, args.root, args.port, args.check_engine)
        report = {"status": "passed", "action": args.action}
    except Exception:
        # Do not serialize filenames, environment contents, or external errors.
        pass
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
