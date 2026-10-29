"""The final status must require every declared validation, including on retries."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy"))
try:
    from check_ci_gate import REQUIRED_JOBS, validate_results
except ImportError:
    REQUIRED_JOBS = ()
    validate_results = None


class GateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(validate_results, "a tested fail-closed gate is required")
        self.good = {name: {"result": "success", "outputs": {}} for name in REQUIRED_JOBS}

    def test_all_required_checks_must_succeed(self):
        validate_results(self.good)

    def test_empty_missing_and_extra_checks_are_rejected(self):
        for value in (
            {},
            {"server": {"result": "success"}},
            {**self.good, "extra": {"result": "success"}},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_results(value)

    def test_each_non_success_and_malformed_result_is_rejected(self):
        for name in REQUIRED_JOBS:
            for value in (
                {"result": "failure"},
                {"result": "cancelled"},
                {"result": "skipped"},
                {"result": "pending"},
                {},
                None,
                "success",
                {"result": True},
            ):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    validate_results({**self.good, name: value})
        for value in ([], None, "success", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_results(value)

    def test_workflow_declares_exactly_the_validated_prerequisites(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        gate = workflow.split("  ci-gate:\n", 1)[1]
        match = re.search(r"^    needs: \[([^\]\n]+)\]$", gate, re.MULTILINE)
        self.assertIsNotNone(match, "keep gate needs explicit as a flow list")
        declared = [name.strip() for name in match.group(1).split(",")]
        self.assertEqual(len(declared), len(REQUIRED_JOBS))
        self.assertEqual(set(declared), set(REQUIRED_JOBS))

    def test_cli_fails_for_absent_or_invalid_json_and_succeeds_for_complete_results(self):
        environment = {
            name: value
            for name, value in os.environ.items()
            if name not in ("RESULTS", "GITHUB_STEP_SUMMARY")
        }
        for payload, expected in (
            (None, 1),
            ("not json", 1),
            ("{}", 1),
            (json.dumps(self.good), 0),
        ):
            with self.subTest(payload=payload):
                values = dict(environment)
                if payload is not None:
                    values["RESULTS"] = payload
                result = subprocess.run(
                    [sys.executable, str(ROOT / "deploy/check_ci_gate.py")],
                    env=values,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, expected)

    def test_cli_writes_all_required_results_to_its_own_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            environment = {
                **os.environ,
                "RESULTS": json.dumps(self.good),
                "GITHUB_STEP_SUMMARY": str(summary),
            }
            result = subprocess.run(
                [sys.executable, str(ROOT / "deploy/check_ci_gate.py")],
                env=environment,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            for name in REQUIRED_JOBS:
                self.assertIn(f"| {name} | success |", summary.read_text())
