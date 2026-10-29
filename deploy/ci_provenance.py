#!/usr/bin/env python3
"""Validate GitHub's run response before downloading a deployment artifact."""

import argparse
import json
import re
from pathlib import Path

REPOSITORY = "yuilyoung/subway_alert"


def trusted_source(run, run_id):
    """Only completed successful main pushes from our CI may be promoted."""
    if type(run_id) is not int or run_id <= 0 or not isinstance(run, dict):
        raise ValueError("Untrusted CI run")
    if type(run.get("run_attempt")) is not int or run["run_attempt"] <= 0:
        raise ValueError("Invalid CI run attempt")
    required = {
        "id": run_id,
        "status": "completed",
        "conclusion": "success",
        "event": "push",
        "head_branch": "main",
        "path": ".github/workflows/ci.yml",
    }
    if any(run.get(name) != value for name, value in required.items()):
        raise ValueError("Untrusted CI run")
    for name in ("repository", "head_repository"):
        repository = run.get(name)
        if not isinstance(repository, dict) or repository.get("full_name") != REPOSITORY:
            raise ValueError("Untrusted CI run")
    sha = run.get("head_sha")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid source identity")
    return sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("response", type=Path)
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    try:
        run = json.loads(args.response.read_text())
        source = trusted_source(run, args.run_id)
    except (OSError, ValueError, TypeError):
        parser.exit(1, "CI run rejected; require successful main push from CI.\n")
    print(f"source_sha={source}")
    print(f"run_attempt={run['run_attempt']}")
    print(f"artifact_name=backend-release-{source}-attempt-{run['run_attempt']}")


if __name__ == "__main__":
    main()
