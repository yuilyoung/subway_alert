"""Run with python3 supabase/tests/test_schema.py against a disposable PostgreSQL container."""
import concurrent.futures
from pathlib import Path
import subprocess
import time
import unittest
import uuid


class SchemaIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container = subprocess.check_output([
            'docker', 'run', '--rm', '-d', '--network', 'none',
            '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
            'postgres:17-alpine',
        ], text=True).strip()
        cls.addClassCleanup(subprocess.run, ['docker', 'stop', cls.container], check=True,
                            stdout=subprocess.DEVNULL)
        for _ in range(60):
            # TCP becomes available only after the image finishes its temporary init server.
            probe = subprocess.run(['docker', 'exec', cls.container, 'pg_isready', '-h', '127.0.0.1',
                                    '-U', 'postgres'], capture_output=True)
            if probe.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('PostgreSQL did not start')
        cls.sql("""
            CREATE ROLE anon;
            CREATE ROLE authenticated;
            CREATE ROLE service_role BYPASSRLS;
            CREATE SCHEMA auth;
            CREATE TABLE auth.users (id uuid PRIMARY KEY);
            CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE SQL STABLE AS $$
              SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid
            $$;
            GRANT USAGE ON SCHEMA auth TO authenticated, anon, service_role;
        """).check_returncode()
        schema = Path(__file__).resolve().parents[1] / 'migrations/drafts/schema.sql'
        cls.sql(schema.read_text()).check_returncode()

    @classmethod
    def sql(cls, query):
        return subprocess.run(['docker', 'exec', '-i', cls.container, 'psql', '-X', '-qAt',
                               '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=verbose', '-U', 'postgres'],
                              input=query, text=True, capture_output=True)

    def setUp(self):
        self.owner, self.other = uuid.uuid4(), uuid.uuid4()
        self.expect(f"INSERT INTO auth.users VALUES ('{self.owner}'), ('{self.other}')")

    def expect(self, query, value='', *, error=None):
        response = self.sql(query)
        if error:
            self.assertNotEqual(response.returncode, 0)
            self.assertIn(error, response.stderr)
        else:
            self.assertEqual(response.returncode, 0, response.stderr)
            self.assertEqual(response.stdout.strip(), value)

    @staticmethod
    def user(uid):
        return f"SET ROLE authenticated; SET request.jwt.claim.sub='{uid}'; "

    @staticmethod
    def favorite(uid, slot):
        return ("INSERT INTO commute_favorites(user_id,slot,label,line_id,origin_station_id,destination_station_id) "
                f"VALUES('{uid}',{slot},'commute','2','a','b');")

    def test_favorite_visibility_and_mutations(self):
        owner, other = self.user(self.owner), self.user(self.other)
        self.expect(owner + self.favorite(self.owner, 1))
        self.expect(other + 'SELECT count(*) FROM commute_favorites', '0')
        self.expect(other + 'UPDATE commute_favorites SET label=\'other\'; DELETE FROM commute_favorites;')
        self.expect(owner + 'SELECT label FROM commute_favorites', 'commute')
        self.expect(other + self.favorite(self.owner, 2), error='42501')
        self.expect(owner + f"UPDATE commute_favorites SET user_id='{self.other}'", error='42501')
        self.expect('SET ROLE anon; SELECT * FROM commute_favorites', error='42501')
        self.expect(owner + "UPDATE commute_favorites SET label='home' RETURNING label", 'home')
        self.expect(owner + 'DELETE FROM commute_favorites RETURNING slot', '1')

    def test_slot_limit_and_concurrent_writers(self):
        stmt = self.user(self.owner)
        self.expect(stmt + self.favorite(self.owner, 6), error='23514')
        query = stmt + self.favorite(self.owner, 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(self.sql, [query, query]))
        self.assertEqual(sum(r.returncode == 0 for r in responses), 1)
        self.assertTrue(any('23505' in r.stderr for r in responses))
        self.expect(stmt + 'SELECT count(*) FROM commute_favorites', '1')

    def test_session_and_alert_ownership_and_cascade(self):
        session = uuid.uuid4()
        insert = ("INSERT INTO tracking_sessions(id,user_id,line_id,origin_station_id,"
                  "destination_station_id,train_id,direction) "
                  f"VALUES('{session}','{self.owner}','2','a','b','0007','INNER');")
        self.expect(self.user(self.owner) + insert, error='42501')
        self.expect('SET ROLE service_role; ' + insert)
        self.expect(self.user(self.owner) + 'SELECT count(*) FROM tracking_sessions', '1')
        self.expect(self.user(self.other) + 'SELECT count(*) FROM tracking_sessions', '0')
        alert = f"SET ROLE service_role; INSERT INTO alert_logs(session_id,user_id,outcome) VALUES('{session}',"
        self.expect(alert + f"'{self.other}','sent')", error='23503')
        self.expect(alert + f"'{self.owner}','sent')")
        self.expect(self.user(self.owner) + 'SELECT outcome FROM alert_logs', 'sent')
        self.expect(self.user(self.other) + 'SELECT count(*) FROM alert_logs', '0')
        self.expect(f"DELETE FROM auth.users WHERE id='{self.owner}'; "
                    f"SELECT count(*) FROM alert_logs WHERE session_id='{session}'", '0')
        self.expect(f"SELECT count(*) FROM tracking_sessions WHERE id='{session}'", '0')


if __name__ == '__main__':
    unittest.main()
