#!/usr/bin/env python3
"""Prepare staging GitHub settings; the default plan has no external side effects."""

import argparse
import json
import re
import subprocess
import sys

REPOSITORY = "yuilyoung/subway_alert"
ENVIRONMENT = "staging"
REPO = f"repos/{REPOSITORY}"
ENV = f"{REPO}/environments/{ENVIRONMENT}"
AUTO_VARIABLE = "STAGING_AUTO_DEPLOY"
DEPLOY_VARIABLE = "STAGING_DEPLOY_ENABLED"
SECRET_NAMES = (
    "STAGING_SSH_HOST",
    "STAGING_SSH_PORT",
    "STAGING_SSH_USER",
    "STAGING_SSH_PRIVATE_KEY",
    "STAGING_SSH_KNOWN_HOSTS",
)
BRANCH_SELECTOR = {"protected_branches": False, "custom_branch_policies": True}


class SetupFailure(Exception):
    """Only a fixed, non-sensitive operation label may cross the CLI boundary."""


def api(method, endpoint, stage, *, payload=None, missing=False):
    """Use operator-managed gh authentication; capture and discard raw diagnostics."""
    command = [
        "gh",
        "api",
        endpoint,
        "--hostname",
        "github.com",
        "--method",
        method,
        "--include",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2026-03-10",
    ]
    if payload is not None:
        command.extend(["--input", "-"])
    try:
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise SetupFailure(stage) from None
    output = result.stdout.replace("\r\n", "\n")
    headers, separator, body = output.partition("\n\n")
    status = re.match(r"HTTP/\S+ ([0-9]{3})(?:\s|$)", headers)
    if status is None or not separator:
        raise SetupFailure(stage)
    status = int(status[1])
    if missing and status == 404:
        return None
    if result.returncode != 0 or not 200 <= status < 300:
        raise SetupFailure(stage)
    try:
        value = json.loads(body) if body.strip() else {}
    except (ValueError, TypeError):
        raise SetupFailure(stage) from None
    if not isinstance(value, dict):
        raise SetupFailure(stage)
    return value


def collection(endpoint, key, stage):
    """Read every page so a hidden extra rule cannot evade conflict checks."""
    items = []
    for page in range(1, 102):
        response = api("GET", f"{endpoint}?per_page=100&page={page}", stage)
        count = response.get("total_count")
        values = response.get(key)
        if type(count) is not int or count < 0 or not isinstance(values, list):
            raise SetupFailure(stage)
        if not all(isinstance(item, dict) for item in values):
            raise SetupFailure(stage)
        items.extend(values)
        if len(items) == count:
            return items
        if not values or len(items) > count:
            raise SetupFailure(stage)
    raise SetupFailure(stage)


def valid_login(login):
    return (
        isinstance(login, str)
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", login)
        and "--" not in login
    )


def prerequisites(login):
    repository = api("GET", REPO, "repository_permissions")
    permissions = repository.get("permissions")
    if (
        repository.get("full_name") != REPOSITORY
        or not isinstance(permissions, dict)
        or permissions.get("admin") is not True
        or repository.get("default_branch") != "main"
    ):
        raise SetupFailure("repository_permissions")
    branch = api("GET", f"{REPO}/branches/main", "main_branch")
    if branch.get("name") != "main":
        raise SetupFailure("main_branch")
    reviewer = api("GET", f"users/{login}" if login else "user", "reviewer_identity")
    identity = reviewer.get("id")
    actual_login = reviewer.get("login")
    if (
        type(identity) is not int
        or identity <= 0
        or not valid_login(actual_login)
        or reviewer.get("type") != "User"
        or (login and actual_login.lower() != login.lower())
    ):
        raise SetupFailure("reviewer_identity")
    access = api("GET", f"{REPO}/collaborators/{actual_login}/permission", "reviewer_access")
    user = access.get("user")
    if (
        access.get("permission") not in ("read", "triage", "write", "maintain", "admin")
        or not isinstance(user, dict)
        or user.get("id") != identity
    ):
        raise SetupFailure("reviewer_access")
    return identity


def variable(endpoint, name):
    value = api("GET", f"{endpoint}/{name}", "variables_read", missing=True)
    if value is None:
        return None
    if value.get("name") != name or not isinstance(value.get("value"), str):
        raise SetupFailure("variables_read")
    return value["value"]


def read_state():
    auto = variable(f"{REPO}/actions/variables", AUTO_VARIABLE)
    environment = api("GET", ENV, "environment_read", missing=True)
    policies, deploy = [], None
    if environment is not None:
        policies = collection(
            f"{ENV}/deployment-branch-policies", "branch_policies", "policies_read"
        )
        deploy = variable(f"{ENV}/variables", DEPLOY_VARIABLE)
    return {"environment": environment, "policies": policies, "auto": auto, "deploy": deploy}


