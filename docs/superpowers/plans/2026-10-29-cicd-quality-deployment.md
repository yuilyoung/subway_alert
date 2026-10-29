# CI Quality and Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Add enforceable static analysis, tested immutable deployment artifacts and opt-in staging CD.

**Architecture:** Keep existing CI tests, add independent static jobs and an aggregate gate. Package the exact tested backend image; manually promote only successful main CI runs over pinned SSH, validate and roll back failures.

**Tech Stack:** GitHub Actions, ESLint, Prettier, Spotless, PMD, Ruff, actionlint, Docker Compose, Python 3.

**Spec:** docs/superpowers/specs/2026-10-29-cicd-quality-deployment-design.md

## Global Constraints

- Java 17 and Expo 54 remain unchanged. Preserve application behavior.
- No paid resources, public tunnels, real API calls or production deployment.
- No secrets in Git, bundles, command output or test reports.
- Do not merge existing PR #6/#7; develop on feat/cicd-quality-deployment.
- Preserve source SHA, CI run ID and image identity through deployment.

## Review Focus

- Formatting and static checks must reject deliberate invalid inputs.
- Failed/cancelled/skipped prerequisites must fail the aggregate gate.
- Tampered, wrong-source or untrusted-run artifacts must be rejected.
- Failed deployments must preserve and check a previous working image.
- Liveness alone must not accept failed monitor storage as ready.

### Task 1: Mobile static quality

**Files:** mobile/package.json, mobile/package-lock.json, mobile/eslint.config.*, mobile/.prettier*, mobile JavaScript/JSON files.

**Interfaces:** `npm run lint`, `npm run format:check`, `npm run format`.

- [ ] Install pinned compatible tooling; configure JS, JSX, Node tests and app config accurately.
- [ ] Run failing checks on current tree or deliberate temporary fixtures; retain evidence.
- [ ] Apply formatting and fix legitimate lint findings without changing behavior.
- [ ] Run lint, format check and npm test; report exact results.

### Task 2: Server static quality

**Files:** server/pom.xml, server/config/*, server/src/**/*.java.

**Interfaces:** `mvn verify` must include formatter and lint checks; `mvn spotless:apply` fixes formatting.

- [ ] Add pinned Java 17 compatible Spotless/PMD tooling and useful explicit lint rules.
- [ ] Observe current formatting or temporary bad-code checks fail.
- [ ] Format existing sources and fix actual violations without broad suppressions.
- [ ] Run Maven verify and standalone engine check; report results.

### Task 3: Verified image bundle and deployment tool

**Files:** deploy/release.py, deploy/compose.staging.yaml, deploy/smoke_compose.py, data/tests/test_release.py, data/tests/test_compose_smoke.py.

**Interfaces:** CLI build/verify bundle, deploy on host and rollback; document exact CLI for workflow integration in task report.

- [ ] Write failing behavioral tests for manifest integrity, source mismatch, invalid image identity, failed readiness and rollback.
- [ ] Allow smoke_compose to test an existing immutable image without rebuilding/removing it; preserve default isolation.
- [ ] Implement strict bundle validation, staging SAMPLE-only Compose and single-host deployment with readiness and rollback.
- [ ] Run all Python tests; report real vs mocked Docker evidence.

### Task 4: CI/CD workflow, Python quality and documentation

**Files:** .github/workflows/ci.yml, .github/workflows/cd.yml, pyproject.toml, requirements-quality.txt, docs/cicd.md, README.md, docs/architecture.md, docs/deployment.md.

**Interfaces:** Consumes Task 1/2 check commands and Task 3 bundle/deploy CLI.

- [ ] Add Ruff and actionlint; verify deliberate lint/format failure and fix existing Python findings.
- [ ] Wire static checks, preserved JAR/test reports, tested deployment bundle and aggregate CI gate.
- [ ] Add main-only successful-run promotion validation, staging environment and pinned SSH manual CD.
- [ ] Document exact environment/secret/admin setup and unconfigured external prerequisites.
- [ ] Run local available checks, fresh independent review, publish branch/PR and inspect real CI including artifacts.
