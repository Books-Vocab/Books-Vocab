#!/usr/bin/env bash
# ios_test.sh — run iOS unit tests with clean pass/fail output
#
# Usage:
#   ./ops/ios_test.sh                             # run ALL tests in BooksBrowserTests
#   ./ops/ios_test.sh testName1 testName2 ...     # run specific tests (method names)
#   ./ops/ios_test.sh -g "notebook"               # grep: run tests matching pattern
#   ./ops/ios_test.sh --file BooksBrowserTests.swift
#   ./ops/ios_test.sh --ui testLaunchShowsPrimaryTabs
#   ./ops/ios_test.sh --all-targets               # run scheme test action, including UI tests
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
TEST_FILE=""
TEST_SCOPE="unit"
SPECIFIC_TESTS=()
LIST_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -g|--grep) GREP_PATTERN="$2"; shift 2 ;;
    --file) TEST_FILE="$2"; shift 2 ;;
    --unit) TEST_SCOPE="unit"; shift ;;
    --ui) TEST_SCOPE="ui"; shift ;;
    --all-targets|--scheme) TEST_SCOPE="all"; shift ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --list) LIST_ONLY=1; shift ;;   # dry-run: print resolved -only-testing flags, no xcodebuild
    *) SPECIFIC_TESTS+=("$1"); shift ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XCODEPROJ="$PROJECT_ROOT/ios/BooksBrowser.xcodeproj"

# shellcheck source=lib/ios_test_discovery.sh
source "$SCRIPT_DIR/lib/ios_test_discovery.sh"

[[ -d "$XCODEPROJ" ]] || { echo "error: $XCODEPROJ not found" >&2; exit 1; }

CALLER="${WORKTREE_BRANCH:-$(git -C "$PROJECT_ROOT" branch --show-current 2>/dev/null || echo 'unknown')}"

# --- Build -only-testing flags ---
ONLY_FLAGS=()
TEST_TARGET="BooksBrowserTests"
TEST_DIR="$PROJECT_ROOT/ios/BooksBrowserTests"

case "$TEST_SCOPE" in
  unit)
    TEST_TARGET="BooksBrowserTests"
    TEST_DIR="$PROJECT_ROOT/ios/BooksBrowserTests"
    ;;
  ui)
    TEST_TARGET="BooksBrowserUITests"
    TEST_DIR="$PROJECT_ROOT/ios/BooksBrowserUITests"
    ;;
  all)
    TEST_TARGET=""
    ;;
  *)
    echo "[ios_test] internal error: unknown test scope '$TEST_SCOPE'" >&2
    exit 2
    ;;
esac

if [[ -n "$GREP_PATTERN" && -n "$TEST_FILE" ]]; then
  echo "[ios_test] error: --file and --grep cannot be combined" >&2
  exit 1
fi

