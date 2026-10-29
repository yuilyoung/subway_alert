#!/usr/bin/env python3
"""Run source quality checks and optional real-tool rejection controls."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class QualityFailure(Exception):
    """A source check failed or a rejection control did not prove its rule."""


def check(name, command, cwd, *, source=None, diagnostics=()):
    """Require a clean check, or exit 1 plus every intended rejection diagnostic."""
    print(f"Quality: {name}", flush=True)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            input=source,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except OSError as error:
        raise QualityFailure(f"{name}: tool could not start ({error.strerror})") from error
    output = result.stdout or ""
    if output:
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
    expected = 1 if diagnostics else 0
    if result.returncode != expected:
        raise QualityFailure(f"{name}: expected exit {expected}, received {result.returncode}")
    missing = [diagnostic for diagnostic in diagnostics if diagnostic not in output]
    if missing:
        raise QualityFailure(f"{name}: intended rejection diagnostic missing: {', '.join(missing)}")


def static_checks(actionlint):
    check("JavaScript lint", ["npm", "run", "lint", "--prefix", "mobile"], ROOT)
    check("JavaScript format", ["npm", "run", "format:check", "--prefix", "mobile"], ROOT)
    check("Python lint", [sys.executable, "-m", "ruff", "check", "deploy", "data"], ROOT)
    check(
        "Python format",
        [sys.executable, "-m", "ruff", "format", "--check", "deploy", "data"],
        ROOT,
    )
    check("Actions workflows", [actionlint, "-no-color"], ROOT)


def server_checks(maven):
    check(
        "Java format and static analysis",
        [maven, "--batch-mode", "--no-transfer-progress", "spotless:check", "pmd:check"],
        ROOT / "server",
    )


def static_controls(actionlint):
    mobile = ROOT / "mobile"
    eslint = [
        "node",
        str(mobile / "node_modules/eslint/bin/eslint.js"),
        "--stdin",
        "--stdin-filename",
        "src/quality-control.js",
        "--max-warnings=0",
    ]
    check(
        "ESLint undefined variable control",
        eslint,
        mobile,
        source="export default missingQualityValue;\n",
        diagnostics=("no-undef", "missingQualityValue"),
    )
    check(
        "ESLint conditional Hook control",
        eslint,
        mobile,
        source=(
            "import { useState } from 'react';\n"
            "export default function QualityControl({ enabled }) {\n"
            "  if (enabled) { useState(0); }\n"
            "  return null;\n"
            "}\n"
        ),
        diagnostics=("react-hooks/rules-of-hooks", "called conditionally"),
    )
    check(
        "ESLint warning-only control",
        eslint,
        mobile,
        source="/* eslint no-console: warn */\nconsole.log('quality');\n",
        diagnostics=("no-console", "0 errors, 1 warning", "ESLint found too many warnings"),
    )
    # Prettier's stdin --check only prints '(stdin)'; use a temporary file so
    # rejection includes its ordinary identifiable formatting diagnostic.
    with tempfile.TemporaryDirectory(prefix="subway-quality-") as directory:
        fixture = Path(directory) / "quality-control.js"
        fixture.write_text("export default {unformatted:true}\n")
        check(
            "Prettier format control",
            [
                "node",
                str(mobile / "node_modules/prettier/bin/prettier.cjs"),
                "--check",
                "--config",
                str(mobile / ".prettierrc.json"),
                str(fixture),
            ],
            mobile,
            diagnostics=("quality-control.js", "Code style issues found"),
        )
    check(
        "Ruff undefined variable control",
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--stdin-filename",
            "deploy/quality-control.py",
            "-",
        ],
        ROOT,
        source="print(missing_quality_value)\n",
        diagnostics=("F821", "missing_quality_value"),
    )
    with tempfile.TemporaryDirectory(prefix="subway-quality-") as directory:
        fixture = Path(directory) / "quality-control.py"
        fixture.write_text("quality_value={'unformatted':True}\n")
        check(
            "Ruff format control",
            [
                sys.executable,
                "-m",
                "ruff",
                "format",
                "--check",
                "--config",
                str(ROOT / "pyproject.toml"),
                str(fixture),
            ],
            ROOT,
            diagnostics=("Would reformat:", "quality-control.py"),
        )
    check(
        "Actions unknown job key control",
        [actionlint, "-no-color", "-"],
        ROOT,
        source=(
            "name: Quality control\n"
            "on: push\n"
            "jobs:\n"
            "  quality:\n"
            "    runs-on: ubuntu-latest\n"
            "    invalid-quality-key: true\n"
            "    steps:\n"
            "      - run: echo quality\n"
        ),
        diagnostics=('unexpected key "invalid-quality-key"', "[syntax-check]"),
    )


def server_controls(maven):
    # Mirror only configuration and deliberate fixtures; never edit application sources.
    with tempfile.TemporaryDirectory(prefix="subway-quality-") as directory:
        mirror = Path(directory)
        shutil.copy2(ROOT / "server/pom.xml", mirror / "pom.xml")
        shutil.copytree(ROOT / "server/config", mirror / "config")
        fixture = mirror / "src/main/java/QualityControl.java"
        fixture.parent.mkdir(parents=True)
        fixture.write_text("public final class QualityControl{public int value(){return 1;}}\n")
        base = [maven, "--batch-mode", "--no-transfer-progress"]
        check(
            "Spotless format control",
            [*base, "spotless:check"],
            mirror,
            diagnostics=("format violations", "QualityControl.java"),
        )
        fixture.write_text(
            "public final class QualityControl {\n"
            "  public boolean invalid(Object value) {\n"
            "    int deadQualityValue = 1;\n"
            "    return value.equals(null);\n"
            "  }\n"
            "}\n"
        )
        check(
            "PMD defect control",
            [*base, "pmd:check"],
            mirror,
            diagnostics=("UnusedLocalVariable", "EqualsNull", "PMD Failure: QualityControl:"),
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=("static", "server", "all"), default="all")
    parser.add_argument("--negative-controls", action="store_true")
    parser.add_argument("--maven", default="mvn", help="Maven executable name or absolute path")
    parser.add_argument("--actionlint", default="actionlint", help="actionlint executable or path")
    args = parser.parse_args(argv)
    try:
        if args.group in ("static", "all"):
            static_checks(args.actionlint)
        if args.group in ("server", "all"):
            server_checks(args.maven)
        if args.negative_controls:
            if args.group in ("static", "all"):
                static_controls(args.actionlint)
            if args.group in ("server", "all"):
                server_controls(args.maven)
    except (QualityFailure, OSError) as error:
        print(f"Quality checks failed: {error}", file=sys.stderr)
        return 1
    print("Quality checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
