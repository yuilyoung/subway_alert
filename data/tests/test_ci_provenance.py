"""Reject untrusted CI runs before their artifacts reach a deployment host."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
from ci_provenance import trusted_source


def valid_run():
    return {
        "id": 123,
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "event": "push",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "path": ".github/workflows/ci.yml",
        "repository": {"full_name": "yuilyoung/subway_alert"},
        "head_repository": {"full_name": "yuilyoung/subway_alert"},
    }


class ProvenanceTests(unittest.TestCase):
    def test_invalid_or_missing_attempt_is_rejected(self):
        for attempt in (None, 0, -1, True, "2", 2.0):
            with self.subTest(attempt=attempt), self.assertRaises(ValueError):
                trusted_source({**valid_run(), "run_attempt": attempt}, 123)
        run = valid_run()
        del run["run_attempt"]
        with self.assertRaises(ValueError):
            trusted_source(run, 123)

    def test_cli_selects_exact_latest_attempt_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            response = Path(directory) / "run.json"
            response.write_text(json.dumps({**valid_run(), "run_attempt": 2}))
            command = Path(__file__).resolve().parents[2] / "deploy/ci_provenance.py"
            result = subprocess.run(
                [sys.executable, str(command), str(response), "--run-id", "123"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn(
                "artifact_name=backend-release-" + "a" * 40 + "-attempt-2\n", result.stdout
            )
            self.assertIn("run_attempt=2\n", result.stdout)

    def test_successful_main_push_has_exact_artifact_identity(self):
        self.assertEqual(trusted_source(valid_run(), 123), "a" * 40)

    def test_rejects_pull_request_failure_skipped_and_other_workflow(self):
        changes = [
            ("event", "pull_request"),
            ("event", "workflow_dispatch"),
            ("status", "in_progress"),
            ("conclusion", "failure"),
            ("conclusion", "skipped"),
            ("conclusion", "cancelled"),
            ("head_branch", "feat/test"),
            ("path", ".github/workflows/other.yml"),
            ("head_sha", "x" * 40),
            ("head_sha", "abc"),
            ("id", 124),
            ("repository", {"full_name": "attacker/subway_alert"}),
            ("head_repository", {"full_name": "attacker/subway_alert"}),
        ]
        for name, value in changes:
            with self.subTest(name=name, value=value):
                run = copy.deepcopy(valid_run())
                run[name] = value
                with self.assertRaises(ValueError):
                    trusted_source(run, 123)

    def test_missing_and_malformed_payloads_fail_closed(self):
        for run in (None, [], {}, {**valid_run(), "head_repository": None}):
            with self.subTest(run=run), self.assertRaises(ValueError):
                trusted_source(run, 123)
        for run_id in (0, -1, "123", True):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                trusted_source(valid_run(), run_id)
