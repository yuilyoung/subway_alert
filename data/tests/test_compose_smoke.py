"""Policy and boundary fixtures; these are not proof of a Docker engine run."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy'))
import smoke_compose as smoke
import smoke_api_access as api_smoke


def runtime_fixture(port='43127'):
    return {
        'running': True, 'health': 'healthy', 'healthcheck': True,
        'readonly': True, 'cap_drop': ['ALL'],
        'security_opt': ['no-new-privileges:true'],
        'tmpfs': {'/tmp': 'rw,noexec,nosuid,size=128m'},
        'ports': {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': port}]},
        'sample': True, 'fcm_disabled': True,
    }


class RuntimePolicyTests(unittest.TestCase):
    def test_hardened_healthy_container_is_accepted(self):
        smoke.validate_runtime(runtime_fixture(), '10001', 43127)

    def test_root_or_unexpected_uid_is_rejected(self):
        for uid in ('0', '1000', '', '10001\n0'):
            with self.subTest(uid=uid), self.assertRaises(smoke.SmokeFailure):
                smoke.validate_runtime(runtime_fixture(), uid, 43127)

    def test_public_wrong_or_additional_port_is_rejected(self):
        alternatives = [
            {'8080/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '43127'}]},
            {'8080/tcp': [{'HostIp': '::', 'HostPort': '43127'}]},
            {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8080'}]},
            {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '43127'},
                          {'HostIp': '::1', 'HostPort': '43127'}]},
            {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '43127'}],
             '9090/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '43128'}]},
            {},
        ]
        for ports in alternatives:
            with self.subTest(ports=ports), self.assertRaises(smoke.SmokeFailure):
                details = runtime_fixture()
                details['ports'] = ports
                smoke.validate_runtime(details, '10001', 43127)

    def test_missing_hardening_health_or_safe_mode_is_rejected(self):
        # Each mutation independently removes a required deployment protection.
        mutations = [
            ('readonly', False), ('cap_drop', []),
            ('security_opt', []), ('security_opt', ['no-new-privileges:false']),
            ('tmpfs', {}), ('tmpfs', {'/other': 'rw'}),
            ('running', False), ('health', 'starting'), ('health', 'unhealthy'),
            ('healthcheck', False), ('sample', False), ('fcm_disabled', False),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value), self.assertRaises(smoke.SmokeFailure):
                details = runtime_fixture()
                details[field] = value
                smoke.validate_runtime(details, '10001', 43127)


class SharedHttpSmokeTests(unittest.TestCase):
    def test_registration_check_rejects_a_server_without_cancel_before_create(self):
        self.assertTrue(callable(getattr(api_smoke, 'check_registration_recovery', None)),
                        'packaged server must verify the registration recovery contract')
        with patch.object(api_smoke, 'request', return_value=(404, {}, b'{}')):
            with self.assertRaises(AssertionError):
                api_smoke.check_registration_recovery(43127, 'fixture-key')

    def test_unconfigured_check_rejects_accidentally_open_api(self):
        with patch.object(api_smoke, 'request', return_value=(200, {}, b'[]')):
            with self.assertRaises(AssertionError):
                api_smoke.check_unconfigured(43127)

    def test_keyed_check_rejects_accidentally_open_api(self):
        with patch.object(api_smoke, 'request', return_value=(200, {}, b'[]')):
            with self.assertRaises(AssertionError):
                api_smoke.check_keyed(43127, 'fixture-key')


class OptimizedHttpSmokeTests(unittest.TestCase):
    def test_auth_checks_remain_effective_when_python_optimization_is_enabled(self):
        code = """
import sys
sys.path.insert(0, sys.argv[1])
import smoke_api_access as smoke
smoke.request = lambda *args, **kwargs: (200, {}, b'[]')
try:
    smoke.check_unconfigured(43127)
except AssertionError:
    raise SystemExit(0)
