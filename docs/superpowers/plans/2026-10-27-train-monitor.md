# Train monitor and notification integration

Goal: connect an explicitly selected train to server monitoring and Android notification delivery, with safe simulation and an operator-controlled gate for unverified live data.

Constraints: The public Seoul sample covers only five rows. User-submitted route/timezone validation is never trusted. Actual service mode is disabled until an operator supplies validated route and provider semantics; credentials stay on the server. Firebase and Seoul credentials are not available here. FCM acceptance does not prove device display. Test data and real train alerts must remain clearly separated.

Architecture: short-lived server sessions own random access tokens; polling retrieves the line once per tick and matches train/direction/station/freshness; session state and push delivery are separate, with failures exposed. Android obtains a native FCM device token when configured, creates a session with selected train and route, and displays its status/cancellation. Local fake provider and fake push test the full flow without external accounts. Protect secrets and do not turn on production flags automatically. All in-memory state is marked non-production; restart recovery is unfinished.
