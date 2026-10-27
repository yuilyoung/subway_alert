# Live train test build

Goal: prepare an Android test build with explicit train selection and a server-side Seoul API integration, without claiming production readiness.

Architecture: keep the existing Expo and Spring projects. The server owns the upstream credential and only sends it over HTTPS; official public sample may use HTTP solely with the literal `sample` key. Parse and validate provider responses; do not infer train identity, route or alert time from incomplete or stale data. Android displays provider mode, available rows and transport errors, with explicit selection. Existing demo remains distinguishable. Use unit/integration tests with fixtures and a real public sample when available. Build a debug APK if the toolchain can be installed.

Tasks: (1) server provider, input validation, mode, tests; (2) Android live train browsing and explicit selection, server settings, tests; (3) APK build and verification; (4) review and documentation. Unavailable actual keys, TLS, push delivery, verified route data, and device testing remain explicit.