raise SystemExit(1)
"""
        result = subprocess.run([sys.executable, '-O', '-c', code, str(ROOT / 'deploy')],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, 'optimized Python bypassed API protection checks')


class DockerBoundary:
    """Replace only the unavailable engine; leave lifecycle/files/report code real."""

    def __init__(self, fail=None, bad_runtime=False, engine_version='28.3.3'):
        self.fail = fail
        self.engine_version = engine_version
        self.bad_runtime = bad_runtime
        self.commands = []
        self.project = None
        self.tag = None
        self.port = None
        self.phases = []
        self.image_exists = False
        self.active = False
        self.builds = 0
        self.restarts = 0
        self.secrets = []
        self.environments = []
        self.private_files = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        environment = kwargs['env']
        self.environments.append(dict(environment))
        self.assert_private_capture(kwargs)
        failure = False
        output = ''
        if command[:3] == ['docker', 'compose', 'version']:
            output = 'Docker Compose version v2.39.4'
        elif command[:2] == ['docker', 'version']:
            if self.fail == 'engine':
                raise FileNotFoundError('ambient-secret must stay private')
            output = self.engine_version
        elif command[:2] == ['docker', 'compose']:
            project = command[command.index('--project-name') + 1]
            if self.project is None:
                self.project = project
            if project != self.project or not project.startswith('subway-smoke-'):
                raise AssertionError('cleanup or operation escaped its isolated project')
            if str(ROOT / 'compose.yaml') not in command:
                raise AssertionError('original deployment configuration was bypassed')
            env_file = Path(command[command.index('--env-file') + 1])
            values = dict(line.split('=', 1) for line in env_file.read_text().splitlines())
            if values['SUBWAY_API_TOKENS'] != environment['SUBWAY_API_TOKENS']:
                raise AssertionError('interpolation environment disagrees with private env file')
            if values['BACKEND_PORT'] != environment['BACKEND_PORT']:
                raise AssertionError('port environment disagrees with private env file')
            if values['SUBWAY_API_TOKENS']:
                self.secrets.append(values['SUBWAY_API_TOKENS'])
            self.port = values['BACKEND_PORT']
            self.private_files.append(env_file)
            last_file_flag = len(command) - 1 - command[::-1].index('-f')
            override_path = Path(command[last_file_flag + 1])
            override = json.loads(override_path.read_text())
            if set(override) != {'services'} or set(override['services']) != {'backend'}:
                raise AssertionError('override changes non-backend configuration')
            if set(override['services']['backend']) != {'image'}:
                raise AssertionError('override changes runtime policy')
            self.tag = override['services']['backend']['image']
            if not self.tag.startswith('subway-alert-smoke:'):
                raise AssertionError('default image tag would be mutated')
            if 'build' in command:
                self.builds += 1
                failure = self.fail in ('build', 'build-query')
                self.image_exists = not failure or self.fail == 'build-query'
            elif 'up' in command:
                if '--wait' not in command or '--wait-timeout' not in command:
                    raise AssertionError('startup did not require Docker health')
                self.active = True
                self.phases.append(bool(values['SUBWAY_API_TOKENS']))
                if self.phases[-1] and '--force-recreate' not in command:
                    raise AssertionError('new credential was not applied by recreation')
            elif 'ps' in command:
                output = 'f' * 64
            elif 'restart' in command:
                self.restarts += 1
            elif 'down' in command:
                failure = self.fail == 'cleanup'
                if not failure:
                    self.active = False
        elif command[:2] == ['docker', 'inspect']:
            if '--format' not in command:
                raise AssertionError('full container inspect is forbidden')
            details = runtime_fixture(self.port)
            if self.bad_runtime:
                details['readonly'] = False
            output = json.dumps(details)
        elif command[:2] == ['docker', 'exec']:
            output = '10001\n'
        elif command[:3] == ['docker', 'image', 'inspect']:
            failure = not self.image_exists or self.fail == 'build-query'
            output = 'sha256:' + 'f' * 64 if self.image_exists else ''
        elif command[:3] == ['docker', 'image', 'ls']:
            if command[-1] != 'reference=' + self.tag:
                raise AssertionError('query escaped the isolated image tag')
            failure = self.fail == 'build-query'
            output = 'f' * 64 if self.image_exists else ''
        elif command[:3] == ['docker', 'image', 'rm']:
            if command[-1] != self.tag:
                raise AssertionError('attempted to remove an unrelated image')
            failure = self.fail == 'image-cleanup'
            if not failure:
                self.image_exists = False
        else:
            raise AssertionError('unexpected Docker operation')
        if failure:
            return subprocess.CompletedProcess(command, 1, 'private-output', 'ambient-secret')
        return subprocess.CompletedProcess(command, 0, output, '')

    @staticmethod
    def assert_private_capture(kwargs):
        if not kwargs.get('capture_output'):
            raise AssertionError('Docker subprocess output can leak')
        if kwargs.get('check'):
            raise AssertionError('raw command exceptions can leak credential material')


class ComposeLifecycleTests(unittest.TestCase):
    def run_fixture(self, boundary):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / 'report.json'
            stdout, stderr = io.StringIO(), io.StringIO()
            original_env = ROOT / '.env'
            before = original_env.read_bytes() if original_env.exists() else None
            with patch.dict(os.environ, {'SUBWAY_API_TOKENS': 'ambient-secret',
                                         'BACKEND_PORT': '1', 'COMPOSE_FILE': 'unrelated.yaml'}), \
                    patch.object(smoke.subprocess, 'run', side_effect=boundary), \
                    patch.object(smoke, 'check_unconfigured') as unconfigured, \
                    patch.object(smoke, 'check_keyed') as keyed, \
                    patch.object(smoke, 'request', return_value=(200, {}, b'[]')), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = smoke.main(['--report', str(report_path)])
            report_text = report_path.read_text()
            report = json.loads(report_text)
            combined = report_text + stdout.getvalue() + stderr.getvalue()
            self.assertNotIn('ambient-secret', combined)
            self.assertNotIn('private-output', combined)
            for secret in boundary.secrets:
                self.assertNotIn(secret, combined)
            self.assertEqual(before, original_env.read_bytes() if original_env.exists() else None)
            self.assertTrue(all(not path.exists() for path in boundary.private_files))
            return result, report, unconfigured.call_count, keyed.call_count

    def test_success_checks_both_phases_restarts_and_cleans_own_resources(self):
        boundary = DockerBoundary()
        result, report, unconfigured, keyed = self.run_fixture(boundary)
        self.assertEqual(result, 0)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['cleanup']['status'], 'passed')
        self.assertFalse(boundary.active)
        self.assertFalse(boundary.image_exists)
        self.assertEqual(boundary.builds, 1)
        self.assertEqual(boundary.phases, [False, True])
        self.assertEqual(boundary.restarts, 1)
        self.assertEqual((unconfigured, keyed), (1, 1))
        self.assertNotEqual(boundary.port, '1')
        self.assertTrue(all(env['SUBWAY_API_TOKENS'] != 'ambient-secret'
                            for env in boundary.environments))

    def test_runtime_policy_failure_still_cleans_and_never_reports_success(self):
        boundary = DockerBoundary(bad_runtime=True)
        result, report, _, keyed = self.run_fixture(boundary)
        self.assertEqual(result, 1)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['cleanup']['status'], 'passed')
        self.assertFalse(boundary.active)
        self.assertFalse(boundary.image_exists)
        self.assertEqual(keyed, 0)

    def test_build_failure_still_attempts_isolated_project_cleanup(self):
        boundary = DockerBoundary(fail='build')
        result, report, unconfigured, keyed = self.run_fixture(boundary)
        self.assertEqual(result, 1)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['cleanup']['status'], 'passed')
        self.assertTrue(any('down' in command for command in boundary.commands))
        self.assertEqual((unconfigured, keyed), (0, 0))

    def test_cleanup_failures_turn_otherwise_passing_run_into_failure(self):
        for failure in ('cleanup', 'image-cleanup'):
            with self.subTest(failure=failure):
                result, report, _, _ = self.run_fixture(DockerBoundary(fail=failure))
                self.assertEqual(result, 1)
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['cleanup']['status'], 'failed')

    def test_image_query_error_after_failed_build_is_not_reported_as_clean(self):
        boundary = DockerBoundary(fail='build-query')
        result, report, _, _ = self.run_fixture(boundary)
        self.assertEqual(result, 1)
        self.assertTrue(boundary.image_exists)
        self.assertEqual(report['cleanup']['status'], 'failed')
        self.assertEqual(report['cleanup']['image'], 'failed')
        self.assertIn('cleanup-image', report['failures'])

    def test_old_or_unrecognized_engine_cannot_claim_loopback_isolation(self):
        for version in ('27.5.1', '20.10.24', '', 'not-a-version'):
            with self.subTest(version=version):
                boundary = DockerBoundary(engine_version=version)
                result, report, _, _ = self.run_fixture(boundary)
                self.assertEqual(result, 1)
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(boundary.builds, 0)
                self.assertFalse(boundary.active)

    def test_missing_engine_is_failed_and_not_skipped(self):
        result, report, _, _ = self.run_fixture(DockerBoundary(fail='engine'))
        self.assertEqual(result, 1)
        self.assertEqual(report['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
