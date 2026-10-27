# Subway Alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement an Android subway exit-alert MVP in the connected repository.
**Architecture:** React Native UI, native Kotlin FCM/geofences, Spring Boot tracking, PostgreSQL outbox. A separate demo profile exercises the flow without private credentials.
**Tech Stack:** React Native, TypeScript, Kotlin, Java 21, Spring Boot, PostgreSQL 16, Firebase.
**Spec:** `docs/superpowers/specs/2026-10-27-subway-alert.md`

## Global Constraints
- Android API 24+, at most five favorites, pre-destination departure alert.
- Only the explicitly confirmed train can advance a session.
- No synthetic data in live mode; no API secrets committed.
- Work on `feat/android-subway-alert-mvp`, preserve main, do not merge automatically.

## Review Focus
- Wrong train/direction, stale timestamps, backwards movement and repeated observations.
- Midnight commute windows and duplicate geofence callbacks.
- Permission refusal, app restart and old notifications after cancellation.
- Retried creation, other-user access, outbox retries and bounded lifetime.
- Missing facilities, invalid catalog graphs, unknown express/terminal information.

## Task 1: Deterministic domain and favorites
Files: `server/src/main/java/com/subwayalert/core/JourneyEngine.java`, matching executable core tests, `mobile/src/domain/favorites.ts`, `mobile/tests/domain.test.cjs`.
- [ ] Write tests for train identity/freshness/route progression and five-favorite invariants.
- [ ] Observe failures before implementation.
- [ ] Implement immutable evaluation and validated favorite mutations.
- [ ] Run `bash tools/test-core.sh` with Java and TypeScript.

## Task 2: Server and persistence
Files: server application, catalog, tracking service, TOPIS gateway, Firebase gateway, API, SQL migrations and integration tests.
Consumes: JourneyEngine input/decision records; produces `/api` JSON contract.
- [ ] Add ownership/idempotency and demo integration tests.
- [ ] Implement explicit demo/live configuration, persisted sessions, line cache, outbox and expiry.
- [ ] Run Maven/DB tests where dependencies and PostgreSQL are available; record unavailable checks.

## Task 3: Android bridge and commute rules
Files: native TurboModule spec, Kotlin notification service, geofence receiver/worker, preference store and Android build files.
Consumes: `/api` contract and favorite JSON; produces native identity/storage/notification/geofence calls.
- [ ] Test overnight/day-boundary commute eligibility and duplicate prevention.
- [ ] Implement foreground permission setup, native FCM rendering and geofence-to-WAITING_BOARDING flow.
- [ ] Compile with Android SDK in CI; do not substitute static inspection for a device test.

## Task 4: React Native app
Files: `mobile/App.tsx`, API client, types, theme/components and configuration.
Consumes: native bridge and `/api`; produces route, favorites, facilities, tracking and settings screens.
- [ ] Implement selectable station search, boarding confirmation, status, cancel and persisted settings.
- [ ] Add permission guidance, empty/error states and visibly separate demo mode.
- [ ] Type-check and build Android in CI.

## Task 5: Delivery and review
Files: CI workflow, compose, importer, README, verification report.
- [ ] Run full available tests, inspect secrets and review failure modes.
- [ ] Publish source to the feature branch and verify remote contents.
- [ ] Open a PR with honest test/build status and remaining acceptance criteria.
