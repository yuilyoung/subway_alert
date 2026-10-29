#!/usr/bin/env python3
"""Verify immutable SAMPLE-only staging bundles and replace one backend safely.

Host commands use the current directory, an owner-only precreated .env, and a
filesystem lock. All engine and HTTP output stays private; only fixed stage
names and public source/run/image identities may reach the CLI report.
"""

import argparse
import contextlib
import fcntl
import hashlib
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import stat
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path, PurePosixPath

PAYLOAD = ("compose.staging.yaml", "image.tar", "release.py")
BUNDLE_FILES = {*PAYLOAD, "manifest.json", "SHA256SUMS"}
HERE = Path(__file__).resolve().parent
IMAGE_PATTERN = r"sha256:[0-9a-f]{64}"
RELEASE_PATTERN = r"[1-9][0-9]*-[0-9a-f]{40}"
INSPECT_FORMAT = (
    "{{ $sample := false }}{{ $fcm := false }}{{ $memory := false }}"
    "{{ range .Config.Env }}"
    '{{ if eq . "SEOUL_SUBWAY_KEY=sample" }}{{ $sample = true }}{{ end }}'
    '{{ if eq . "FCM_ENABLED=false" }}{{ $fcm = true }}{{ end }}'
    '{{ if eq . "MONITOR_STORE=memory" }}{{ $memory = true }}{{ end }}'
    "{{ end }}"
    '{"image":{{json .Image}},"running":{{json .State.Running}},'
    '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}""{{end}},'
    '"healthcheck":{{if .Config.Healthcheck}}'
    '{{if .Config.Healthcheck.Test}}{{if eq (index .Config.Healthcheck.Test 0) "NONE"}}false'
    "{{else}}true{{end}}{{else}}false{{end}}{{else}}false{{end}},"
    '"readonly":{{json .HostConfig.ReadonlyRootfs}},'
    '"cap_drop":{{json .HostConfig.CapDrop}},'
    '"security_opt":{{json .HostConfig.SecurityOpt}},'
    '"tmpfs":{{json .HostConfig.Tmpfs}},"ports":{{json .NetworkSettings.Ports}},'
    '"sample":{{$sample}},"fcm_disabled":{{$fcm}},"memory":{{$memory}}}'
)


class ReleaseFailure(Exception):
    """A fixed public stage, never raw subprocess or HTTP error text."""


def require(condition, stage):
    if not condition:
        raise ReleaseFailure(stage)


def identities(source, run, image=None):
    require(isinstance(source, str) and re.fullmatch(r"[0-9a-f]{40}", source), "source")
    require(type(run) is int and run > 0, "run")
    if image is not None:
        require(isinstance(image, str) and re.fullmatch(IMAGE_PATTERN, image), "image-identity")


def digest(path):
    with path.open("rb") as stream:
        checksum = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
        return checksum.hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "json")
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def regular(path, private=False):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), "file-policy")
    if private:
        require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600, "private-file")


def image_archive(path, image):
    """Docker save's config bytes define its image ID, independent of local tags."""
    with tarfile.open(path, "r:*") as archive:
        names = set()
        for entry in archive.getmembers():
            part = PurePosixPath(entry.name)
            require(
                not part.is_absolute()
                and ".." not in part.parts
                and (entry.isfile() or entry.isdir())
                and entry.name not in names,
                "image-archive",
            )
            names.add(entry.name)
        entry = archive.getmember("manifest.json")
        require(entry.size <= 1024 * 1024, "image-archive")
        manifest = json.load(archive.extractfile(entry), object_pairs_hook=unique_object)
        require(
            isinstance(manifest, list) and len(manifest) == 1 and isinstance(manifest[0], dict),
            "image-archive",
        )
        config_name = manifest[0].get("Config")
        require(isinstance(config_name, str) and config_name in names, "image-archive")
        config = archive.getmember(config_name)
        require(config.isfile() and config.size <= 16 * 1024 * 1024, "image-archive")
        config_hash = hashlib.sha256(archive.extractfile(config).read()).hexdigest()
        require("sha256:" + config_hash == image, "image-identity")
        layers = manifest[0].get("Layers")
        require(
            isinstance(layers, list)
            and all(
                isinstance(name, str) and name in names and archive.getmember(name).isfile()
                for name in layers
            ),
            "image-archive",
        )


