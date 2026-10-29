"""Database smoke safety boundaries; this suite never contacts PostgreSQL."""

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "smoke_postgres.py"
sys.path.insert(0, str(ROOT / "deploy"))


def load_smoke():
    spec = importlib.util.spec_from_file_location("smoke_postgres", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_environment():
    return {
        "SUBWAY_POSTGRES_TEST_ONLY": "1",
        "MONITOR_DB_URL": "jdbc:postgresql://127.0.0.1:5432/subway_alert_test",
        "MONITOR_DB_USER": "fixture-user",
        "MONITOR_DB_PASSWORD": "fixture-secret",
    }


class PostgresSmokeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.smoke = load_smoke()

    def test_explicit_opt_in_and_exact_test_database_are_required_before_processes(self):
        bad = [
            dict(valid_environment(), SUBWAY_POSTGRES_TEST_ONLY=value)
            for value in ("", "true", "0")
        ]
        bad += [
            dict(valid_environment(), MONITOR_DB_URL=url)
            for url in (
                "jdbc:postgresql://127.0.0.1:5432/subway_alert",
                "jdbc:postgresql://127.0.0.1:5432/subway_alert_test_backup",
                "jdbc:postgresql://127.0.0.1:5432/subway_alert_test?user=secret",
                "jdbc:postgresql://user:secret@127.0.0.1:5432/subway_alert_test",
                "jdbc:postgresql://127.0.0.1:5432/%73ubway_alert_test",
                "postgresql://127.0.0.1:5432/subway_alert_test",
                "jdbc:postgresql:///subway_alert_test",
                "jdbc:postgresql://127.0.0.1:99999/subway_alert_test",
            )
        ]
        bad += [
            dict(valid_environment(), **{name: ""})
            for name in ("MONITOR_DB_USER", "MONITOR_DB_PASSWORD")
        ]
        with tempfile.NamedTemporaryFile(suffix=".jar") as jar:
            for environment in bad:
                with (
                    self.subTest(
                        environment={
                            k: v for k, v in environment.items() if k != "MONITOR_DB_PASSWORD"
                        }
                    ),
                    patch.dict(os.environ, environment, clear=True),
                    patch.object(self.smoke.subprocess, "run") as run,
                    patch.object(self.smoke.subprocess, "Popen") as popen,
                    contextlib.redirect_stdout(io.StringIO()) as stdout,
                    contextlib.redirect_stderr(io.StringIO()) as stderr,
                ):
                    self.assertEqual(self.smoke.main(["--jar", jar.name]), 1)
                    run.assert_not_called()
                    popen.assert_not_called()
                    self.assertNotIn("fixture-secret", stdout.getvalue() + stderr.getvalue())
                    self.assertNotIn(
                        environment.get("MONITOR_DB_URL", ""), stdout.getvalue() + stderr.getvalue()
                    )

    def test_jar_launch_cannot_inherit_spring_jvm_or_other_app_overrides(self):
        database = self.smoke.Database.from_environment(valid_environment())
        hostile = {
            "PATH": "/fixture/bin",
            "JAVA_HOME": "/fixture/jdk",
            "LANG": "C.UTF-8",
            "SPRING_APPLICATION_JSON": '{"MONITOR_DB_URL":"jdbc:postgresql://live/production","FCM_ENABLED":true}',
            "SPRING_CONFIG_LOCATION": "https://live/config.properties",
            "SPRING_CONFIG_ADDITIONAL_LOCATION": "file:/live/",
            "SPRING_CONFIG_IMPORT": "https://live/extra.properties",
            "SPRING_PROFILES_ACTIVE": "production",
            "JAVA_TOOL_OPTIONS": "-DMONITOR_DB_URL=jdbc:postgresql://live/production",
            "JDK_JAVA_OPTIONS": "-DFCM_ENABLED=true",
            "_JAVA_OPTIONS": "-Dserver.address=0.0.0.0",
            "MONITOR_DB_URL": "jdbc:postgresql://live/production",
            "MONITOR_DB_USER": "live-user",
            "MONITOR_DB_PASSWORD": "live-password",
            "MONITOR_STORE": "memory",
            "FCM_ENABLED": "true",
            "FIREBASE_CREDENTIALS": "/live/credential.json",
            "SEOUL_SUBWAY_KEY": "live-provider-key",
            "UNRELATED_PRIVATE_SETTING": "live-secret",
        }
        with (
            patch.dict(os.environ, hostile, clear=True),
            patch.object(self.smoke.subprocess, "Popen") as popen,
        ):
            popen.return_value.poll.return_value = 0
            server = self.smoke.JarServer(Path("fixture.jar"), database, "fixture-api-token")
            try:
                server.launch()
            finally:
                server.close()
        launched = popen.call_args.kwargs["env"]
        self.assertFalse(
            any(name.startswith("SPRING_") for name in launched),
            "Spring configuration must not override the preflight-tested DB",
        )
        self.assertTrue(
            all(
                name not in launched
                for name in (
                    "JAVA_TOOL_OPTIONS",
                    "JDK_JAVA_OPTIONS",
                    "_JAVA_OPTIONS",
                    "FIREBASE_CREDENTIALS",
                    "UNRELATED_PRIVATE_SETTING",
                )
            )
        )
        self.assertEqual(launched["PATH"], hostile["PATH"])
        self.assertEqual(launched["JAVA_HOME"], hostile["JAVA_HOME"])
        self.assertEqual(launched["MONITOR_DB_URL"], database.url)
        self.assertEqual(launched["MONITOR_DB_USER"], database.user)
        self.assertEqual(launched["MONITOR_DB_PASSWORD"], database.password)
        self.assertEqual(launched["MONITOR_STORE"], "postgres")
        self.assertEqual(launched["FCM_ENABLED"], "false")
        self.assertEqual(launched["SEOUL_SUBWAY_KEY"], "sample")
        self.assertEqual(launched["SERVER_ADDRESS"], "127.0.0.1")
        self.assertEqual(launched["MONITOR_POLL_INTERVAL_MS"], "3600000")

    def test_psql_uses_environment_password_and_captures_private_failures(self):
        database = self.smoke.Database.from_environment(valid_environment())
        with patch.object(
            self.smoke.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [], 1, "private-output fixture-secret", "private-error fixture-secret"
            ),
        ) as run:
            with self.assertRaises(self.smoke.SmokeFailure) as failure:
                database.sql("SELECT 1", "fixture-stage")
        self.assertEqual(str(failure.exception), "fixture-stage")
        arguments, kwargs = run.call_args
        self.assertNotIn("fixture-secret", str(arguments))
        self.assertNotIn("jdbc:", str(arguments))
        self.assertEqual(kwargs["env"]["PGPASSWORD"], "fixture-secret")
        self.assertEqual(kwargs["env"]["PGDATABASE"], "subway_alert_test")
        self.assertTrue(kwargs["capture_output"])
        self.assertFalse(kwargs["check"])
        self.assertLessEqual(kwargs["timeout"], 15)
        self.assertIn("-X", arguments[0])

    def test_ambient_pg_connection_selection_cannot_override_explicit_database(self):
        with patch.dict(
            os.environ,
            {
                "PGSERVICE": "production",
                "PGOPTIONS": "-c role=other",
                "PGDATABASE": "production",
                "PGPASSWORD": "ambient-secret",
            },
        ):
            database = self.smoke.Database.from_environment(valid_environment())
        self.assertNotIn("PGSERVICE", database.environment)
        self.assertNotIn("PGOPTIONS", database.environment)
        self.assertEqual(database.environment["PGDATABASE"], "subway_alert_test")
        self.assertEqual(database.environment["PGPASSWORD"], "fixture-secret")

    def test_nonempty_or_wrong_database_is_rejected_before_server_launch(self):
        for answer in ("subway_alert_test|1", "production|0", "subway_alert_test|0\nother", ""):
            with (
                self.subTest(answer=answer),
                patch.object(self.smoke.Database, "sql", return_value=answer),
                patch.object(self.smoke, "JarServer") as server,
            ):
                database = self.smoke.Database.from_environment(valid_environment())
                with self.assertRaises(self.smoke.SmokeFailure):
                    self.smoke.check_fresh_database(database)
                server.assert_not_called()

    def test_outage_never_terminates_ambiguous_or_unrecognized_connections(self):
        database = self.smoke.Database.from_environment(valid_environment())
        for answer in ("", "123\n456", "not-a-pid", "-1"):
            with (
                self.subTest(answer=answer),
                patch.object(database, "sql", return_value=answer) as sql,
            ):
                with self.assertRaises(self.smoke.SmokeFailure):
                    self.smoke.terminate_test_backend(database)
                self.assertEqual(sql.call_count, 1, "ambiguous connection must not be terminated")
                self.assertNotIn("pg_terminate_backend", sql.call_args.args[0])

    def test_outage_terminates_only_the_confirmed_jdbc_session(self):
        database = self.smoke.Database.from_environment(valid_environment())
        with patch.object(database, "sql", side_effect=["12345", "t"]) as sql:
            self.smoke.terminate_test_backend(database)
        select, terminate = [call.args[0] for call in sql.call_args_list]
        self.assertIn("application_name='subway-alert-monitor-store'", select)
        self.assertIn("datname=current_database()", select)
        self.assertIn("usename=current_user", select)
        self.assertIn("pid=12345", terminate)
        self.assertIn("datname=current_database()", terminate)
        self.assertIn("application_name='subway-alert-monitor-store'", terminate)

    def test_cli_guard_remains_effective_under_python_optimization(self):
        result = subprocess.run(
            [sys.executable, "-O", str(SCRIPT), "--jar", "missing.jar"],
            env=valid_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("fixture-secret", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
