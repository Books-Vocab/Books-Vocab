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
CURRENT_XCODE_PID=""
RESULT_DIR=""
RESULT_BUNDLE=""
cleanup() {
  if [[ -n "${CURRENT_XCODE_PID:-}" ]] && kill -0 "$CURRENT_XCODE_PID" 2>/dev/null; then
    kill "$CURRENT_XCODE_PID" 2>/dev/null || true
  fi
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

emit_new_test_output() {
  local from_line="$1" to_line="$2"
  [[ "$to_line" -ge "$from_line" ]] || return 0
  sed -n "${from_line},${to_line}p" "$TMPOUT" \
    | grep -E "^(\*\* TEST|Test Suite '.+' (started|passed|failed)|Test Case '.+' (started|passed|failed|skipped)|Test session results|[[:space:]]*[✘✗] Test .+ failed|[✔✘✓✗] Test run with|error:)" \
    || true
}

last_test_event() {
  grep -E "^(Test Suite '.+' (started|passed|failed)|Test Case '.+' (started|passed|failed|skipped)|[[:space:]]*[✘✗] Test .+ failed|[✔✘✓✗] Test run with)" "$TMPOUT" \
    | tail -1 \
    | sed 's/^[[:space:]]*//'
}

run_xcodebuild_once() {
  local xcode_pid last_line current_line heartbeat_at now elapsed recent_event
  xcodebuild test \
    -project "$XCODEPROJ" \
    -scheme BooksBrowser \
    -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
    -parallel-testing-enabled NO \
    -test-timeouts-enabled YES \
    -default-test-execution-time-allowance 60 \
    -maximum-test-execution-time-allowance 120 \
    -resultBundlePath "$RESULT_BUNDLE" \
    ${ONLY_FLAGS[@]+"${ONLY_FLAGS[@]}"} \
    >"$TMPOUT" 2>&1 &
  xcode_pid=$!
  CURRENT_XCODE_PID="$xcode_pid"
  echo "[ios_test] xcodebuild pid=$xcode_pid log=$TMPOUT xcresult=$RESULT_BUNDLE"

  last_line=0
  heartbeat_at=$(date +%s)
  while kill -0 "$xcode_pid" 2>/dev/null; do
    current_line=$(wc -l < "$TMPOUT" | tr -d ' ')
    if [[ "$current_line" -gt "$last_line" ]]; then
      emit_new_test_output "$((last_line + 1))" "$current_line"
      last_line="$current_line"
    fi

    now=$(date +%s)
    if [[ $((now - heartbeat_at)) -ge 30 ]]; then
      elapsed=$((now - START))
      recent_event="$(last_test_event)"
      [[ -n "$recent_event" ]] || recent_event="xcodebuild still running"
      echo "[ios_test] … still running (${elapsed}s, pid=$xcode_pid, log=$TMPOUT) — last: $recent_event"
      heartbeat_at="$now"
    fi
    sleep 2
  done

  wait "$xcode_pid"
  local status=$?
  CURRENT_XCODE_PID=""
  current_line=$(wc -l < "$TMPOUT" | tr -d ' ')
  if [[ "$current_line" -gt "$last_line" ]]; then
    emit_new_test_output "$((last_line + 1))" "$current_line"
  fi
  return "$status"
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
  [[ -n "$RESULT_DIR" ]] && rm -rf "$RESULT_DIR"
  RESULT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kg_ios_test_result.XXXXXX")"
  RESULT_BUNDLE="$RESULT_DIR/Test.xcresult"
  set +e
  run_xcodebuild_once
  EXIT_CODE=$?
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
DIAGNOSTICS="$SCRIPT_DIR/ios_diagnostics.py"
if [[ -x "$DIAGNOSTICS" ]]; then
  diag_result="fail"; [[ $EXIT_CODE -eq 0 ]] && diag_result="pass"
  "$DIAGNOSTICS" --kind test --xcresult "$RESULT_BUNDLE" --log "$TMPOUT" --result "$diag_result" --limit 40 || true
else
  echo "[ios_test] diagnostics unavailable: $DIAGNOSTICS" >&2
fi

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

count_executed_tests_xcresult() {
  local n
  [[ -n "$RESULT_BUNDLE" && -d "$RESULT_BUNDLE" ]] || return 1
  n="$("$SCRIPT_DIR/ios_diagnostics.py" --kind test --xcresult "$RESULT_BUNDLE" --json 2>/dev/null \
    | jq -r '.counts.tests // empty' 2>/dev/null)"
  [[ "$n" =~ ^[0-9]+$ ]] || return 1
  echo "$n"
}

# Machine-readable verdict file — survives even when stdout/stderr is piped
# (e.g. `ios_test.sh | tail`, where the pipeline's exit code is tail's, not the
# script's). Read this instead of trusting a piped `$?`.
VERDICT_FILE="${TMPDIR:-/tmp}/kg_ios_test_verdict"
VERDICT_JSON_FILE="$VERDICT_FILE.json"
write_json_verdict() {
  local result="$1" exit_code="$2" reason="$3" executed="$4"
  jq -nc \
    --arg schema "kg.ios.run-verdict.v1" \
    --arg kind "test" \
    --arg result "$result" \
    --arg exit "$exit_code" \
    --arg reason "$reason" \
    --arg caller "$CALLER" \
    --arg elapsed "${ELAPSED}s" \
    --arg executed "$executed" \
    --arg log "$TMPOUT" \
    --arg xcresult "$RESULT_BUNDLE" \
    '{
      schema:$schema,
      kind:$kind,
      status:$result,
      result:$result,
      exit:$exit,
      reason:(if $reason == "" then null else $reason end),
      caller:$caller,
      elapsed:$elapsed,
      executed:(if $executed == "" then null else $executed end),
      artifacts:{log:$log,xcresult:$xcresult}
    }' >"$VERDICT_JSON_FILE" || true
}

# Extract summary from xcresult if available
if grep -q '^\*\* TEST SUCCEEDED' "$TMPOUT" 2>/dev/null; then
  EXECUTED="$(count_executed_tests_xcresult || count_executed_tests)"
  if [[ "$EXECUTED" -eq 0 ]]; then
    echo ""
    echo "[ios_test] ✗ FALSE GREEN: xcodebuild reported TEST SUCCEEDED but 0 tests executed" >&2
    echo "[ios_test]   (likely a stale/bogus -only-testing test ID matched nothing) — $CALLER" >&2
    echo "RESULT=fail reason=false-green-0-executed caller=$CALLER log=$TMPOUT xcresult=$RESULT_BUNDLE" > "$VERDICT_FILE"
    write_json_verdict "fail" "1" "false-green-0-executed" "0"
    rm -f "$TMPOUT"
    exit 1
  fi
  echo ""
  echo "RESULT=ok executed=$EXECUTED caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE" > "$VERDICT_FILE"
  write_json_verdict "ok" "0" "" "$EXECUTED"
  echo "[ios_test] ✓ all tests passed ($EXECUTED executed, ${ELAPSED}s) — $CALLER  log=$TMPOUT  xcresult=$RESULT_BUNDLE  verdict=$VERDICT_FILE"
elif grep -q '^\*\* TEST FAILED' "$TMPOUT" 2>/dev/null; then
  echo ""
  # Show failing test details
  grep -E 'error:|failed' "$TMPOUT" | grep -v 'xcodebuild\|Linker\|frontend' | head -20
  echo ""
  PRESERVE_TMPOUT=1
  echo "RESULT=fail reason=tests-failed caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE" > "$VERDICT_FILE"
  write_json_verdict "fail" "1" "tests-failed" ""
  echo "[ios_test] ✗ tests failed (${ELAPSED}s) — $CALLER  verdict=$VERDICT_FILE" >&2
  echo "[ios_test] full log preserved: $TMPOUT" >&2
  echo "[ios_test] xcresult preserved: $RESULT_BUNDLE" >&2
  EXIT_CODE=1
else
  echo ""
  # Show last 10 lines for unexpected output
  tail -10 "$TMPOUT"
  PRESERVE_TMPOUT=1
  echo "RESULT=inconclusive EXIT=$EXIT_CODE caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE" > "$VERDICT_FILE"
  write_json_verdict "inconclusive" "$EXIT_CODE" "" ""
  echo "[ios_test] ? inconclusive (exit=$EXIT_CODE, ${ELAPSED}s) — $CALLER  verdict=$VERDICT_FILE" >&2
  echo "[ios_test] full log preserved: $TMPOUT" >&2
  echo "[ios_test] xcresult preserved: $RESULT_BUNDLE" >&2
  EXIT_CODE=1
fi

if [[ "$PRESERVE_TMPOUT" -eq 0 ]]; then
  rm -f "$TMPOUT"
fi
exit $EXIT_CODE