def validate_state(state, reviewer, *, disabled):
    """Recognize only the expected configuration, including safe incomplete setup."""
    allowed_values = (None, "false") if disabled else (None, "false", "true")
    if state["auto"] not in allowed_values or state["deploy"] not in allowed_values:
        raise SetupFailure("variables_conflict")
    environment = state["environment"]
    if environment is None:
        return False
    if (
        environment.get("name") != ENVIRONMENT
        or environment.get("deployment_branch_policy") != BRANCH_SELECTOR
    ):
        raise SetupFailure("environment_conflict")
    rules = environment.get("protection_rules")
    if not isinstance(rules, list) or not all(isinstance(rule, dict) for rule in rules):
        raise SetupFailure("environment_conflict")
    required = [rule for rule in rules if rule.get("type") == "required_reviewers"]
    if len(required) != 1 or required[0].get("prevent_self_review") is not False:
        raise SetupFailure("reviewer_conflict")
    reviewers = required[0].get("reviewers")
    if (
        not isinstance(reviewers, list)
        or len(reviewers) != 1
        or not isinstance(reviewers[0], dict)
        or reviewers[0].get("type") != "User"
        or not isinstance(reviewers[0].get("reviewer"), dict)
        or type(reviewers[0]["reviewer"].get("id")) is not int
        or reviewers[0]["reviewer"].get("id") != reviewer
    ):
        raise SetupFailure("reviewer_conflict")
    for rule in rules:
        if rule.get("type") in ("required_reviewers", "branch_policy"):
            continue
        if rule.get("type") == "wait_timer" and rule.get("wait_timer") == 0:
            continue
        raise SetupFailure("environment_conflict")
    policies = state["policies"]
    if len(policies) > 1 or (
        policies and (policies[0].get("name") != "main" or policies[0].get("type") != "branch")
    ):
        raise SetupFailure("branch_policy_conflict")
    return bool(policies) and state["auto"] is not None and state["deploy"] is not None


def apply_settings(state, reviewer):
    """Create missing resources; there is deliberately no update or delete path."""
    if state["auto"] is None:
        api(
            "POST",
            f"{REPO}/actions/variables",
            "repository_variable_create",
            payload={"name": AUTO_VARIABLE, "value": "false"},
        )
    if state["environment"] is None:
        api(
            "PUT",
            ENV,
            "environment_create",
            payload={
                "wait_timer": 0,
                # Solo developers can explicitly approve their own staging deployment.
                "prevent_self_review": False,
                "reviewers": [{"type": "User", "id": reviewer}],
                "deployment_branch_policy": BRANCH_SELECTOR,
            },
        )
    if state["deploy"] is None:
        api(
            "POST",
            f"{ENV}/variables",
            "environment_variable_create",
            payload={"name": DEPLOY_VARIABLE, "value": "false"},
        )
    if not state["policies"]:
        api(
            "POST",
            f"{ENV}/deployment-branch-policies",
            "branch_policy_create",
            payload={"name": "main", "type": "branch"},
        )


def secret_metadata():
    """List names only, never retrieve a secret/public-key/encrypted-value endpoint."""
    try:
        secrets = collection(f"{ENV}/secrets", "secrets", "secret_metadata")
        names = {secret.get("name") for secret in secrets if isinstance(secret.get("name"), str)}
    except SetupFailure:
        return {name: "unknown" for name in SECRET_NAMES}
    return {name: "present" if name in names else "missing" for name in SECRET_NAMES}


def report(mode, *, state=None, prepared=False):
    return {
        "mode": mode,
        "repository": REPOSITORY,
        "environment": ENVIRONMENT,
        "branch": "main",
        "external_state_checked": state is not None,
        "environment_prepared": prepared,
        "manual_deploy_enabled": state is not None and state["deploy"] == "true",
        "auto_deploy_enabled": state is not None and state["auto"] == "true",
        "deployment_ready": False,
        "ssh_configuration": "not_verified",
        "secret_names": {name: "unknown" for name in SECRET_NAMES},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("plan", "apply", "check"), default="plan")
    parser.add_argument("--reviewer")
    args = parser.parse_args(argv)
    try:
        if args.reviewer is not None and not valid_login(args.reviewer):
            raise SetupFailure("reviewer_input")
        if args.mode == "plan":
            output = report("plan")
            output["planned_settings"] = {
                "required_reviewer": "specified_user" if args.reviewer else "authenticated_user",
                "prevent_self_review": False,
                "deployment_branch_policy": BRANCH_SELECTOR,
                "branch_policy": {"name": "main", "type": "branch"},
                "environment_variable": {"name": DEPLOY_VARIABLE, "value": "false"},
                "repository_variable": {"name": AUTO_VARIABLE, "value": "false"},
            }
            print(json.dumps(output, sort_keys=True))
            return 0
        reviewer = prerequisites(args.reviewer)
        state = read_state()
        prepared = validate_state(state, reviewer, disabled=args.mode == "apply")
        if args.mode == "apply":
            apply_settings(state, reviewer)
            try:
                state = read_state()
                prepared = validate_state(state, reviewer, disabled=True)
                if not prepared:
                    raise SetupFailure("verification")
            except SetupFailure:
                raise SetupFailure("verification") from None
        output = report(args.mode, state=state, prepared=prepared)
        if args.mode == "check" and state["environment"] is not None:
            output["secret_names"] = secret_metadata()
        print(json.dumps(output, sort_keys=True))
        return 0 if prepared else 1
    except SetupFailure as error:
        print(
            f"GitHub staging setup failed at {error}; raw diagnostics suppressed. "
            "Partial resources may remain disabled; inspect with check before retrying.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
