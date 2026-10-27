# Verification record

Local implementation environment: Java 21, Node 22, TypeScript, Kotlin and Python.
GitHub connector access is working. Direct shell DNS access to GitHub/npm/Maven is unavailable.
Android SDK, Maven and Gradle are not installed locally; Android and Spring integration builds are delegated to the repository's CI, with results reported separately.

## Executed locally
- RED then GREEN: JourneyEngine executable checks (25 assertions).
- RED then GREEN: TypeScript favorites/search tests (6 tests).
- RED then GREEN: Kotlin commute-window checks (14 assertions).
- RED then GREEN: Python catalog validator (8 tests).
- TypeScript/TSX parser: 11 source files, no syntax errors at initial check (not a full type-check).
- Android XML and Maven POM parse, JSON configuration parse.

Commands:
```bash
bash tools/test-core.sh
python -m unittest discover -s tools -p 'test_catalog.py'
```

## CI definitions
- Full TypeScript type-check with installed React Native dependencies.
- Maven verification and PostgreSQL-backed API integration tests.
- Standalone Android preview APK build (demo configuration, no embedded secrets).

Defining CI does not mean it passed. Consult the actual run attached to the pull request.
No actual TOPIS API-key call, Firebase device delivery, physical GPS/geofence run or real train ride has been verified here.