def write_metadata(bundle, source, run, image):
    identities(source, run, image)
    manifest = {
        "formatVersion": 1,
        "sourceSHA": source,
        "runID": run,
        "imageID": image,
        "files": {name: digest(bundle / name) for name in PAYLOAD},
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    names = sorted((*PAYLOAD, "manifest.json"))
    (bundle / "SHA256SUMS").write_text(
        "".join(digest(bundle / name) + "  " + name + "\n" for name in names), encoding="utf-8"
    )


def verify_bundle(bundle, source, run, check_tools=True):
    identities(source, run)
    bundle = Path(bundle)
    require(bundle.is_dir() and not bundle.is_symlink(), "bundle")
    require({p.name for p in bundle.iterdir()} == BUNDLE_FILES, "bundle-files")
    for name in BUNDLE_FILES:
        regular(bundle / name)
    manifest = read_json(bundle / "manifest.json")
    require(
        isinstance(manifest, dict)
        and set(manifest) == {"formatVersion", "sourceSHA", "runID", "imageID", "files"},
        "manifest",
    )
    require(type(manifest["formatVersion"]) is int and manifest["formatVersion"] == 1, "manifest")
    identities(manifest["sourceSHA"], manifest["runID"], manifest["imageID"])
    require(manifest["sourceSHA"] == source and manifest["runID"] == run, "source-run")
    require(
        isinstance(manifest["files"], dict) and set(manifest["files"]) == set(PAYLOAD),
        "manifest-files",
    )
    for name in PAYLOAD:
        require(manifest["files"][name] == digest(bundle / name), "checksum")
    expected = "".join(
        digest(bundle / name) + "  " + name + "\n" for name in sorted((*PAYLOAD, "manifest.json"))
    )
    require((bundle / "SHA256SUMS").read_text(encoding="utf-8") == expected, "checksum")
    if check_tools:
        for name in ("release.py", "compose.staging.yaml"):
            require(digest(bundle / name) == digest(HERE / name), "source-tools")
    image_archive(bundle / "image.tar", manifest["imageID"])
    return manifest


def engine_environment():
    # Do not allow ambient Compose, Spring, JVM or application configuration.
    allowed = (
        "PATH",
        "HOME",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "XDG_RUNTIME_DIR",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    )
    return {key: os.environ[key] for key in allowed if key in os.environ}


def command(args, stage, environment=None, timeout=180):
    try:
        result = subprocess.run(
            args,
            env=environment or engine_environment(),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        raise ReleaseFailure(stage) from None
    require(result.returncode == 0, stage)
    return result.stdout.strip()


def build_bundle(output, source, run, image):
    identities(source, run, image)
    output = Path(output)
    require(not output.exists() and not output.is_symlink(), "output-exists")
    require(
        command(["docker", "image", "inspect", "--format", "{{.Id}}", image], "image-inspect")
        == image,
        "image-identity",
    )
    output.mkdir(parents=True, mode=0o700)
    try:
        for name in ("release.py", "compose.staging.yaml"):
            shutil.copyfile(HERE / name, output / name)
        command(
            ["docker", "image", "save", "--output", str(output / "image.tar"), image],
            "image-save",
            timeout=600,
        )
        write_metadata(output, source, run, image)
        verify_bundle(output, source, run)
    except Exception:
        shutil.rmtree(output)
        raise
    return output


def private_write(path, text):
    temporary = path.with_name("." + path.name + "-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_config(path):
    regular(path, private=True)
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        require(
            separator and key in ("BACKEND_PORT", "SUBWAY_API_TOKENS") and key not in values,
            "configuration",
        )
        values[key] = value
    require(set(values) == {"BACKEND_PORT", "SUBWAY_API_TOKENS"}, "configuration")
    require(
        re.fullmatch(r"[1-9][0-9]{0,4}", values["BACKEND_PORT"])
        and int(values["BACKEND_PORT"]) <= 65535,
        "configuration",
    )
    require(re.fullmatch(r"[A-Za-z0-9_-]{32,128}", values["SUBWAY_API_TOKENS"]), "configuration")
    return values


def config_text(values):
    return "".join(key + "=" + values[key] + "\n" for key in ("BACKEND_PORT", "SUBWAY_API_TOKENS"))


@contextlib.contextmanager
def host_lock(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "host-directory")
    info = root.stat()
    require(info.st_uid == os.geteuid() and not info.st_mode & 0o022, "host-directory")
    descriptor = os.open(root / ".deploy.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        regular(root / ".deploy.lock", private=True)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReleaseFailure("deployment-locked") from None
        for name in ("releases", "configs"):
            directory = root / name
            directory.mkdir(mode=0o700, exist_ok=True)
            require(directory.is_dir() and not directory.is_symlink(), "host-directory")
            require(
                directory.stat().st_uid == os.geteuid() and not directory.stat().st_mode & 0o077,
                "host-directory",
            )
        yield
    finally:
        os.close(descriptor)


def state_read(root):
    path = root / "state.json"
    if not path.exists() and not path.is_symlink():
        # Existing containers/config snapshots without a state need operator recovery.
        require(
            not any((root / "releases").iterdir()) and not any((root / "configs").iterdir()),
            "state-missing",
        )
        return None
    regular(path, private=True)
    state = read_json(path)
    require(isinstance(state, dict) and set(state) == {"current", "previous"}, "state")
    for key in ("current", "previous"):
        require(
            (key == "previous" and state[key] is None)
            or (isinstance(state[key], str) and re.fullmatch(RELEASE_PATTERN, state[key])),
            "state",
        )
    require(state["current"] != state["previous"], "state")
    for identity in (state["current"], state["previous"]):
        if identity is not None:
            saved_release(root, identity)
    return state


def state_write(root, current, previous):
    private_write(
        root / "state.json", json.dumps({"current": current, "previous": previous}) + "\n"
    )


def saved_release(root, identity):
    require(isinstance(identity, str) and re.fullmatch(RELEASE_PATTERN, identity), "state")
    run, source = identity.split("-", 1)
    bundle = root / "releases" / identity
    manifest = verify_bundle(bundle, source, int(run), check_tools=False)
    values = read_config(root / "configs" / (identity + ".env"))
    return bundle, manifest, values


def compose_command(root, bundle, manifest, values):
    project = "subway-staging-" + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    environment = engine_environment()
    environment.update(values, SUBWAY_IMAGE=manifest["imageID"])
    args = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--project-directory",
        str(bundle),
        "--env-file",
        str(root / "configs" / (str(manifest["runID"]) + "-" + manifest["sourceSHA"] + ".env")),
        "-f",
        str(bundle / "compose.staging.yaml"),
    ]
    return args, environment


def load_image(bundle, manifest):
    command(["docker", "load", "--input", str(bundle / "image.tar")], "image-load", timeout=600)
    identity = manifest["imageID"]
    require(
        command(["docker", "image", "inspect", "--format", "{{.Id}}", identity], "image-inspect")
        == identity,
        "image-identity",
    )


def stop(root, saved):
    args, environment = compose_command(root, *saved)
    command(args + ["down", "--remove-orphans", "--timeout", "20"], "stop", environment)


def start(root, saved):
    args, environment = compose_command(root, *saved)
    command(
        args
        + [
            "up",
            "--no-build",
            "--pull",
            "never",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "120",
            "backend",
        ],
        "start",
        environment,
    )
    check_ready(root, saved)


def http_request(port, path, token=None, session_token=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if session_token is not None:
        headers["X-Session-Token"] = session_token
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read(1024 * 1024)
    finally:
        connection.close()


def check_ready(root, saved):
    args, environment = compose_command(root, *saved)
    _, manifest, values = saved
    container = command(args + ["ps", "-q", "backend"], "container", environment)
    require(re.fullmatch(r"[0-9a-f]{12,64}", container), "container")
    details = json.loads(
        command(
            ["docker", "inspect", "--format", INSPECT_FORMAT, container], "runtime", environment
        ),
        object_pairs_hook=unique_object,
    )
    uid = command(["docker", "exec", container, "id", "-u"], "runtime", environment)
    require(
        uid == "10001"
        and details.get("image") == manifest["imageID"]
        and details.get("running") is True
        and details.get("health") == "healthy"
        and details.get("healthcheck") is True
        and details.get("readonly") is True
        and "ALL" in (details.get("cap_drop") or [])
        and any(
            value in ("no-new-privileges", "no-new-privileges:true")
            for value in (details.get("security_opt") or [])
        )
        and "/tmp" in (details.get("tmpfs") or {})
        and details.get("ports")
        == {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": values["BACKEND_PORT"]}]}
        and all(details.get(key) is True for key in ("sample", "fcm_disabled", "memory")),
        "runtime",
    )
    port, token = int(values["BACKEND_PORT"]), values["SUBWAY_API_TOKENS"]
    require(http_request(port, "/api/health")[0] == 200, "health")
    require(http_request(port, "/api/lines")[0] == 401, "authentication")
    require(http_request(port, "/api/lines", token)[0] == 200, "authorization")
    path = "/api/monitor-sessions/" + str(uuid.uuid4())
    status, headers, body = http_request(port, path, token, secrets.token_urlsafe(32))
    content_type = {key.lower(): value for key, value in headers.items()}.get("content-type", "")
    require(status == 404 and content_type.split(";", 1)[0] == "application/json", "monitor-store")
    payload = json.loads(body)
    # The service checks storage before unknown-ID lookup. A JSON Spring 404
    # proves that route passed authentication and its monitor-store guard.
    require(
        isinstance(payload, dict) and payload.get("status") == 404 and payload.get("path") == path,
        "monitor-store",
    )


def engine_check():
    version = command(["docker", "version", "--format", "{{.Server.Version}}"], "engine")
    major = re.match(r"^(\d+)\.", version)
    require(major and int(major.group(1)) >= 28, "engine")
    command(["docker", "compose", "version", "--short"], "compose")


def restore(root, saved):
    """A failed down may already have removed its container; inspect then recover.

    Requiring a successful cleanup before recreation avoids overlapping singleton
    backends when a failed engine command left the previous container running.
    """
    try:
        check_ready(root, saved)
        return
    except Exception:
        pass
    stop(root, saved)
    load_image(saved[0], saved[1])
    start(root, saved)


def deploy_bundle(root, bundle, source, run):
    report = {"status": "failed", "rollback": "not-needed", "failure": "preflight"}
    try:
        root = Path(root).resolve()
        manifest = verify_bundle(bundle, source, run)
        with host_lock(root):
            values = read_config(root / ".env")
            state = state_read(root)
            old = saved_release(root, state["current"]) if state else None
            engine_check()
            identity = str(run) + "-" + source
            destination = root / "releases" / identity
            if destination.exists():
                require(state and state["current"] == identity, "release-exists")
                require(read_json(destination / "manifest.json") == manifest, "release-exists")
                check_ready(root, old)
                return {"status": "passed", "rollback": "not-needed"}
            load_image(Path(bundle), manifest)
            configuration = root / "configs" / (identity + ".env")
            try:
                shutil.copytree(bundle, destination)
                private_write(configuration, config_text(values))
                candidate = saved_release(root, identity)
            except Exception:
                # Preparation has no service side effects. Remove partial copies
                # and snapshots so a first-deployment retry is not stranded by
                # state-missing or release-exists validation.
                if destination.exists():
                    shutil.rmtree(destination)
                configuration.unlink(missing_ok=True)
                raise
            attempted = False
            try:
                if old:
                    stop(root, old)
                attempted = True
                start(root, candidate)
                state_write(root, identity, state["current"] if state else None)
                return {"status": "passed", "rollback": "not-needed"}
            except Exception:
                report["failure"] = "candidate"
                cleaned = True
                if attempted:
                    try:
                        stop(root, candidate)
                    except Exception:
                        cleaned = False
                        report["failure"] = "candidate-cleanup"
                if old:
                    report["rollback"] = "failed"
                    if cleaned:
                        try:
                            restore(root, old)
                            report["rollback"] = "passed"
                        except Exception:
                            pass
                if cleaned:
                    shutil.rmtree(destination)
                    (root / "configs" / (identity + ".env")).unlink()
    except Exception:
        # Intentionally do not serialize exception text: external tools, filenames
        # and HTTP payloads can contain server-side credentials.
        pass
    return report


def rollback(root):
    report = {"status": "failed", "rollback": "failed"}
    try:
        root = Path(root).resolve()
        with host_lock(root):
            state = state_read(root)
            require(state and state["previous"] is not None, "no-previous-release")
            current = saved_release(root, state["current"])
            previous = saved_release(root, state["previous"])
            engine_check()
            load_image(previous[0], previous[1])
            try:
                stop(root, current)
                start(root, previous)
                state_write(root, state["previous"], state["current"])
                return {"status": "passed", "rollback": "passed"}
            except Exception:
                restore(root, current)
                report["rollback"] = "restored-current"
    except Exception:
        pass
    return report


def smoke_bundle(bundle, source, run):
    """Real Docker readiness and automatic rollback, isolated from host staging."""
    manifest = verify_bundle(bundle, source, run)
    report = {"status": "failed", "rollback": "not-tested", "cleanup": "not-needed"}
    with tempfile.TemporaryDirectory(prefix="subway-release-smoke-") as directory:
        root = Path(directory) / "host"
        root.mkdir(mode=0o700)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        values = {"BACKEND_PORT": str(port), "SUBWAY_API_TOKENS": secrets.token_urlsafe(32)}
        private_write(root / ".env", config_text(values))
        try:
            require(deploy_bundle(root, bundle, source, run)["status"] == "passed", "smoke-first")
            candidate = Path(directory) / "candidate"
            shutil.copytree(bundle, candidate)
            write_metadata(candidate, source, run + 1, manifest["imageID"])
            # Holding a second local port produces an actual engine startup failure.
            # The previous service must be stopped first, then restored on its saved port.
            with socket.socket() as conflict:
                conflict.bind(("127.0.0.1", 0))
                conflict.listen(1)
                values["BACKEND_PORT"] = str(conflict.getsockname()[1])
                private_write(root / ".env", config_text(values))
                failed = deploy_bundle(root, candidate, source, run + 1)
            require(
                failed["status"] == "failed" and failed["rollback"] == "passed", "smoke-rollback"
            )
            state = state_read(root)
            require(state["current"] == str(run) + "-" + source, "smoke-state")
            check_ready(root, saved_release(root, state["current"]))
            report.update(status="passed", rollback="passed", imageID=manifest["imageID"])
        finally:
            try:
                # Both candidates use one directory-derived project. A startup
                # failure is cleaned even when no current state was written.
                releases = (
                    list((root / "releases").iterdir()) if (root / "releases").exists() else []
                )
                for path in releases:
                    stop(root, saved_release(root, path.name))
                report["cleanup"] = "passed"
            except Exception:
                report.update(status="failed", cleanup="failed")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    for name in ("bundle", "verify", "hostdeploy", "smoke"):
        sub = subcommands.add_parser(name)
        sub.add_argument("--source-sha", required=True)
        sub.add_argument("--run-id", type=int, required=True)
        sub.add_argument("--output" if name == "bundle" else "--bundle", type=Path, required=True)
        if name == "bundle":
            sub.add_argument("--image", required=True)
        sub.add_argument("--report", type=Path)
    subcommands.add_parser("rollback").add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = {"status": "failed", "failure": args.action}
    try:
        if args.action == "bundle":
            build_bundle(args.output, args.source_sha, args.run_id, args.image)
            report = {"status": "passed", "imageID": args.image}
        elif args.action == "verify":
            manifest = verify_bundle(args.bundle, args.source_sha, args.run_id)
            report = {
                "status": "passed",
                "sourceSHA": manifest["sourceSHA"],
                "runID": manifest["runID"],
                "imageID": manifest["imageID"],
            }
        elif args.action == "hostdeploy":
            report = deploy_bundle(Path.cwd(), args.bundle, args.source_sha, args.run_id)
        elif args.action == "rollback":
            report = rollback(Path.cwd())
        else:
            report = smoke_bundle(args.bundle, args.source_sha, args.run_id)
    except Exception:
        pass
    if args.report:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
        except OSError:
            report = {"status": "failed", "failure": "report"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
