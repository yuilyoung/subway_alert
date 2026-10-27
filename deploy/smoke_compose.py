#!/usr/bin/env python3
"""Build and check the real Compose backend in a disposable, isolated project."""

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import tempfile
import time
import uuid

from smoke_api_access import check_keyed, check_unconfigured, request


ROOT = Path(__file__).resolve().parents[1]
# Select policy facts, never the full inspect, environment, command, or health logs.
# Convert the two safe-mode environment settings to booleans inside Docker.
INSPECT_FORMAT = (
    '{{ $sample := false }}{{ $fcm := false }}'
    '{{ range .Config.Env }}'
    '{{ if eq . "SEOUL_SUBWAY_KEY=sample" }}{{ $sample = true }}{{ end }}'
    '{{ if eq . "FCM_ENABLED=false" }}{{ $fcm = true }}{{ end }}'
    '{{ end }}'
    '{"running":{{json .State.Running}},'
    '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}""{{end}},'
    '"healthcheck":{{if .Config.Healthcheck}}'
    '{{if .Config.Healthcheck.Test}}{{if eq (index .Config.Healthcheck.Test 0) "NONE"}}false'
    '{{else}}true{{end}}{{else}}false{{end}}{{else}}false{{end}},'
    '"readonly":{{json .HostConfig.ReadonlyRootfs}},'
    '"cap_drop":{{json .HostConfig.CapDrop}},'
    '"security_opt":{{json .HostConfig.SecurityOpt}},'
    '"tmpfs":{{json .HostConfig.Tmpfs}},'
    '"ports":{{json .NetworkSettings.Ports}},'
    '"sample":{{$sample}},"fcm_disabled":{{$fcm}}}'
)


class SmokeFailure(Exception):
    """Only a fixed, credential-free stage name may cross the CLI boundary."""


def validate_runtime(details, uid, port):
    """Reject unsafe or unhealthy facts read from the running container."""
    expected_ports = {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]}
    if not (
        uid.strip() == '10001'
        and details.get('running') is True
        and details.get('health') == 'healthy'
        and details.get('healthcheck') is True
        and details.get('readonly') is True
        and 'ALL' in (details.get('cap_drop') or [])
        and any(option in ('no-new-privileges', 'no-new-privileges:true')
                for option in (details.get('security_opt') or []))
        and '/tmp' in (details.get('tmpfs') or {})
        and details.get('ports') == expected_ports
        and details.get('sample') is True
        and details.get('fcm_disabled') is True
    ):
        raise SmokeFailure('runtime-policy')


