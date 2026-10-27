#!/usr/bin/env python3
"""Run destructive, local TEST receipt checks against a fresh subway_alert_test DB.

Required environment: SUBWAY_POSTGRES_TEST_ONLY=1, MONITOR_DB_URL (a direct
jdbc:postgresql://host:port/subway_alert_test URL), MONITOR_DB_USER and
MONITOR_DB_PASSWORD. Requires Java and psql on PATH. Never use a real database.
The database is deliberately left populated for inspection; recreate it before
another run. All subprocess output stays private, including failure output.
"""

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
import uuid

from smoke_api_access import isolated_java_environment, request


class SmokeFailure(Exception):
    """Only a fixed stage name, never subprocess details or credentials."""


def require(condition, stage):
    # Every caller supplies a fixed, credential-free stage name; never assert.
    if not condition:
        raise SmokeFailure(stage)


class Database:
    def __init__(self, url, user, password, environment):
        self.url, self.user, self.password = url, user, password
        self.environment = environment

    @classmethod
    def from_environment(cls, source):
        if source.get('SUBWAY_POSTGRES_TEST_ONLY') != '1':
            raise SmokeFailure('explicit-test-opt-in-required')
        url = source.get('MONITOR_DB_URL', '')
        try:
            parsed = urlsplit(url.removeprefix('jdbc:'))
            if (not url.startswith('jdbc:postgresql://') or parsed.scheme != 'postgresql'
                    or not parsed.hostname or parsed.path != '/subway_alert_test'
                    or parsed.query or parsed.fragment or parsed.username or parsed.password
                    or parsed.port is not None and not 1 <= parsed.port <= 65535
                    or any(character.isspace() for character in url)):
                raise ValueError()
        except ValueError:
            raise SmokeFailure('dedicated-test-database-required') from None
        user, password = source.get('MONITOR_DB_USER', ''), source.get('MONITOR_DB_PASSWORD', '')
        if not user or not password:
            raise SmokeFailure('database-credentials-required')
        # Ignore libpq's ambient service/options/file selectors. The exact same
        # host, port, user and database must be used by psql and the JDBC server.
        environment = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
        environment.update(PGHOST=parsed.hostname, PGPORT=str(parsed.port or 5432),
                           PGDATABASE='subway_alert_test', PGUSER=user, PGPASSWORD=password,
                           PGCONNECT_TIMEOUT='5', PGAPPNAME='subway-alert-durability-smoke')
        return cls(url, user, password, environment)

    def execute(self, statement, stage):
        try:
            return subprocess.run(
                ['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=sqlstate',
                 '-A', '-t', '-F', '|', '-c', statement],
                env=self.environment, capture_output=True, text=True, check=False, timeout=15)
        except (OSError, subprocess.SubprocessError):
            raise SmokeFailure(stage) from None

    def sql(self, statement, stage):
        result = self.execute(statement, stage)
        if result.returncode != 0:
            raise SmokeFailure(stage)
        return result.stdout.strip()


def check_fresh_database(database):
    # Reject schema/function/type/relation leftovers before launching Java. No
    # schema DROP/TRUNCATE is ever attempted, even after an interrupted smoke.
    answer = database.sql("""
        SELECT current_database(),
          (SELECT count(*) FROM pg_namespace WHERE nspname <> 'public'
            AND nspname <> 'information_schema' AND left(nspname,3) <> 'pg_') +
          (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public') +
          (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public') +
          (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
            WHERE n.nspname='public')
    """, 'fresh-database-preflight')
    if answer != 'subway_alert_test|0':
        raise SmokeFailure('fresh-dedicated-test-database-required')


