#!/usr/bin/env python3
"""Verify the packaged server's private API gate on loopback, without external API calls."""

import argparse
import http.client
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path


def request(
    port,
    path,
    token=None,
    method="GET",
    body=None,
    duplicate=False,
    session_token=None,
    idempotency_key=None,
):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if session_token:
            headers["X-Session-Token"] = session_token
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if duplicate:
            connection.putrequest(method, path)
            connection.putheader("Authorization", "Bearer " + token)
            connection.putheader("Authorization", "Bearer " + token)
            connection.endheaders()
        else:
            connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        return response.status, dict(response.getheaders()), payload
    finally:
        connection.close()


def isolated_java_environment():
    """Keep only OS/JDK essentials; ambient app/JVM config can change safety modes."""
    allowed = (
        "PATH",
        "JAVA_HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        "TMP",
        "TEMP",
        "SYSTEMROOT",
        "WINDIR",
    )
    return {name: os.environ[name] for name in allowed if name in os.environ}


@contextmanager
def server(jar, token):
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    environment = isolated_java_environment()
    environment.update(
        SERVER_ADDRESS="127.0.0.1",
        PORT=str(port),
        MONITOR_STORE="memory",
        SUBWAY_API_TOKENS=token,
        FCM_ENABLED="false",
        SEOUL_SUBWAY_KEY="sample",
        MONITOR_POLL_INTERVAL_MS="3600000",
    )
    # Capture logs without echoing environment or credential material on failures.
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(
            ["java", "-jar", str(jar)], env=environment, stdout=log, stderr=subprocess.STDOUT
        )
        try:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError("Packaged server exited before health was available")
                try:
                    if request(port, "/api/health")[0] == 200:
                        break
                except (OSError, http.client.HTTPException):
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Packaged server health timed out")
            yield port
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log.seek(0)
            output = log.read()
            if any(value.encode() in output for value in token.split(",") if value):
                raise AssertionError("Server log exposed API credential material")


def require(condition, message):
    # Smoke checks must remain active even when Python runs with -O.
    if not condition:
        raise AssertionError(message)


def check_unconfigured(port):
    """Check public health and fail-closed access without making provider calls."""
    require(request(port, "/api/health")[0] == 200, "public health must remain available")
    require(request(port, "/api/lines")[0] == 503, "unconfigured private API must fail closed")


def check_keyed(port, token):
    """Check authentication and quotas using local metadata and invalid demo input."""
    require(request(port, "/api/health")[0] == 200, "public health must remain available")
    require(request(port, "/api/lines")[0] == 401, "missing key must be rejected")
    require(
        request(port, "/api/lines", secrets.token_urlsafe(32))[0] == 401,
        "wrong key must be rejected",
    )
    require(
        request(port, "/api/lines", token, duplicate=True)[0] == 401,
        "duplicate key header must be rejected",
    )
    status, _, payload = request(port, "/api/lines", token)
    require(status == 200 and isinstance(json.loads(payload), list), "valid key must reach API")
    for _ in range(3):
        require(
            request(port, "/api/track", token, "POST", "{}")[0] == 400,
            "invalid demo body must be rejected",
        )
    status, headers, _ = request(port, "/api/track", token, "POST", "{}")
    require(
        status == 429 and int(headers.get("Retry-After", "0")) > 0,
        "creation budget must reject with retry hint",
    )
    with ThreadPoolExecutor(max_workers=12) as workers:
        responses = list(workers.map(lambda _: request(port, "/api/lines", token), range(90)))
    require(any(value[0] == 200 for value in responses), "normal requests must still succeed")
    require(any(value[0] == 429 for value in responses), "burst must reach key budget")
    require(all(value[0] in (200, 429) for value in responses), "unexpected burst response")
    require(
        all(token.encode() not in value[2] for value in responses),
        "API response must not expose key",
    )


def check_registration_recovery(port, token):
    """A cancelled intent never starts polling, including a lost response and late replay."""
    identity, secret = str(uuid.uuid4()), secrets.token_hex(32)
    path = "/api/monitor-sessions/" + identity
    status, _, payload = request(port, path, token, "DELETE", session_token=secret)
    require(status == 200, "cancel-before-create must succeed")
    cancelled = json.loads(payload)
    require(cancelled["status"] == "CANCELLED", "cancel-before-create must retain a tombstone")
    expires = cancelled["expiresAt"]
    body = json.dumps(
        {
            "lineId": "2",
            "trainId": "0202",
            "direction": "INNER",
            "previousStation": "선릉",
            "destinationStation": "삼성",
            "fcmToken": "smoke-token-never-sent",
            "mode": "TEST",
        }
    )
    # Read only headers, then discard the response body as a deterministic lost-result boundary.
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(
            "POST",
            "/api/monitor-sessions",
            body=body,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Idempotency-Key": identity,
                "X-Session-Token": secret,
            },
        )
        require(connection.getresponse().status == 200, "late registration must return a result")
    finally:
        connection.close()
    status, _, payload = request(port, path, token, session_token=secret)
    require(
        status == 200 and json.loads(payload)["status"] == "CANCELLED",
        "known client ID must remain queryable without a creation response",
    )
    require(secret.encode() not in payload, "status must not disclose session credentials")
    status, _, payload = request(
        port,
        "/api/monitor-sessions",
        token,
        "POST",
        body,
        session_token=secret,
        idempotency_key=identity,
    )
    replay = json.loads(payload)
    require(
        status == 200
        and replay["id"] == identity
        and replay["sessionToken"] == secret
        and replay["status"] == "CANCELLED"
        and replay["expiresAt"] == expires,
        "replay must preserve cancellation, identity and original expiry",
    )
    status, _, payload = request(
        port,
        "/api/monitor-sessions",
        token,
        "POST",
        body,
        session_token=secrets.token_hex(32),
        idempotency_key=identity,
    )
    require(status == 409, "conflicting registration capability must be rejected")
    require(secret.encode() not in payload, "conflict must not disclose the original credential")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, required=True)
    args = parser.parse_args()
    if not args.jar.is_file():
        parser.error("server JAR is missing; run Maven verify first")
    with server(args.jar, "") as port:
        check_unconfigured(port)
    token, recovery_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with server(args.jar, token + "," + recovery_token) as port:
        check_keyed(port, token)
        check_registration_recovery(port, recovery_token)
    print(
        "Packaged API smoke: health 200, unconfigured 503, missing/wrong/duplicate key 401, valid key 200, creation/burst 429; no external API calls"
    )
    print(
        "Registration recovery smoke: cancel-before-create, discarded response, GET recovery, stable cancelled replay and conflict 409 passed"
    )


if __name__ == "__main__":
    main()
