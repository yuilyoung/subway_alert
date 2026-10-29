"""Untrusted CI completion events must never select a deployment artifact."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
try:
    from cd_event import select_run
except ImportError:
    select_run = None


def completed_main():
    return {
        "repository": {"full_name": "yuilyoung/subway_alert"},
        "workflow_run": {
            "id": 123,
            "event": "push",
            "head_branch": "main",
            "conclusion": "success",
            "status": "completed",
            "head_repository": {"full_name": "yuilyoung/subway_alert"},
        },
    }


class EventTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(select_run, "CD event selector must reject untrusted triggers")

    def test_manual_selects_positive_run_id_on_main(self):
        event = {"inputs": {"ci_run_id": "123"}}
        self.assertEqual(select_run("workflow_dispatch", event, "refs/heads/main", "false"), 123)

    def test_enabled_automatic_main_success_selects_exact_run(self):
        self.assertEqual(
            select_run("workflow_run", completed_main(), "refs/heads/main", "true"), 123
        )

    def test_disabled_automatic_pr_failed_foreign_and_incomplete_events_are_rejected(self):
        for key, value in (
            ("event", "pull_request"),
            ("head_branch", "feat/test"),
            ("conclusion", "failure"),
            ("conclusion", "cancelled"),
            ("status", "in_progress"),
            ("head_repository", {"full_name": "attacker/repo"}),
            ("id", True),
            ("id", "123"),
        ):
            event = copy.deepcopy(completed_main())
            event["workflow_run"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                select_run("workflow_run", event, "refs/heads/main", "true")
        with self.assertRaises(ValueError):
            select_run("workflow_run", completed_main(), "refs/heads/main", "false")
        with self.assertRaises(ValueError):
            select_run(
                "workflow_run",
                {**completed_main(), "repository": {"full_name": "attacker/repo"}},
                "refs/heads/main",
                "true",
            )

    def test_wrong_ref_missing_payload_and_invalid_manual_ids_are_rejected(self):
        for name, event, ref in (
            ("push", {}, "refs/heads/main"),
            ("workflow_dispatch", {}, "refs/heads/main"),
            ("workflow_run", {}, "refs/heads/main"),
            ("workflow_dispatch", {"inputs": {"ci_run_id": "123"}}, "refs/heads/feature"),
        ):
            with self.subTest(name=name, ref=ref), self.assertRaises(ValueError):
                select_run(name, event, ref, "true")
        for value in (None, True, 123, "0", "-1", "1;echo invalid", "1\n2", "1" * 16):
            with self.subTest(value=value), self.assertRaises(ValueError):
                select_run(
                    "workflow_dispatch",
                    {"inputs": {"ci_run_id": value}},
                    "refs/heads/main",
                    "false",
                )