class JarServer:
    """Separate packaged processes, each with an isolated loopback HTTP port."""
    def __init__(self, jar, database, api_tokens, private_values=(), poll_interval_ms=3600000):
        self.jar, self.database, self.api_tokens = jar, database, api_tokens
        self.private_values = [database.password, database.url, *api_tokens.split(','), *private_values]
        self.process = self.log = None
        self.poll_interval_ms = poll_interval_ms
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            self.port = listener.getsockname()[1]

    def launch(self):
        environment = isolated_java_environment()
        environment.update(SERVER_ADDRESS='127.0.0.1', PORT=str(self.port),
                           MONITOR_STORE='postgres', MONITOR_DB_URL=self.database.url,
                           MONITOR_DB_USER=self.database.user, MONITOR_DB_PASSWORD=self.database.password,
                           SUBWAY_API_TOKENS=self.api_tokens, FCM_ENABLED='false',
                           SEOUL_SUBWAY_KEY='sample', MONITOR_POLL_INTERVAL_MS=str(self.poll_interval_ms))
        self.log = tempfile.TemporaryFile()
        try:
            self.process = subprocess.Popen(['java', '-jar', str(self.jar)], env=environment,
                                            stdout=self.log, stderr=subprocess.STDOUT)
        except OSError:
            self.log.close()
            self.log = None
            raise SmokeFailure('jar-launch') from None

    def wait_healthy(self):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise SmokeFailure('jar-startup')
            try:
                if request(self.port, '/api/health')[0] == 200:
                    return
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.1)
        raise SmokeFailure('jar-health-timeout')

    def __enter__(self):
        self.launch()
        try:
            self.wait_healthy()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log is not None:
            self.log.seek(0)
            output = self.log.read()
            self.log.close()
            self.log = None
            if any(value.encode() in output for value in self.private_values if value):
                raise SmokeFailure('server-log-secret-exposure')


def json_request(port, path, token, method='GET', body=None, secret=None, identity=None, status=200):
    actual, _, payload = request(port, path, token, method, body,
                                 session_token=secret, idempotency_key=identity)
    require(actual == status, 'unexpected-monitor-http-status')
    return json.loads(payload) if payload else {}


def receipt_rows(database):
    return json.loads(database.sql("""
      SELECT coalesce(json_agg(row_to_json(r)), '[]'::json) FROM
        (SELECT id::text, session_hash, fingerprint_hash, expires_at, state, delivery_status
         FROM subway_alert_private.monitor_receipts ORDER BY id) r
    """, 'receipt-inspection'))


def check_private_schema(database, identities, capabilities, body, fcm_token, api_tokens):
    columns = database.sql("""
      SELECT string_agg(column_name, ',' ORDER BY ordinal_position)
      FROM information_schema.columns
      WHERE table_schema='subway_alert_private' AND table_name='monitor_receipts'
    """, 'schema-columns')
    require(columns == 'id,session_hash,fingerprint_hash,expires_at,state,delivery_status',
            'receipt-table-must-contain-only-approved-columns')
    rows = receipt_rows(database)
    require({row['id'] for row in rows} == set(identities), 'receipt-identities')
    fingerprint = hashlib.sha256('\0'.join(body[name] for name in (
        'lineId', 'trainId', 'direction', 'previousStation', 'destinationStation', 'fcmToken', 'mode')
    ).encode()).hexdigest()
    for row in rows:
        index = identities.index(row['id'])
        require(row['session_hash'] == hashlib.sha256(capabilities[index].encode()).hexdigest(),
                'capability-must-be-sha256')
        require(row['fingerprint_hash'] == (None if index == 2 else fingerprint),
                'request-fingerprint-must-be-sha256-or-tombstone')
    serialized = json.dumps(rows)
    require(all(value not in serialized for value in [fcm_token, *capabilities, *api_tokens]),
            'plaintext-must-not-be-persisted')
    policy = database.sql("""
      SELECT c.relrowsecurity,
        NOT EXISTS (SELECT 1 FROM aclexplode(coalesce(c.relacl, acldefault('r',c.relowner))) a
                    WHERE a.grantee=0),
        NOT EXISTS (SELECT 1 FROM aclexplode(coalesce(n.nspacl, acldefault('n',n.nspowner))) a
                    WHERE a.grantee=0)
      FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='subway_alert_private' AND c.relname='monitor_receipts'
    """, 'private-schema-policy')
    require(policy == 't|t|t', 'rls-and-public-revocation-required')
    # A standard built-in role avoids creating or changing cluster-wide roles.
    # The disposable test DB user must have permission to SET ROLE pg_monitor.
    role = database.sql('SET ROLE pg_monitor; SELECT current_user; RESET ROLE;', 'public-role-probe')
    require('pg_monitor' in role.splitlines(), 'nonowner-role-probe')
    denied = database.execute('SET ROLE pg_monitor; SELECT * FROM subway_alert_private.monitor_receipts LIMIT 0;',
                              'public-read-denial')
    require(denied.returncode != 0 and '42501' in denied.stderr, 'public-read-must-be-denied')