def command(arguments, environment, stage, timeout=150, allowed=(0,)):
    """Capture all engine output privately, including failed builds and cleanup."""
    try:
        result = subprocess.run(arguments, env=environment, capture_output=True,
                                text=True, check=False, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise SmokeFailure(stage) from None
    if result.returncode not in allowed:
        raise SmokeFailure(stage)
    return result


def check_container(compose, environment, port, stage):
    container = command(compose + ['ps', '-q', 'backend'], environment, stage).stdout.strip()
    if not re.fullmatch(r'[0-9a-f]{12,64}', container):
        raise SmokeFailure(stage)
    details = json.loads(command(
        ['docker', 'inspect', '--format', INSPECT_FORMAT, container], environment, stage
    ).stdout)
    uid = command(['docker', 'exec', container, 'id', '-u'], environment, stage).stdout
    validate_runtime(details, uid, port)
    return container


def wait_after_restart(container, environment):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        details = json.loads(command(
            ['docker', 'inspect', '--format', INSPECT_FORMAT, container],
            environment, 'restart-health'
        ).stdout)
        if details.get('running') is not True or details.get('health') == 'unhealthy':
            raise SmokeFailure('restart-health')
        if details.get('health') == 'healthy':
            return
        time.sleep(0.5)
    raise SmokeFailure('restart-health')


def run_smoke():
    report = {'status': 'failed', 'checks': [], 'failures': [],
              'cleanup': {'status': 'not-needed'}}
    stage = 'engine'
    try:
        # Explicit interpolation values beat ambient shell variables; disable all
        # ambient COMPOSE_* selection so only the given files/project participate.
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith('COMPOSE_')}
        environment.update(SUBWAY_API_TOKENS='', BACKEND_PORT='')
        version = command(['docker', 'version', '--format', '{{.Server.Version}}'],
                          environment, stage).stdout.strip()
        major = re.match(r'^(\d+)\.', version)
        if not major or int(major.group(1)) < 28:
            raise SmokeFailure(stage)
        stage = 'compose'
        command(['docker', 'compose', 'version', '--short'], environment, stage)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        environment['BACKEND_PORT'] = str(port)
        unique = uuid.uuid4().hex
        image = 'subway-alert-smoke:' + unique
        project = 'subway-smoke-' + unique
        with tempfile.TemporaryDirectory(prefix='subway-smoke-') as directory:
            env_file = Path(directory) / '.env'
            override = Path(directory) / 'override.json'
            override.write_text(json.dumps({'services': {'backend': {'image': image}}}),
                                encoding='utf-8')
            compose = ['docker', 'compose', '--project-name', project,
                       '--project-directory', str(ROOT), '--env-file', str(env_file),
                       '-f', str(ROOT / 'compose.yaml'), '-f', str(override)]

            def configure(token):
                environment['SUBWAY_API_TOKENS'] = token
                env_file.write_text('BACKEND_PORT=' + str(port) + '\nSUBWAY_API_TOKENS='
                                    + token + '\n', encoding='utf-8')
                env_file.chmod(0o600)

            configure('')
            built = False
            try:
                stage = 'build'
                command(compose + ['build', 'backend'], environment, stage, timeout=900)
                built = True
                report['checks'].append(stage)
                stage = 'unconfigured-start'
                command(compose + ['up', '--wait', '--wait-timeout', '120', 'backend'],
                        environment, stage)
                stage = 'unconfigured-runtime'
                check_container(compose, environment, port, stage)
                report['checks'].append(stage)
                stage = 'unconfigured-http'
                check_unconfigured(port)
                report['checks'].append(stage)
                token = secrets.token_urlsafe(32)
                configure(token)
                stage = 'keyed-start'
                command(compose + ['up', '--force-recreate', '--wait', '--wait-timeout',
                                   '120', 'backend'], environment, stage)
                stage = 'keyed-runtime'
                container = check_container(compose, environment, port, stage)
                report['checks'].append(stage)
                stage = 'keyed-http'
                check_keyed(port, token)
                report['checks'].append(stage)
                stage = 'restart'
                command(compose + ['restart', 'backend'], environment, stage)
                wait_after_restart(container, environment)
                stage = 'restart-runtime'
                check_container(compose, environment, port, stage)
                report['checks'].append(stage)
                stage = 'restart-http'
                if request(port, '/api/health')[0] != 200 or request(
                    port, '/api/lines', token
                )[0] != 200:
                    raise SmokeFailure(stage)
                report['checks'].append(stage)
                report['status'] = 'passed'
            finally:
                # Always target only our random project, including partial builds.
                cleanup = {'status': 'passed', 'project': 'passed', 'image': 'not-created'}
                try:
                    command(compose + ['down', '--volumes', '--remove-orphans', '--timeout',
                                       '20'], environment, 'cleanup-project', timeout=60)
                except SmokeFailure:
                    cleanup.update(status='failed', project='failed')
                    report['failures'].append('cleanup-project')
                try:
                    exists = built or command(
                        ['docker', 'image', 'ls', '--quiet', '--filter', 'reference=' + image],
                        environment, 'cleanup-image-query'
                    ).stdout.strip() != ''
                    if exists:
                        command(['docker', 'image', 'rm', image], environment, 'cleanup-image',
                                timeout=60)
                        cleanup['image'] = 'passed'
                except SmokeFailure:
                    cleanup.update(status='failed', image='failed')
                    report['failures'].append('cleanup-image')
                report['cleanup'] = cleanup
                if cleanup['status'] == 'failed':
                    report['status'] = 'failed'
    except Exception:
        # HTTP assertions, malformed engine output, timeout and all other errors
        # are reduced to the current stage; exception text may contain secrets.
        report['status'] = 'failed'
        report['failures'].append(stage)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_smoke()
    try:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    except OSError:
        print('Compose smoke failed: report')
        return 1
    if report['status'] == 'passed':
        print('Compose smoke passed')
        return 0
    print('Compose smoke failed: ' + ', '.join(report['failures']))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
