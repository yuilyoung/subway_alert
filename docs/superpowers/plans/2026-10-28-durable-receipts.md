# Durable TEST receipts implementation

Spec: `docs/superpowers/specs/2026-10-28-durable-receipts-design.md`.
Base: merged PR #5, `acee162c3fde75ed5966b3d95c42bf7fe3151549`.

## Global constraints

Preserve memory default and TEST-only behavior. No live cloud mutation, no private PDF publication, no production keys. Existing authentication and rate limits remain. Store hashes and receipts only; never persist FCM/API/session plaintext. Original expiry and cancel tombstones survive restart in postgres mode. Restart stops tracking; no resend. Single dedicated DB connection, one backend per database, bounded timeouts, fail closed after ambiguous storage failure. No database fallback. Default/sample/FCM-off Compose remains available.

## Task 1: Server durable receipts

Own `server/` changes. Add JDBC PostgreSQL 42.7.14; optional store bean selected by environment. Implement private receipt schema bootstrap (local development, not a Supabase migration), advisory lock, transactional restore/prune, receipt writes/deletes and sanitized failures. Integrate all MonitorService transitions and controller 503 handling, maintain lock ordering and keep FCM outside locks. Add unit tests first for restart cancellation, original expiry/replay, tombstones, failed writes blocking acknowledgments and pushes, unknown delivery after restart, and no live token restoration. Run Maven suite. Do not edit CI/deploy/mobile/docs or commit.

## Task 2: Mobile restored delivery state

Own mobile changes only. Accept delivery `UNKNOWN` in strict monitor response validation; render a clear Korean message saying the prior send result is unknown after restart. Add a meaningful parser regression test before production edit; run full npm test and Android export. No new automatic registration or retry behavior. Do not edit server/deploy/docs/CI or commit.

## Task 3: Reproducible PostgreSQL integration

Own deploy scripts, data/tests, compose.postgres.yaml, .env.example and CI workflow. Add optional local PostgreSQL 17-alpine Compose override with no database host port, persistent named volume, password required, health dependency, TEST/FCM-off backend. Extend exclusive private env generator with optional `--postgres` generated password. Add a packaged JAR integration script taking DB URL/user/password from environment and psql on PATH; it uses only a fresh dedicated test DB, no production DB. Verify restart recovery with unchanged ID/expiry/cancel tombstone, wrong capability, single backend lock rejection, durable database content contains only hashes/no FCM token, RLS/PUBLIC denial, and a storage outage fails closed. Add CI job with isolated PostgreSQL service to run the real script after Maven package. Tests must prevent accidental execution against a non-explicit test DB; never log secrets or DB URLs. Do not edit server/mobile/docs or commit.

## Task 4: Documentation, verification, review and delivery

Update README, architecture v1.4, deployment and focused durability runbook with memory/postgres/cloud distinctions and evidence. Run full local suites and actual PostgreSQL integration if local runtime can be provisioned; execute CI and review final diff. Publish a new feature branch and reviewable PR. The current user authorized merging PR #5; leave this new PR open for their next merge instruction.