if [[ "$TEST_SCOPE" == "all" && ( -n "$GREP_PATTERN" || -n "$TEST_FILE" || ${#SPECIFIC_TESTS[@]} -gt 0 ) ]]; then
  echo "[ios_test] error: --all-targets cannot be combined with --file, --grep, or specific tests" >&2
  exit 1
fi

if [[ -n "$TEST_FILE" ]]; then
  if [[ "$TEST_FILE" = /* ]]; then
    FILE_PATH="$TEST_FILE"
  elif [[ "$TEST_FILE" == */* ]]; then
    FILE_PATH="$PROJECT_ROOT/$TEST_FILE"
  else
    FILE_PATH="$TEST_DIR/$TEST_FILE"
  fi
  [[ -f "$FILE_PATH" ]] || { echo "[ios_test] test file not found: $TEST_FILE" >&2; exit 1; }
  while IFS= read -r flag; do
    [[ -n "$flag" ]] && ONLY_FLAGS+=("$flag")
  done < <(discover_file_only_flags "$FILE_PATH" "" "$TEST_TARGET")
  if [[ ${#ONLY_FLAGS[@]} -eq 0 ]]; then
    echo "[ios_test] no tests discovered in file '$TEST_FILE'" >&2
    exit 1
  fi
  echo "[ios_test] matched ${#ONLY_FLAGS[@]} tests in file '$TEST_FILE' ($TEST_TARGET)"
elif [[ -n "$GREP_PATTERN" ]]; then
  # Auto-discover test funcs matching the pattern, attributing each func to its
  # OWN enclosing top-level container (struct / @Suite struct / class). See
  # lib/ios_test_discovery.sh for the discovery contract.
  while IFS= read -r flag; do
    [[ -n "$flag" ]] && ONLY_FLAGS+=("$flag")
  done < <(discover_only_flags "$TEST_DIR" "$GREP_PATTERN" "$TEST_TARGET")
  if [[ ${#ONLY_FLAGS[@]} -eq 0 ]]; then
    echo "[ios_test] no tests matching pattern '$GREP_PATTERN'" >&2
    exit 1
  fi
  echo "[ios_test] matched ${#ONLY_FLAGS[@]} tests for pattern '$GREP_PATTERN' ($TEST_TARGET)"
elif [[ ${#SPECIFIC_TESTS[@]} -gt 0 ]]; then
  for t in "${SPECIFIC_TESTS[@]}"; do
    if [[ "$t" == */* ]]; then
      ONLY_FLAGS+=("-only-testing:$TEST_TARGET/$t")
    else
      ONLY_FLAGS+=("-only-testing:$TEST_TARGET/$TEST_TARGET/$t")
    fi
  done
elif [[ "$TEST_SCOPE" != "all" ]]; then
  ONLY_FLAGS+=("-only-testing:$TEST_TARGET")
fi

# Dry-run: print resolved flags and exit before touching the lock / xcodebuild.
if [[ "$LIST_ONLY" -eq 1 ]]; then
  if [[ ${#ONLY_FLAGS[@]} -eq 0 ]]; then
    echo "[ios_test] (no -only-testing flags — would run ALL tests)"
  else
    printf '%s\n' "${ONLY_FLAGS[@]}"
  fi
  exit 0
fi

# --- Lock acquire (shared with ios_build.sh) ---
TMPOUT=""
PRESERVE_TMPOUT=0
cleanup() {
  rm -f "$LOCK_FILE"
  if [[ "$PRESERVE_TMPOUT" -eq 0 ]]; then
    rm -f "${TMPOUT:-}"
  fi
}

echo "[ios_test] caller=$CALLER waiting for lock..."
WAITED=0
while ! shlock -f "$LOCK_FILE" -p $$; do
  HOLDER_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
  if [[ -n "$HOLDER_PID" ]] && ! kill -0 "$HOLDER_PID" 2>/dev/null; then
    # Re-check the lock still holds the SAME dead PID before stealing — another
    # waiter may have acquired it fresh between our cat and rm (steal only our
    # observed dead lock, never a live one).
    if [[ "$(cat "$LOCK_FILE" 2>/dev/null || echo "")" == "$HOLDER_PID" ]]; then
      echo "[ios_test] stale lock (pid=$HOLDER_PID dead), stealing"
      rm -f "$LOCK_FILE"
    fi
    continue
  fi
  sleep "$POLL_INTERVAL"
  WAITED=$((WAITED + POLL_INTERVAL))
  if [[ $WAITED -ge $TIMEOUT ]]; then
    echo "[ios_test] error: timed out after ${TIMEOUT}s waiting for lock" >&2
    exit 1
  fi
done
trap cleanup EXIT INT TERM

echo "[ios_test] lock acquired — scope=$TEST_SCOPE running ${#ONLY_FLAGS[@]} selector(s) (0=scheme all targets)..."
START=$(date +%s)

is_build_db_lock_failure() {
  grep -qE 'build\.db.*database is locked|unable to attach DB' "$TMPOUT" 2>/dev/null
}

# Run xcodebuild test, capture output to parse results. Xcode can keep the
# shared DerivedData build database locked briefly after the previous simulator
# test process exits, so retry that infrastructure failure before surfacing it.
MAX_BUILD_DB_LOCK_RETRIES=3
ATTEMPT=1
EXIT_CODE=0
while :; do
  [[ -n "$TMPOUT" ]] && rm -f "$TMPOUT"
  TMPOUT=$(mktemp)
  set +e
  xcodebuild test \
    -project "$XCODEPROJ" \
    -scheme BooksBrowser \
    -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
    -parallel-testing-enabled NO \
    -test-timeouts-enabled YES \
    -default-test-execution-time-allowance 60 \
    -maximum-test-execution-time-allowance 120 \
    ${ONLY_FLAGS[@]+"${ONLY_FLAGS[@]}"} \
    2>&1 | tee "$TMPOUT" | grep -E '^(Test |[[:space:]]*[✔✘✓✗] Test |◇|Passing|Failing|Executed|\*\* TEST)' || true
  EXIT_CODE=${PIPESTATUS[0]}
  set -e

  if is_build_db_lock_failure && [[ "$ATTEMPT" -le "$MAX_BUILD_DB_LOCK_RETRIES" ]]; then
    echo "[ios_test] build database locked; retrying xcodebuild attempt $((ATTEMPT + 1))/$((MAX_BUILD_DB_LOCK_RETRIES + 1)) after 10s" >&2
    sleep 10
    ATTEMPT=$((ATTEMPT + 1))
    continue
  fi
  break
done

ELAPSED=$(( $(date +%s) - START ))

# Count tests xcodebuild actually executed, so a SUCCEEDED with zero tests run
# (bogus -only-testing IDs → "TEST SUCCEEDED" but nothing executed) is caught as
# a false green instead of being reported as a pass. Sums both reporters:
#   XCTest:        "Executed N tests, ..."   (one line per suite)
#   Swift Testing: "✔ Test ... passed" / "✘ Test ... failed" per-test ticks,
#                  Xcode 26 "Test case 'Suite/test()' passed" lines,
#                  and "Test run with N test(s)" summary.
count_executed_tests() {
  local n xc st xc26
  # XCTest: sum the per-suite "Executed N tests" counts.
  xc=$(grep -oE 'Executed [0-9]+ test' "$TMPOUT" 2>/dev/null \
       | grep -oE '[0-9]+' | awk '{s+=$1} END{print s+0}')
  xc=${xc:-0}
  # Swift Testing: count per-test pass/fail ticks (grep -c always prints one int).
  st=$(grep -cE '^[[:space:]]*[✔✘✓✗] Test .+ (passed|failed)' "$TMPOUT" 2>/dev/null)
  st=${st:-0}
  # Xcode 26 Swift Testing console output uses XCTest-style per-case rows.
  xc26=$(grep -cE "^Test case '.+' (passed|failed)" "$TMPOUT" 2>/dev/null)
  xc26=${xc26:-0}
  n=$(( xc + st + xc26 ))
  # Fallback: Swift Testing summary line "Test run with N test(s)".
  if [[ "$n" -eq 0 ]]; then
    n=$(grep -oE 'Test run with [0-9]+ test' "$TMPOUT" 2>/dev/null \
        | grep -oE '[0-9]+' | head -1)
    n=${n:-0}
  fi
  echo "$n"
}

# Machine-readable verdict file — survives even when stdout/stderr is piped
# (e.g. `ios_test.sh | tail`, where the pipeline's exit code is tail's, not the
# script's). Read this instead of trusting a piped `$?`.
VERDICT_FILE="${TMPDIR:-/tmp}/kg_ios_test_verdict"

# Extract summary from xcresult if available
if grep -q '^\*\* TEST SUCCEEDED' "$TMPOUT" 2>/dev/null; then
  EXECUTED=$(count_executed_tests)
  if [[ "$EXECUTED" -eq 0 ]]; then
    echo ""
    echo "[ios_test] ✗ FALSE GREEN: xcodebuild reported TEST SUCCEEDED but 0 tests executed" >&2
    echo "[ios_test]   (likely a stale/bogus -only-testing test ID matched nothing) — $CALLER" >&2
    echo "RESULT=fail reason=false-green-0-executed caller=$CALLER" > "$VERDICT_FILE"
    rm -f "$TMPOUT"
    exit 1
  fi
  echo ""
  echo "RESULT=ok executed=$EXECUTED caller=$CALLER elapsed=${ELAPSED}s" > "$VERDICT_FILE"
  echo "[ios_test] ✓ all tests passed ($EXECUTED executed, ${ELAPSED}s) — $CALLER  (verdict: $VERDICT_FILE)"
elif grep -q '^\*\* TEST FAILED' "$TMPOUT" 2>/dev/null; then
  echo ""
  # Show failing test details
  grep -E 'error:|failed' "$TMPOUT" | grep -v 'xcodebuild\|Linker\|frontend' | head -20
  echo ""
  PRESERVE_TMPOUT=1
  echo "RESULT=fail reason=tests-failed caller=$CALLER elapsed=${ELAPSED}s" > "$VERDICT_FILE"
  echo "[ios_test] ✗ tests failed (${ELAPSED}s) — $CALLER  (verdict: $VERDICT_FILE)" >&2
  echo "[ios_test] full log preserved: $TMPOUT" >&2
  EXIT_CODE=1
else
  echo ""
  # Show last 10 lines for unexpected output
  tail -10 "$TMPOUT"
  PRESERVE_TMPOUT=1
  echo "RESULT=inconclusive EXIT=$EXIT_CODE caller=$CALLER elapsed=${ELAPSED}s" > "$VERDICT_FILE"
  echo "[ios_test] ? inconclusive (exit=$EXIT_CODE, ${ELAPSED}s) — $CALLER  (verdict: $VERDICT_FILE)" >&2
  echo "[ios_test] full log preserved: $TMPOUT" >&2
  EXIT_CODE=1
fi

if [[ "$PRESERVE_TMPOUT" -eq 0 ]]; then
  rm -f "$TMPOUT"
fi
exit $EXIT_CODE
