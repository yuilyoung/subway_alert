#!/usr/bin/env python3
"""Select a CD run from a manual request or an opted-in trusted CI event."""

import json
import os
import re
from pathlib import Path

REPOSITORY = "yuilyoung/subway_alert"


def select_run(name, event, ref, auto_enabled):
    if ref != "refs/heads/main" or not isinstance(event, dict):
        raise ValueError("Untrusted CD event")
    if name == "workflow_dispatch":
        inputs = event.get("inputs")
        run_id = inputs.get("ci_run_id") if isinstance(inputs, dict) else None
        if not isinstance(run_id, str) or not re.fullmatch(r"[1-9][0-9]{0,14}", run_id):
            raise ValueError("Invalid CI run ID")
        return int(run_id)
    if name != "workflow_run" or auto_enabled != "true":
        raise ValueError("Automatic CD disabled or unsupported event")
    repository = event.get("repository")
    run = event.get("workflow_run")
    if not isinstance(repository, dict) or repository.get("full_name") != REPOSITORY:
        raise ValueError("Untrusted CD repository")
    if not isinstance(run, dict):
        raise ValueError("Missing CI event")
    required = {
        "event": "push",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
    }
    if any(run.get(key) != value for key, value in required.items()):
        raise ValueError("Untrusted CI event")
    head = run.get("head_repository")
    if not isinstance(head, dict) or head.get("full_name") != REPOSITORY:
        raise ValueError("Untrusted CI source")
    run_id = run.get("id")
    if type(run_id) is not int or not 0 < run_id < 10**15:
        raise ValueError("Invalid CI run ID")
    return run_id


def main():
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        run_id = select_run(
            os.environ.get("GITHUB_EVENT_NAME"),
            event,
            os.environ.get("GITHUB_REF"),
            os.environ.get("STAGING_AUTO_DEPLOY", "false"),
        )
    except (KeyError, OSError, ValueError, TypeError):
        print("CD trigger rejected.")
        return 1
    print(f"ci_run_id={run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
