#!/usr/bin/env python3
"""Verify the packaged server's private API gate on loopback, without external API calls."""

import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time


def request(port, path, token=None, method='GET', body=None, duplicate=False):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if duplicate:
            connection.putrequest(method, path)
            connection.putheader('Authorization', 'Bearer ' + token)
            connection.putheader('Authorization', 'Bearer ' + token)
            connection.endheaders()
        else:
            connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        return response.status, dict(response.getheaders()), payload
    finally:
        connection.close()


@contextmanager
def server(jar, token):
    with socket.socket() as port_socket:
        port_socket.bind(('127.0.0.1', 0))
        port = port_socket.getsockname()[1]
    environment = dict(os.environ, SERVER_ADDRESS='127.0.0.1', PORT=str(port),
                       SUBWAY_API_TOKENS=token, FCM_ENABLED='false', SEOUL_SUBWAY_KEY='sample')
    # Capture logs without echoing environment or credential material on failures.
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(['java', '-jar', str(jar)], env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError('Packaged server exited before health was available')
                try:
                    if request(port, '/api/health')[0] == 200:
                        break
                except (OSError, http.client.HTTPException):
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError('Packaged server health timed out')
            yield port
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log.seek(0)
            if token and token.encode() in log.read():
                raise AssertionError('Server log exposed API credential material')


def require(condition, message):
    # Smoke checks must remain active even when Python runs with -O.
    if not condition:
        raise AssertionError(message)


def check_unconfigured(port):
    """Check public health and fail-closed access without making provider calls."""
    require(request(port, '/api/health')[0] == 200, 'public health must remain available')
    require(request(port, '/api/lines')[0] == 503, 'unconfigured private API must fail closed')


def check_keyed(port, token):
    """Check authentication and quotas using local metadata and invalid demo input."""
    require(request(port, '/api/health')[0] == 200, 'public health must remain available')
    require(request(port, '/api/lines')[0] == 401, 'missing key must be rejected')
    require(request(port, '/api/lines', secrets.token_urlsafe(32))[0] == 401, 'wrong key must be rejected')
    require(request(port, '/api/lines', token, duplicate=True)[0] == 401, 'duplicate key header must be rejected')
    status, _, payload = request(port, '/api/lines', token)
    require(status == 200 and isinstance(json.loads(payload), list), 'valid key must reach API')
    for _ in range(3):
        require(request(port, '/api/track', token, 'POST', '{}')[0] == 400, 'invalid demo body must be rejected')
    status, headers, _ = request(port, '/api/track', token, 'POST', '{}')
    require(status == 429 and int(headers.get('Retry-After', '0')) > 0, 'creation budget must reject with retry hint')
    with ThreadPoolExecutor(max_workers=12) as workers:
        responses = list(workers.map(lambda _: request(port, '/api/lines', token), range(90)))
    require(any(value[0] == 200 for value in responses), 'normal requests must still succeed')
    require(any(value[0] == 429 for value in responses), 'burst must reach key budget')
    require(all(value[0] in (200, 429) for value in responses), 'unexpected burst response')
    require(all(token.encode() not in value[2] for value in responses), 'API response must not expose key')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jar', type=Path, required=True)
    args = parser.parse_args()
    if not args.jar.is_file():
        parser.error('server JAR is missing; run Maven verify first')
    with server(args.jar, '') as port:
        check_unconfigured(port)
    token = secrets.token_urlsafe(32)
    with server(args.jar, token) as port:
        check_keyed(port, token)
    print('Packaged API smoke: health 200, unconfigured 503, missing/wrong/duplicate key 401, valid key 200, creation/burst 429; no external API calls')


if __name__ == '__main__':
    main()