def check_singleton(jar, database, api_tokens, private_values):
    other = JarServer(jar, database, api_tokens, private_values)
    other.launch()
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            code = other.process.poll()
            if code is not None:
                require(code != 0, 'second-backend-must-fail-startup')
                return
            try:
                require(request(other.port, '/api/health')[0] != 200, 'second-backend-must-not-become-healthy')
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.1)
        raise SmokeFailure('second-backend-did-not-exit')
    finally:
        other.close()


def terminate_test_backend(database):
    selected = database.sql("""
      SELECT pid FROM pg_stat_activity
      WHERE datname=current_database() AND usename=current_user
        AND application_name='subway-alert-monitor-store' AND pid<>pg_backend_pid()
    """, 'identify-test-jdbc-session')
    require(re.fullmatch(r'[1-9][0-9]*', selected) is not None,
            'exactly-one-test-jdbc-session-required')
    # Only an integer selected above is interpolated; recheck identity before
    # terminating so an ambiguous lookup cannot interrupt another connection.
    terminated = database.sql("""
      SELECT pg_terminate_backend(pid) FROM pg_stat_activity
      WHERE datname=current_database() AND usename=current_user
        AND application_name='subway-alert-monitor-store' AND pid=""" + selected,
        'terminate-test-jdbc-session')
    require(terminated == 't', 'confirmed-test-jdbc-session-required')


