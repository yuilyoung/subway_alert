# Subway Alert — implementation specification

## Requested basis
The attached **지하철 하차알림 앱 - 설계 문서 v1.0 (2026-10-27)** has 13 pages.
The original repository at `0f9d41bb91e34ebd3e0a2f7cf3a49f2e122d028e` contained only README.md.
This is an implementation of that design plus the user's explicit extensions, not a claim that the PDF already specifies those extensions.

## Preserve from the PDF
- Android 7.0/API 24 minimum; React Native UI and Kotlin native integration (pp. 1, 3, 11).
- Spring Boot/Java 21 server, PostgreSQL/Flyway, Firebase FCM (pp. 3–8).
- Server polls active TOPIS lines every 10 seconds, sharing each line's result (pp. 3–5).
- Manual origin/destination/direction selection, cancellation, tracking status, heads-up notification with vibration (pp. 3, 10).
- A user confirms boarding; automatic identification of a train is not established by the PDF (p. 13).

## User extensions
- Search new stations by name; save at most five origin/destination favorites.
- Enable an opt-in weekday/time-window/near-origin commute rule for a favorite.
- Show origin and destination facilities: transfer car/door, toilets, amenities, gates and exits.
- GPS/geofences assist with origin proximity; realtime API identifies train progress.

## Explicit engineering decisions / departures
1. PDF p. 5 matches any train on a line. Implementation binds to a specific train number, direction and line after a boarding confirmation. Express trains and unverifiable terminal routes are rejected rather than guessed.
2. PDF pp. 6 and 13 give inconsistent fixed-time station extrapolation rules. Implementation **does not fabricate station progress from age**: stale/future/out-of-order observations are rejected and freshness is shown.
3. FCM registration tokens are delivery addresses, not authentication. Live API uses Firebase ID-token authentication and checks ownership for each session. Demo identity is accepted only in the explicit demo profile.
4. Kotlin renders incoming data-message notifications immediately. This replaces the PDF's Notifee/JS rendering example while keeping the same server/FCM architecture. No full-screen intent or Do-Not-Disturb bypass is requested.
5. Commute geofences start a WAITING_BOARDING session and show a boarding prompt. They cannot prove which train a rider is on. The app must not label this as fully automatic boarding detection.
6. First increment supports verified, same-line ordinary-train paths. Transfer guidance is station information; multi-train transfer journeys are not implemented.
7. An explicit synthetic demo catalog is separate from live data. Unknown facilities are shown as unavailable, not invented. A validated catalog importer accepts real stations, directed connections, TOPIS identifiers and source-stamped facilities.
8. SQL uses a private schema and denies client roles; no Supabase service key is shipped to the app. Server uses JDBC rather than JPA to make leases/idempotency explicit.
9. FCM acceptance is not proof of handset delivery. Outbox retries use a stable event ID; the native client deduplicates and rejects cancelled/expired session messages.

## Deliverable / verification boundaries
A branch and reviewable PR containing mobile/server sources, schema, demo fixture, tests, CI and setup instructions. No production deployment, paid resource creation, release signing, secret fabrication or claim of real-train verification.
Actual route data, TOPIS key, Firebase configuration, live DB credentials and device/railway tests remain setup or acceptance requirements.
