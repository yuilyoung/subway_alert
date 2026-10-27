#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
javac -d "$OUT/java" server/src/main/java/com/subwayalert/core/JourneyEngine.java server/src/test/java/com/subwayalert/core/JourneyEngineChecks.java
java -cp "$OUT/java" com.subwayalert.core.JourneyEngineChecks
TSC=${TSC:-tsc}
"$TSC" --strict --target ES2022 --module commonjs --outDir "$OUT/ts" mobile/src/domain/favorites.ts
CORE_OUT="$OUT/ts" node --test mobile/tests/domain.test.cjs
if command -v kotlinc >/dev/null && [ -f mobile/android/app/src/main/java/com/subwayalert/CommuteWindow.kt ]; then
  kotlinc mobile/android/app/src/main/java/com/subwayalert/CommuteWindow.kt mobile/tests/CommuteWindowChecks.kt -include-runtime -d "$OUT/commute.jar"
  java -jar "$OUT/commute.jar"
fi
