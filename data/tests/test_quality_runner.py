"""Quality controls must prove a rule rejected code, not merely a broken tool."""

import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("check_quality", ROOT / "deploy/check_quality.py")
quality = None
if SPEC and Path(SPEC.origin).exists():
    quality = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(quality)


class QualityRunnerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(quality, "the read-only quality runner is missing")
        for redirect in (contextlib.redirect_stdout, contextlib.redirect_stderr):
            output = redirect(io.StringIO())
            output.__enter__()
            self.addCleanup(output.__exit__, None, None, None)

    def command(self, code, output):
        return [sys.executable, "-c", f"print({output!r}); raise SystemExit({code})"]

    def test_successful_normal_check_passes_and_failed_check_stops(self):
        quality.check("good", self.command(0, "clean"), ROOT)
        with self.assertRaises(quality.QualityFailure):
            quality.check("bad", self.command(1, "real violation"), ROOT)

    def test_negative_control_requires_exit_one_and_every_expected_diagnostic(self):
        quality.check(
            "negative",
            self.command(1, "F821 undefined qualityValue"),
            ROOT,
            diagnostics=("F821", "qualityValue"),
        )
        for code, output in (
            (0, "F821 qualityValue"),
            (2, "F821 qualityValue"),
            (1, "could not load configuration"),
            (1, "F821 anotherValue"),
        ):
            with self.subTest(code=code, output=output), self.assertRaises(quality.QualityFailure):
                quality.check(
                    "negative",
                    self.command(code, output),
                    ROOT,
                    diagnostics=("F821", "qualityValue"),
                )

    def test_missing_tool_never_counts_as_a_successful_negative_control(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(quality.QualityFailure):
                quality.check(
                    "missing", [str(Path(directory) / "missing-tool")], ROOT, diagnostics=("F821",)
                )

    def test_normal_checks_send_no_mutating_flags_and_honor_tool_overrides(self):
        commands = []

        def completed(args, **kwargs):
            commands.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, "clean")

        with patch.object(quality.subprocess, "run", side_effect=completed):
            self.assertEqual(
                quality.main(["--maven", "/custom/mvn", "--actionlint", "/custom/actionlint"]), 0
            )
        self.assertEqual(len(commands), 6)
        self.assertIn(["npm", "run", "lint", "--prefix", "mobile"], [args for args, _ in commands])
        self.assertIn(
            ["npm", "run", "format:check", "--prefix", "mobile"], [args for args, _ in commands]
        )
        self.assertIn(["/custom/actionlint", "-no-color"], [args for args, _ in commands])
        self.assertIn(
            [
                "/custom/mvn",
                "--batch-mode",
                "--no-transfer-progress",
                "spotless:check",
                "pmd:check",
            ],
            [args for args, _ in commands],
        )
        for args, _ in commands:
            self.assertFalse({"--write", "--fix", "spotless:apply"}.intersection(args))

    def test_failed_normal_tool_cannot_reach_negative_controls(self):
        with patch.object(
            quality.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "broken")
        ) as process:
            self.assertEqual(quality.main(["--group", "static", "--negative-controls"]), 1)
        self.assertEqual(process.call_count, 1)

    def test_static_group_does_not_require_maven(self):
        with patch.object(
            quality.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "clean")
        ):
            self.assertEqual(quality.main(["--group", "static", "--maven", "/missing/mvn"]), 0)

    def test_prettier_control_uses_temporary_file_for_identifiable_check_diagnostic(self):
        fixtures = []

        def completed(args, **kwargs):
            if "prettier.cjs" in " ".join(args):
                fixture = Path(args[-1])
                self.assertTrue(fixture.is_file(), "Prettier stdin --check only prints '(stdin)'")
                self.assertNotIn(ROOT, fixture.parents)
                self.assertEqual(fixture.read_text(), "export default {unformatted:true}\n")
                self.assertIn(str(ROOT / "mobile/.prettierrc.json"), args)
                fixtures.append(fixture)
                return subprocess.CompletedProcess(args, 1, "configuration failed")
            return subprocess.CompletedProcess(
                args,
                1,
                "no-undef missingQualityValue react-hooks/rules-of-hooks called conditionally "
                "no-console 0 errors, 1 warning ESLint found too many warnings",
            )

        with patch.object(quality.subprocess, "run", side_effect=completed):
            with self.assertRaises(quality.QualityFailure):
                quality.static_controls("actionlint")
        self.assertTrue(fixtures)
        self.assertTrue(all(not fixture.exists() for fixture in fixtures))

    def test_ruff_format_control_uses_temporary_file_for_identifiable_check_diagnostic(self):
        fixtures = []

        def completed(args, **kwargs):
            if "ruff" in args and "format" in args:
                fixture = Path(args[-1])
                self.assertTrue(fixture.is_file(), "Ruff stdin format --check has no diagnostic")
                self.assertNotIn(ROOT, fixture.parents)
                self.assertEqual(fixture.read_text(), "quality_value={'unformatted':True}\n")
                self.assertIn(str(ROOT / "pyproject.toml"), args)
                fixtures.append(fixture)
                return subprocess.CompletedProcess(args, 1, "configuration failed")
            return subprocess.CompletedProcess(
                args,
                1,
                "no-undef missingQualityValue react-hooks/rules-of-hooks called conditionally "
                "no-console 0 errors, 1 warning ESLint found too many warnings "
                "quality-control.js Code style issues found F821 missing_quality_value",
            )

        with patch.object(quality.subprocess, "run", side_effect=completed):
            with self.assertRaises(quality.QualityFailure):
                quality.static_controls("actionlint")
        self.assertTrue(fixtures)
        self.assertTrue(all(not fixture.exists() for fixture in fixtures))

    def test_java_controls_only_write_temporary_fixture_mirror_and_cleanup_on_failure(self):
        before = {path: path.read_bytes() for path in (ROOT / "server").glob("src/**/*.java")}
        mirrors = []

        def broken(args, **kwargs):
            mirror = Path(kwargs["cwd"])
            mirrors.append(mirror)
            self.assertNotEqual(mirror, ROOT / "server")
            self.assertEqual(
                (mirror / "pom.xml").read_bytes(), (ROOT / "server/pom.xml").read_bytes()
            )
            self.assertEqual(
                (mirror / "config/pmd-ruleset.xml").read_bytes(),
                (ROOT / "server/config/pmd-ruleset.xml").read_bytes(),
            )
            self.assertEqual(len(list(mirror.glob("src/**/*.java"))), 1)
            return subprocess.CompletedProcess(args, 1, "configuration failed")

        with patch.object(quality.subprocess, "run", side_effect=broken):
            with self.assertRaises(quality.QualityFailure):
                quality.server_controls("mvn")
        self.assertTrue(mirrors)
        self.assertTrue(all(not mirror.exists() for mirror in mirrors))
        self.assertEqual(
            before, {path: path.read_bytes() for path in (ROOT / "server").glob("src/**/*.java")}
        )


if __name__ == "__main__":
    unittest.main()
