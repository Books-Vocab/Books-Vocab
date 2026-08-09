#!/usr/bin/env bash
# Regression: the iOS build gate must compile the scheme's test targets.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_TARGET_DIR="$ROOT/ios/BooksAndVocabTests"
BROKEN_FILE="$TEST_TARGET_DIR/kg_build_gate_probe_${PPID}_${RANDOM}.swift"
RED_LOG="$(mktemp "${TMPDIR:-/tmp}/kg-ios-build-gate-red.XXXXXX")"
GREEN_LOG="$(mktemp "${TMPDIR:-/tmp}/kg-ios-build-gate-green.XXXXXX")"

cleanup() {
  rm -f "$BROKEN_FILE" "$RED_LOG" "$GREEN_LOG"
}
trap cleanup EXIT

cat >"$BROKEN_FILE" <<'EOF'
import Foundation

let kgBuildGateProbe: MissingTypeForBuildGateProbe = 0
EOF

echo "[ios-build-gate-test] phase=red-control start file=$(basename "$BROKEN_FILE")"
red_rc=0
if "$ROOT/ops/ios_ops.sh" build >"$RED_LOG" 2>&1; then
  red_rc=0
else
  red_rc=$?
fi

if [[ "$red_rc" -eq 0 ]]; then
  echo "[ios-build-gate-test] FAIL: build gate accepted an invalid test target (rc=0)" >&2
  tail -80 "$RED_LOG" >&2 || true
  exit 1
fi
build_log="$(sed -n 's/.* log=\([^ ]*\) .*/\1/p' "$RED_LOG" | tail -1)"
if [[ -z "$build_log" || ! -f "$build_log" ]] || ! grep -Fq "$BROKEN_FILE" "$build_log"; then
  echo "[ios-build-gate-test] FAIL: red build did not identify the invalid test file" >&2
  tail -80 "$RED_LOG" >&2 || true
  if [[ -n "$build_log" && -f "$build_log" ]]; then
    tail -80 "$build_log" >&2 || true
  fi
  exit 1
fi
echo "[ios-build-gate-test] phase=red-control done rc=$red_rc"

rm -f "$BROKEN_FILE"
echo "[ios-build-gate-test] phase=green-control start"
green_rc=0
if "$ROOT/ops/ios_ops.sh" build >"$GREEN_LOG" 2>&1; then
  green_rc=0
else
  green_rc=$?
fi

if [[ "$green_rc" -ne 0 ]]; then
  echo "[ios-build-gate-test] FAIL: build gate rejected the restored test target (rc=$green_rc)" >&2
  tail -80 "$GREEN_LOG" >&2 || true
  exit 1
fi
echo "[ios-build-gate-test] phase=green-control done rc=0"
