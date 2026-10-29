"""Exercise staging configuration through a fake external GitHub CLI boundary."""

import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import github_environment

SCRIPT = Path(__file__).resolve().parents[2] / "deploy/github_environment.py"
REPO = "repos/yuilyoung/subway_alert"
ENV = REPO + "/environments/staging"
SECRET_NAMES = [
    "STAGING_SSH_HOST",
    "STAGING_SSH_PORT",
    "STAGING_SSH_USER",
    "STAGING_SSH_PRIVATE_KEY",
    "STAGING_SSH_KNOWN_HOSTS",
]


def configured_environment(reviewer_id=7):
    return {
        "id": 45,
        "name": "staging",
        "protection_rules": [
            {
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [
                    {"type": "User", "reviewer": {"id": reviewer_id, "login": "operator"}}
                ],
            },
            {"type": "branch_policy"},
        ],
        "deployment_branch_policy": {
            "protected_branches": False,
            "custom_branch_policies": True,
        },
    }


class GitHubCLI:
    """Stateful external boundary: no actual authentication or network."""

    def __init__(self, *, prepared=False):
        self.calls = []
        self.writes = []
        self.repository = {
            "id": 123,
            "full_name": "yuilyoung/subway_alert",
            "permissions": {"admin": True},
            "default_branch": "main",
        }
        self.user = {"login": "operator", "id": 7, "type": "User"}
        self.other_user = {"login": "reviewer", "id": 9, "type": "User"}
        self.reviewer_permission = "read"
        self.environment = configured_environment() if prepared else None
        self.policies = [{"id": 1, "name": "main", "type": "branch"}] if prepared else []
        self.repo_variable = "false" if prepared else None
        self.env_variable = "false" if prepared else None
        self.secrets = []
        self.fail_once = None
        self.overrides = {}
        self.ignore_write = None

    def __call__(self, command, **kwargs):
        if command[:2] != ["gh", "api"]:
            raise AssertionError("Only gh api requests are allowed")
        if kwargs.get("shell") or not kwargs.get("capture_output") or not kwargs.get("text"):
            raise AssertionError("CLI must capture output and never use a shell")
        if command[command.index("--hostname") + 1] != "github.com":
            raise AssertionError("The fixed repository must use github.com")
        if "--include" not in command:
            raise AssertionError("HTTP status must be parsed independently of raw diagnostics")
        method = command[command.index("--method") + 1]
        endpoint = command[2]
        path = endpoint.partition("?")[0]
        body = json.loads(kwargs["input"]) if kwargs.get("input") else None
        self.calls.append((method, endpoint, body))
        if method != "GET":
            if command[-2:] != ["--input", "-"] or body is None:
                raise AssertionError("Mutations must use structured JSON stdin")
            self.writes.append((method, path, copy.deepcopy(body)))
        if self.fail_once == (method, path):
            self.fail_once = None
            return self.response(command, 403, {"message": "raw-secret-marker"})
        if (method, path) in self.overrides:
            status, value = self.overrides[(method, path)]
            return self.response(command, status, value)
        if method == "GET":
            if path == REPO:
                return self.response(command, 200, self.repository)
            if path == "user":
                return self.response(command, 200, self.user)
            if path == "users/reviewer":
                return self.response(command, 200, self.other_user)
            if path.startswith(REPO + "/collaborators/"):
                user = self.other_user if "/reviewer/" in path else self.user
                return self.response(
                    command, 200, {"permission": self.reviewer_permission, "user": user}
                )
            if path == REPO + "/branches/main":
                return self.response(command, 200, {"name": "main"})
            if path == REPO + "/actions/variables/STAGING_AUTO_DEPLOY":
                return self.variable_response(command, "STAGING_AUTO_DEPLOY", self.repo_variable)
            if path == ENV:
                return self.response(command, 200 if self.environment else 404, self.environment)
            if path == ENV + "/deployment-branch-policies":
                return self.response(
                    command,
                    200,
                    {"total_count": len(self.policies), "branch_policies": self.policies},
                )
            if path == ENV + "/variables/STAGING_DEPLOY_ENABLED":
                return self.variable_response(command, "STAGING_DEPLOY_ENABLED", self.env_variable)
            if path == ENV + "/secrets":
                return self.response(
                    command,
                    200,
                    {
                        "total_count": len(self.secrets),
                        "secrets": [{"name": name} for name in self.secrets],
                    },
                )
        if method == "PUT" and path == ENV:
            if body != {
                "wait_timer": 0,
                "prevent_self_review": False,
                "reviewers": [{"type": "User", "id": body["reviewers"][0]["id"]}],
                "deployment_branch_policy": {
                    "protected_branches": False,
                    "custom_branch_policies": True,
                },
            }:
                raise AssertionError("Unexpected environment creation contract")
            self.environment = configured_environment(body["reviewers"][0]["id"])
            return self.response(command, 200, self.environment)
        if method == "POST" and path == REPO + "/actions/variables":
            if self.repo_variable is not None:
                raise AssertionError("An existing repository variable must never be changed")
            if self.ignore_write != path:
                self.repo_variable = body["value"]
            return self.response(command, 201, None)
        if method == "POST" and path == ENV + "/variables":
            if self.env_variable is not None:
                raise AssertionError("An existing environment variable must never be changed")
            if self.ignore_write != path:
                self.env_variable = body["value"]
            return self.response(command, 201, None)
        if method == "POST" and path == ENV + "/deployment-branch-policies":
            if self.ignore_write != path:
                self.policies.append({"id": 1, **body})
            return self.response(command, 200, self.policies[-1] if self.policies else {})
        raise AssertionError(f"Unexpected external request: {method} {path}")

    def variable_response(self, command, name, value):
        return self.response(command, 404 if value is None else 200, {"name": name, "value": value})

    @staticmethod
    def response(command, status, value):
        return subprocess.CompletedProcess(
            command,
            0 if status < 400 else 1,
            "HTTP/2.0 "
            + str(status)
            + " status\r\nContent-Type: application/json\r\n\r\n"
            + (json.dumps(value) if value is not None else ""),
            "raw-secret-marker" if status >= 400 else "",
        )


