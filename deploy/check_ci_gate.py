#!/usr/bin/env python3
"""Require every CI validation result; missing input never means success."""

import json
import os
from pathlib import Path

REQUIRED_JOBS = (
    "static-analysis",
    "mobile-domain-and-data",
    "server",
    "postgres-durability",
    "docker-backend",
    "android-test-apk",
)


def validate_results(results):
    if not isinstance(results, dict) or set(results) != set(REQUIRED_JOBS):
        raise ValueError("Missing or unexpected CI validation jobs")
    for name in REQUIRED_JOBS:
        result = results[name]
        if not isinstance(result, dict) or result.get("result") != "success":
            raise ValueError("Required CI validation did not succeed: " + name)


def main():
    results = None
    status = 1
    message = "Invalid CI results"
    try:
        results = json.loads(os.environ.get("RESULTS", ""))
        validate_results(results)
        status = 0
        message = "Every required validation and artifact job passed."
    except (ValueError, TypeError) as error:
        if isinstance(error, json.JSONDecodeError):
            message = "Missing or malformed CI results"
        else:
            message = str(error)
    print(message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with Path(summary).open("a", encoding="utf-8") as stream:
                stream.write("## CI gate\n\n| Check | Result |\n| --- | --- |\n")
                for name in REQUIRED_JOBS:
                    job = results.get(name) if isinstance(results, dict) else None
                    result = job.get("result") if isinstance(job, dict) else None
                    safe = (
                        result
                        if result in ("success", "failure", "cancelled", "skipped")
                        else "missing/invalid"
                    )
                    stream.write(f"| {name} | {safe} |\n")
                stream.write("\n" + message + "\n")
        except OSError:
            print("Cannot write CI summary")
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
