"""Reject untrusted CI runs before their artifacts reach a deployment host."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
from ci_provenance import trusted_source


def valid_run():
    return {
        "id": 123,
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