def run_cli(arguments, github):
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(subprocess, "run", side_effect=github):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = github_environment.main(arguments)
    return code, json.loads(stdout.getvalue()) if stdout.getvalue() else None, stderr.getvalue()


class PlanTests(unittest.TestCase):
    def test_default_plan_runs_without_gh_authentication_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(SCRIPT)],
                cwd=directory,
                env={"PATH": directory},
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["mode"], "plan")
        self.assertEqual(report["repository"], "yuilyoung/subway_alert")
        self.assertFalse(report["external_state_checked"])
        self.assertFalse(report["deployment_ready"])


class ConfigurationTests(unittest.TestCase):
    def test_apply_creates_disabled_reviewed_main_environment_then_verifies_it(self):
        github = GitHubCLI()
        code, report, errors = run_cli(["apply"], github)
        self.assertEqual(code, 0, errors)
        self.assertEqual(github.repo_variable, "false")
        self.assertEqual(github.env_variable, "false")
        self.assertEqual(github.policies, [{"id": 1, "name": "main", "type": "branch"}])
        self.assertEqual(github.environment, configured_environment())
        self.assertTrue(report["environment_prepared"])
        self.assertFalse(report["deployment_ready"])
        self.assertEqual(report["ssh_configuration"], "not_verified")
        self.assertEqual(
            github.writes[0],
            (
                "POST",
                REPO + "/actions/variables",
                {"name": "STAGING_AUTO_DEPLOY", "value": "false"},
            ),
        )
        self.assertEqual(github.calls[-1][0], "GET")

    def test_existing_environment_is_idempotent_without_any_mutation(self):
        github = GitHubCLI(prepared=True)
        original = copy.deepcopy(github.environment)
        code, report, errors = run_cli(["apply"], github)
        self.assertEqual(code, 0, errors)
        self.assertTrue(report["environment_prepared"])
        self.assertEqual(github.writes, [])
        self.assertEqual(github.environment, original)

    def test_non_admin_and_missing_permissions_fail_before_mutation(self):
        for permissions in ({"admin": False}, {}, {"admin": "true"}):
            with self.subTest(permissions=permissions):
                github = GitHubCLI()
                github.repository["permissions"] = permissions
                code, _, errors = run_cli(["apply"], github)
                self.assertEqual(code, 1)
                self.assertIn("repository_permissions", errors)
                self.assertEqual(github.writes, [])

    def test_missing_main_or_reviewer_access_is_rejected_before_mutation(self):
        for missing in ("main", "reviewer"):
            with self.subTest(missing=missing):
                github = GitHubCLI()
                if missing == "main":
                    github.overrides[("GET", REPO + "/branches/main")] = (404, {})
                else:
                    github.reviewer_permission = "none"
                code, _, _ = run_cli(["apply"], github)
                self.assertEqual(code, 1)
                self.assertEqual(github.writes, [])

    def test_explicit_reviewer_uses_resolved_user_id(self):
        github = GitHubCLI()
        code, _, errors = run_cli(["apply", "--reviewer", "reviewer"], github)
        self.assertEqual(code, 0, errors)
        reviewer = github.environment["protection_rules"][0]["reviewers"][0]
        self.assertEqual(reviewer["reviewer"]["id"], 9)
        self.assertNotIn(("GET", "user", None), github.calls)

    def test_conflicting_rules_or_variables_are_preserved_before_any_mutation(self):
        changes = [
            ("repo_variable", "true"),
            ("repo_variable", "raw-secret-marker"),
            ("env_variable", "true"),
            ("env_variable", "TRUE"),
            ("policies", [{"name": "*", "type": "branch"}]),
            ("policies", [{"name": "main", "type": "tag"}]),
            ("environment", configured_environment(999)),
        ]
        for name, value in changes:
            with self.subTest(name=name, value=value):
                github = GitHubCLI(prepared=True)
                github.repo_variable = None
                setattr(github, name, value)
                snapshot = copy.deepcopy(
                    (github.environment, github.policies, github.repo_variable, github.env_variable)
                )
                code, _, errors = run_cli(["apply"], github)
                self.assertEqual(code, 1)
                self.assertEqual(github.writes, [])
                self.assertEqual(
                    snapshot,
                    (
                        github.environment,
                        github.policies,
                        github.repo_variable,
                        github.env_variable,
                    ),
                )
                self.assertNotIn("raw-secret-marker", errors)

    def test_self_review_prevention_unrestricted_branches_and_extra_rules_conflict(self):
        for change in ("self_review", "unrestricted", "extra"):
            with self.subTest(change=change):
                github = GitHubCLI(prepared=True)
                if change == "self_review":
                    github.environment["protection_rules"][0]["prevent_self_review"] = True
                elif change == "unrestricted":
                    github.environment["deployment_branch_policy"] = None
                else:
                    github.environment["protection_rules"].append(
                        {"type": "wait_timer", "wait_timer": 5}
                    )
                code, _, _ = run_cli(["apply"], github)
                self.assertEqual(code, 1)
                self.assertEqual(github.writes, [])

    def test_partial_setup_remains_disabled_and_retry_completes_only_missing_resources(self):
        github = GitHubCLI()
        github.fail_once = ("POST", ENV + "/deployment-branch-policies")
        code, _, errors = run_cli(["apply"], github)
        self.assertEqual(code, 1)
        self.assertNotIn("raw-secret-marker", errors)
        self.assertEqual(github.repo_variable, "false")
        self.assertEqual(github.env_variable, "false")
        self.assertEqual(github.policies, [])
        github.writes.clear()
        code, report, errors = run_cli(["apply"], github)
        self.assertEqual(code, 0, errors)
        self.assertTrue(report["environment_prepared"])
        self.assertEqual(
            github.writes,
            [("POST", ENV + "/deployment-branch-policies", {"name": "main", "type": "branch"})],
        )

    def test_successful_response_without_persisted_settings_fails_verification(self):
        github = GitHubCLI()
        github.ignore_write = ENV + "/variables"
        code, _, errors = run_cli(["apply"], github)
        self.assertEqual(code, 1)
        self.assertIn("verification", errors)
        self.assertEqual(github.repo_variable, "false")

    def test_check_is_read_only_and_reports_prepared_separately_from_deployment_ready(self):
        github = GitHubCLI(prepared=True)
        github.secrets = [*SECRET_NAMES, "PRIVATE_OTHER_NAME"]
        github.repo_variable = "true"
        github.env_variable = "true"
        code, report, errors = run_cli(["check"], github)
        self.assertEqual(code, 0, errors)
        self.assertEqual(github.writes, [])
        self.assertTrue(report["environment_prepared"])
        self.assertTrue(report["manual_deploy_enabled"])
        self.assertTrue(report["auto_deploy_enabled"])
        self.assertFalse(report["deployment_ready"])
        self.assertEqual(report["secret_names"], {name: "present" for name in SECRET_NAMES})
        self.assertNotIn("PRIVATE_OTHER_NAME", json.dumps(report))

    def test_missing_environment_check_is_incomplete_without_creating_anything(self):
        github = GitHubCLI()
        code, report, errors = run_cli(["check"], github)
        self.assertEqual(code, 1, errors)
        self.assertFalse(report["environment_prepared"])
        self.assertFalse(report["deployment_ready"])
        self.assertEqual(github.writes, [])

    def test_secret_metadata_denied_does_not_claim_secret_or_ssh_readiness(self):
        github = GitHubCLI(prepared=True)
        github.overrides[("GET", ENV + "/secrets")] = (403, {"message": "raw-secret-marker"})
        code, report, errors = run_cli(["check"], github)
        self.assertEqual(code, 0, errors)
        self.assertEqual(report["secret_names"], {name: "unknown" for name in SECRET_NAMES})
        self.assertFalse(report["deployment_ready"])
        self.assertNotIn("raw-secret-marker", json.dumps(report) + errors)

    def test_missing_cli_auth_and_malformed_responses_have_only_safe_errors(self):
        failures = [
            FileNotFoundError("raw-secret-marker"),
            subprocess.TimeoutExpired(
                ["gh", "raw-secret-marker"],
                30,
                output="raw-secret-marker",
                stderr="raw-secret-marker",
            ),
            subprocess.CompletedProcess([], 1, "raw-secret-marker", "raw-secret-marker"),
            subprocess.CompletedProcess([], 0, "HTTP/2.0 200 OK\n\nraw-secret-marker", ""),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                external = failure if isinstance(failure, Exception) else lambda *a, **k: failure
                code, report, errors = run_cli(["apply"], external)
                self.assertEqual(code, 1)
                self.assertIsNone(report)
                self.assertNotIn("raw-secret-marker", errors)

    def test_malformed_metadata_is_rejected_without_mutations_or_raw_errors(self):
        malformed = [
            (REPO, {"permissions": ["raw-secret-marker"]}),
            ("user", {"login": "operator", "id": True, "type": "User"}),
            (
                REPO + "/collaborators/operator/permission",
                {"permission": ["raw-secret-marker"], "user": {"id": 7}},
            ),
            (
                ENV,
                {
                    **configured_environment(),
                    "protection_rules": [
                        *configured_environment()["protection_rules"],
                        {"type": ["raw-secret-marker"]},
                    ],
                },
            ),
            (ENV + "/deployment-branch-policies", {"total_count": 1, "branch_policies": []}),
        ]
        for endpoint, value in malformed:
            with self.subTest(endpoint=endpoint):
                github = GitHubCLI(prepared=True)
                github.overrides[("GET", endpoint)] = (200, value)
                code, _, errors = run_cli(["apply"], github)
                self.assertEqual(code, 1)
                self.assertEqual(github.writes, [])
                self.assertNotIn("raw-secret-marker", errors)

    def test_all_policy_pages_are_read_before_any_mutation(self):
        github = GitHubCLI(prepared=True)
        github.repo_variable = None
        original = github.__call__

        def paginated(command, **kwargs):
            if "/deployment-branch-policies?" in command[2]:
                page = int(command[2].rsplit("=", 1)[1])
                rules = (
                    [{"name": "main", "type": "branch"}]
                    if page == 1
                    else [{"name": "release/*", "type": "branch"}]
                )
                return github.response(command, 200, {"total_count": 2, "branch_policies": rules})
            return original(command, **kwargs)

        code, _, _ = run_cli(["apply"], paginated)
        self.assertEqual(code, 1)
        self.assertEqual(github.writes, [])

    def test_boolean_reviewer_id_cannot_match_a_numeric_user_identity(self):
        github = GitHubCLI(prepared=True)
        github.user["id"] = 1
        github.environment = configured_environment(True)
        code, _, _ = run_cli(["apply"], github)
        self.assertEqual(code, 1)
        self.assertEqual(github.writes, [])

    def test_every_partial_creation_can_be_retried_without_overwriting(self):
        stages = [
            ("POST", REPO + "/actions/variables"),
            ("PUT", ENV),
            ("POST", ENV + "/variables"),
            ("POST", ENV + "/deployment-branch-policies"),
        ]
        for stage in stages:
            with self.subTest(stage=stage):
                github = GitHubCLI()
                github.fail_once = stage
                code, _, errors = run_cli(["apply"], github)
                self.assertEqual(code, 1)
                self.assertNotIn("raw-secret-marker", errors)
                self.assertIn(github.repo_variable, (None, "false"))
                self.assertIn(github.env_variable, (None, "false"))
                code, report, errors = run_cli(["apply"], github)
                self.assertEqual(code, 0, errors)
                self.assertTrue(report["environment_prepared"])
                self.assertEqual(github.repo_variable, "false")
                self.assertEqual(github.env_variable, "false")

    def test_invalid_reviewer_is_rejected_without_invoking_gh(self):
        github = GitHubCLI()
        for login in ("--admin", "bad/path", "bad\nraw-secret-marker", "a" * 40):
            with self.subTest(login=login):
                code, _, errors = run_cli(["apply", "--reviewer=" + login], github)
                self.assertEqual(code, 1)
                self.assertEqual(github.calls, [])
                self.assertNotIn("raw-secret-marker", errors)


if __name__ == "__main__":
    unittest.main()
