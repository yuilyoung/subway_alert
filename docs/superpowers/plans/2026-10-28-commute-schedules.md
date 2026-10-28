# Editable Commute Schedules Implementation Plan

> **For agentic workers:** Use subagent-driven-development with exclusive file ownership. Steps below are test-first.

**Goal:** Edit favorite weekdays/times and suppress stale/duplicate overnight commute suggestions.
**Architecture:** Pure schedule and favorite logic, an injected serialized suggestion coordinator, then the existing Expo screen/background adapter.
**Tech Stack:** Expo54, React19.1, React Native0.81.5, CommonJS domain modules, Node test runner; no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-28-commute-schedules-design.md

## Global Constraints

Keep maximum5, existing IDs and enabled states, local device time, existing 5 demo stations and TEST-only server behavior. No native/cloud configuration, no PR6/main merge, no private PDF upload. New branch starts96d5147; PR targets feat/durable-monitor-receipts until PR6 is merged. Existing storage keys stay compatible.

## Review Focus

- An overnight Sunday schedule must remain Sunday's occurrence after midnight Monday.
- Editing a disabled favorite at capacity5 must keep its ID/disabled status and every other record.
- An already-consumed first candidate must not block another eligible favorite.
- Async edit/delete/stop or stale location during marker I/O must suppress the obsolete notification.
- Overlapping JS callbacks and storage/notification failures must not duplicate a window's request.

### Task 1: Schedule and favorite domain

Own mobile/src/commute.js (new), mobile/src/domain.js, mobile/test/commute.test.js (new), mobile/test/domain.test.js only.

Interfaces: commute.js exports normalizeSchedule(schedule) -> {days,start,end} or Korean Error, scheduleOccurrence(schedule,date) -> string|null, formatSchedule(schedule) -> Korean label. Days are unique integer0..6 canonical Monday-first[1,2,3,4,5,6,0], nonempty; reject duplicate/out-of-range/noninteger input and invalid dates/times. Occurrence string is YYYY-MM-DD|HH:MM|HH:MM using local start date (previous date for early part of overnight window). formatSchedule returns '시간 조건 확인 필요' for invalid schedules, otherwise e.g '월·수·금 07:00–09:00'.

domain.js keeps all existing APIs; matchesSchedule delegates to scheduleOccurrence != null. Add saveFavorite(favorites,draft,editingId=null): validate distinct nonempty from/to and schedule; new draft.id required and unique, new enabled defaults true; editing preserves original id/enabled and unrelated fields while replacing from/to/schedule, rejects missing editingId and duplicate other routes; max5 additions only, edit at5 allowed. Never mutate inputs.

- [ ] Write failing tests for schedule validation, boundaries/overnight/invalidDate and label; observe RED.
- [ ] Implement minimal functions and meaningful saveFavorite preservation/conflict tests; observe RED then GREEN.
- [ ] Run full npm test; write report .superpowers/sdd/commute-schedules/task-1-report.md. No commits; no other files.

### Task 2: Safe background suggestions

Own mobile/src/commuteSuggestions.js (new), mobile/src/background.js, mobile/test/commuteSuggestions.test.js (new) only.

Interface: createCommuteSuggester({store,storage,stations,notify,now=()=>new Date()}) -> async suggest(point), boolean result. store.readState/readConfig as existing, storage.getItem/setItem, notify(title,body) are injected boundaries. point has latitude/longitude/accuracy/timestamp. Import scheduleOccurrence/normalizeSchedule from Task1 commute.js and findRoute/distanceMeters from domain.js. Reuse suggestionKey from storage.js. Background adapter creates one module-level coordinator and delegates the !active && automation branch. Do not change active-trip progress or native permission handling.

- [ ] Tests first: same overnight window once, new next occurrence allowed, already-claimed first favorite does not starve next, disabled/invalid/active/automation-off/stale/inaccurate point rejected.
- [ ] Serialize with a promise queue in one JS runtime; iterate eligible favorites, validate known distinct demo route, use occurrence key, accept legacy date-only marker matching current/start local day.
- [ ] Re-read config and clock/point before claiming and again before notifying; same ID, enabled, route and normalized full schedule must still match. Write marker before notify. On write failure no notify, on notify failure retain marker; reject/rethrow failure rather than pretend success. At most one notify per location event.
- [ ] Test async edits/deletion/stop/new active/time expiry/stale queued location, overlap, marker failure and notification failure. Run full npm test once Task1 exists. Write task-2-report.md. No commits.

### Task 3: Screen, docs and delivery

Root owns mobile/App.js and any focused editor component/helpers/tests not owned above, README/mobileREADME/architecture and focused commute guide/verification. Show weekday controls, actual labels, edit/cancel/save; edits use latest stored state and preserve enabled/ID, default new records weekday7–9. Editor draft must not change monitoring before save; remove draft after save/cancel/delete. Run full tests, Android export, Python, link/diff checks and independent final review. Publish branch and stacked PR targeting PR6 branch with base dependency clear. Observe CI and report tested/untested functions.