def run_smoke(jar, database):
    check_fresh_database(database)
    identities = [str(uuid.uuid4()) for _ in range(3)]
    capabilities = [secrets.token_hex(32) for _ in range(3)]
    api_tokens = [secrets.token_urlsafe(32) for _ in range(3)]
    fcm_token = 'durable-test-never-send-' + secrets.token_hex(16)
    body = {'lineId': '2', 'trainId': 'durability-nonmatching-train', 'direction': 'INNER',
            'previousStation': '선릉', 'destinationStation': '삼성', 'fcmToken': fcm_token, 'mode': 'TEST'}
    encoded_body = json.dumps(body)
    tokens = ','.join(api_tokens)
    private_values = [*capabilities, fcm_token]
    paths = ['/api/monitor-sessions/' + identity for identity in identities]
    with JarServer(jar, database, tokens, private_values) as first:
        created = [json_request(first.port, '/api/monitor-sessions', api_tokens[index], 'POST',
                                encoded_body, capabilities[index], identity)
                   for index, identity in enumerate(identities[:2])]
        require(all(row['id'] == identities[index] and row['sessionToken'] == capabilities[index]
                    and row['status'] == 'TRACKING' and row['mode'] == 'TEST'
                    for index, row in enumerate(created)), 'new-test-sessions-must-track')
        cancelled = json_request(first.port, paths[1], api_tokens[1], 'DELETE', secret=capabilities[1])
        tombstone = json_request(first.port, paths[2], api_tokens[2], 'DELETE', secret=capabilities[2])
        require(cancelled['status'] == tombstone['status'] == 'CANCELLED', 'cancellation-must-persist')
        original_expiry = [created[0]['expiresAt'], created[1]['expiresAt'], tombstone['expiresAt']]
        replay = json_request(first.port, '/api/monitor-sessions', api_tokens[0], 'POST', encoded_body,
                              capabilities[0], identities[0])
        require(replay['id'] == identities[0] and replay['sessionToken'] == capabilities[0]
                and replay['expiresAt'] == original_expiry[0], 'initial-replay')
        check_singleton(jar, database, tokens, private_values)
        check_private_schema(database, identities, capabilities, body, fcm_token, api_tokens)
    # The active record is stopped on restoration; cancel receipts and their
    # original expiry stay intact. No FCM token exists in reconstructed sessions.
    with JarServer(jar, database, tokens, private_values) as restored:
        for index, identity in enumerate(identities):
            result = json_request(restored.port, paths[index], api_tokens[index], secret=capabilities[index])
            require(result['id'] == identity and result['status'] == 'CANCELLED'
                    and result['expiresAt'] == original_expiry[index]
                    and result['deliveryStatus'] == 'NONE', 'restored-safe-stop-and-original-expiry')
            replay = json_request(restored.port, '/api/monitor-sessions', api_tokens[index], 'POST', encoded_body,
                                  capabilities[index], identity)
            require(replay['id'] == identity and replay['sessionToken'] == capabilities[index]
                    and replay['status'] == 'CANCELLED'
                    and replay['expiresAt'] == original_expiry[index], 'restored-cancelled-replay')
            json_request(restored.port, paths[index], api_tokens[index], secret=secrets.token_hex(32), status=404)
            json_request(restored.port, '/api/monitor-sessions', api_tokens[index], 'POST', encoded_body,
                         secrets.token_hex(32), identity, status=409)
            json_request(restored.port, paths[index] + '/test', api_tokens[index], 'POST', secret=capabilities[index], status=409)
        for index, path in enumerate(paths):
            stopped = json_request(restored.port, path, api_tokens[index], secret=capabilities[index])
            require(stopped['deliveryStatus'] == 'NONE' and stopped['pollStatus'] == 'NOT_POLLED',
                    'restored-receipts-must-never-poll-or-send')
        check_private_schema(database, identities, capabilities, body, fcm_token, api_tokens)
        # Kill just this test backend's dedicated JDBC session, never the shared
        # database service or any unrecognized connection.
        terminate_test_backend(database)
        identity, capability = str(uuid.uuid4()), secrets.token_hex(32)
        restored.private_values.append(capability)
        json_request(restored.port, '/api/monitor-sessions/' + identity, api_tokens[0], 'DELETE',
                     secret=capability, status=503)
        json_request(restored.port, paths[0], api_tokens[0], secret=capabilities[0], status=503)
        json_request(restored.port, '/api/monitor-sessions', api_tokens[0], 'POST', encoded_body,
                     capability, identity, status=503)
        json_request(restored.port, paths[0] + '/test', api_tokens[0], 'POST', secret=capabilities[0], status=503)
        require(request(restored.port, '/api/health')[0] == 200, 'health-remains-liveness-only')
        require({row['id'] for row in receipt_rows(database)} == set(identities),
                'failed-write-must-not-be-acknowledged-or-persisted')
        connections = database.sql("""
          SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()
            AND application_name='subway-alert-monitor-store'
        """, 'no-automatic-database-reconnect')
        require(connections == '0', 'failed-backend-must-not-reconnect')
    # PostgreSQL remained available; an explicit restart restores service.
    with JarServer(jar, database, tokens, private_values) as recovered:
        result = json_request(recovered.port, paths[0], api_tokens[0], secret=capabilities[0])
        require(result['expiresAt'] == original_expiry[0] and result['status'] == 'CANCELLED',
                'explicit-restart-recovery')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jar', type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        database = Database.from_environment(os.environ)
        if not arguments.jar.is_file():
            raise SmokeFailure('packaged-jar-required')
        run_smoke(arguments.jar, database)
    except SmokeFailure as failure:
        print('PostgreSQL durability smoke failed: ' + str(failure), file=sys.stderr)
        return 1
    except (AssertionError, OSError, ValueError, KeyError, subprocess.SubprocessError):
        # Assertion texts are fixed but keep the CLI boundary uniformly private.
        print('PostgreSQL durability smoke failed: contract-check', file=sys.stderr)
        return 1
    print('PostgreSQL durability smoke passed: restart, stable replay/expiry, tombstones, capability protection,')
    print('singleton lock, hashes-only private schema/RLS, safe-stop/no resend, outage 503 and explicit restart.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
