#!/usr/bin/env bash
# ios_test.sh — run iOS unit tests with clean pass/fail output
#
# Usage:
#   ./ops/ios_test.sh                             # run ALL tests in BooksBrowserTests
#   ./ops/ios_test.sh testName1 testName2 ...     # run specific tests (method names)
#   ./ops/ios_test.sh -g "notebook"               # grep: run tests matching pattern
#
# Examples:
#   ./ops/ios_test.sh resolveNotebookId_emptyCandidate_returnsDefault
#   ./ops/ios_test.sh -g "sanitizeOutbox"
#   ./ops/ios_test.sh -g "triggerPipelines"
#
# Shares the same shlock + DerivedData as ios_build.sh for incremental builds.

set -euo pipefail

LOCK_FILE="/tmp/kg-ios-build.lock"
TIMEOUT=600
POLL_INTERVAL=3
GREP_PATTERN=""
SPECIFIC_TESTS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -g|--grep) GREP_PATTERN="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    *) SPECIFIC_TESTS+=("$1"); shift ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XCODEPROJ="$PROJECT_ROOT/ios/BooksBrowser.xcodeproj"

[[ -d "$XCODEPROJ" ]] || { echo "error: $XCODEPROJ not found" >&2; exit 1; }

CALLER="${WORKTREE_BRANCH:-$(git -C "$PROJECT_ROOT" branch --show-current 2>/dev/null || echo 'unknown')}"

# --- Build -only-testing flags ---
ONLY_FLAGS=()

if [[ -n "$GREP_PATTERN" ]]; then
  # Auto-discover test method names matching the pattern from the test file
  TEST_FILE="$PROJECT_ROOT/ios/BooksBrowserTests/BooksBrowserTests.swift"
  if [[ -f "$TEST_FILE" ]]; then
    while IFS= read -r name; do
      ONLY_FLAGS+=("-only-testing:BooksBrowserTests/BooksBrowserTests/$name")
    done < <(grep -oE '@Test.*func ([a-zA-Z0-9_]+)' "$TEST_FILE" \
             | sed 's/@Test.*func //' \
             | grep -i "$GREP_PATTERN")
  fi
  if [[ ${#ONLY_FLAGS[@]} -eq 0 ]]; then
    echo "[ios_test] no tests matching pattern '$GREP_PATTERN'" >&2
    exit 1
  fi
  echo "[ios_test] matched ${#ONLY_FLAGS[@]} tests for pattern '$GREP_PATTERN'"
elif [[ ${#SPECIFIC_TESTS[@]} -gt 0 ]]; then
  for t in "${SPECIFIC_TESTS[@]}"; do
    ONLY_FLAGS+=("-only-testing:BooksBrowserTests/BooksBrowserTests/$t")
  done
fi

# --- Lock acquire (shared with ios_build.sh) ---
cleanup() { rm -f "$LOCK_FILE"; }

echo "[ios_test] caller=$CALLER waiting for lock..."
WAITED=0
while ! shlock -f "$LOCK_FILE" -p $$; do
  HOLDER_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
  if [[ -n "$HOLDER_PID" ]] && ! kill -0 "$HOLDER_PID" 2>/dev/null; then
    echo "[ios_test] stale lock (pid=$HOLDER_PID dead), stealing"
    rm -f "$LOCK_FILE"
    continue
  fi
  sleep "$POLL_INTERVAL"
  WAITED=$((WAITED + POLL_INTERVAL))
  if [[ $WAITED -ge $TIMEOUT ]]; then
    echo "[ios_test] error: timed out after ${TIMEOUT}s waiting for lock" >&2
    exit 1
  fi
done
trap cleanup EXIT

echo "[ios_test] lock acquired — running ${#ONLY_FLAGS[@]:-all} tests..."
START=$(date +%s)

# Run xcodebuild test, capture output to parse results
TMPOUT=$(mktemp)
set +e
xcodebuild test \
  -project "$XCODEPROJ" \
  -scheme BooksBrowser \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  "${ONLY_FLAGS[@]}" \
  2>&1 | tee "$TMPOUT" | grep -E '^(Test |✓|✗|◇|Passing|Failing|Executed|\*\* TEST)' || true
EXIT_CODE=${PIPESTATUS[0]}
set -e

ELAPSED=$(( $(date +%s) - START ))

# Extract summary from xcresult if available
if grep -q '^\*\* TEST SUCCEEDED' "$TMPOUT" 2>/dev/null; then
  echo ""
  echo "[ios_test] ✓ all tests passed (${ELAPSED}s) — $CALLER"
elif grep -q '^\*\* TEST FAILED' "$TMPOUT" 2>/dev/null; then
  echo ""
  # Show failing test details
  grep -E 'error:|failed' "$TMPOUT" | grep -v 'xcodebuild\|Linker\|frontend' | head -20
  echo ""
  echo "[ios_test] ✗ tests failed (${ELAPSED}s) — $CALLER" >&2
else
  echo ""
  # Show last 10 lines for unexpected output
  tail -10 "$TMPOUT"
  echo "[ios_test] ? inconclusive (exit=$EXIT_CODE, ${ELAPSED}s) — $CALLER" >&2
fi

rm -f "$TMPOUT"
exit $EXIT_CODE
