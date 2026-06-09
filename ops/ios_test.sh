#!/usr/bin/env bash
# ios_test.sh — run iOS unit tests with clean pass/fail output
#
# Usage:
#   ./ops/ios_test.sh                             # run ALL tests in BooksBrowserTests
#   ./ops/ios_test.sh testName1 testName2 ...     # run specific tests (method names)
#   ./ops/ios_test.sh -g "notebook"               # grep: run tests matching pattern
#   ./ops/ios_test.sh --file BooksBrowserTests.swift
#   ./ops/ios_test.sh --ui testLaunchShowsPrimaryTabs
#   ./ops/ios_test.sh --launch-benchmark
#   ./ops/ios_test.sh --ui --ui-launch-profile ui-smoke testLaunchShowsPrimaryTabs
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
DESTINATION='platform=iOS Simulator,name=iPhone 17 Pro Max'
SIMULATOR_BOOT_SELECTOR='iPhone 17 Pro Max'
GREP_PATTERN=""
TEST_FILE=""
TEST_SCOPE="unit"
SPECIFIC_TESTS=()
LIST_ONLY=0
TEST_SCHEME="BooksBrowser"
TEST_CACHE_ACTION=""
JSON_MODE=0
UI_LAUNCH_PROFILE="${KG_IOS_TEST_UI_LAUNCH_PROFILE:-}"
LAUNCH_BENCHMARK=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -g|--grep) GREP_PATTERN="$2"; shift 2 ;;
    --file) TEST_FILE="$2"; shift 2 ;;
    --unit) TEST_SCOPE="unit"; shift ;;
    --ui) TEST_SCOPE="ui"; shift ;;
    --all-targets|--scheme) TEST_SCOPE="all"; shift ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --list) LIST_ONLY=1; shift ;;   # dry-run: print resolved -only-testing flags, no xcodebuild
    --prepare-cache) TEST_CACHE_ACTION="prepare"; shift ;;
    --cache-status) TEST_CACHE_ACTION="status"; shift ;;
    --clean-cache) TEST_CACHE_ACTION="clean"; shift ;;
    --json) JSON_MODE=1; shift ;;
    --ui-launch-profile) UI_LAUNCH_PROFILE="$2"; shift 2 ;;
    --launch-benchmark) LAUNCH_BENCHMARK=1; shift ;;
    *) SPECIFIC_TESTS+=("$1"); shift ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XCODEPROJ="$PROJECT_ROOT/ios/BooksBrowser.xcodeproj"
IOS_OPS="$SCRIPT_DIR/ios_ops.sh"
TEST_CACHE_ROOT="${KG_IOS_TEST_CACHE_ROOT:-$PROJECT_ROOT/.cache/ios-test-derived-data}"

# shellcheck source=lib/ios_test_discovery.sh
source "$SCRIPT_DIR/lib/ios_test_discovery.sh"
# Optional run-metrics logging — additive, must never break the test run.
METRICS_LIB="$SCRIPT_DIR/lib/ios_run_metrics.sh"
[[ -f "$METRICS_LIB" ]] && source "$METRICS_LIB"

[[ -d "$XCODEPROJ" ]] || { echo "error: $XCODEPROJ not found" >&2; exit 1; }

CALLER="${WORKTREE_BRANCH:-$(git -C "$PROJECT_ROOT" branch --show-current 2>/dev/null || echo 'unknown')}"

ios_test_now_ms() {
  perl -MTime::HiRes=time -e 'printf "%.0f\n", time() * 1000'
}

ios_test_build_input_paths() {
  {
    printf '%s\n' \
      "ios/BooksBrowser.xcodeproj/project.pbxproj" \
      "ios/BooksBrowser.xcodeproj/xcshareddata/xcschemes/BooksBrowser.xcscheme" \
      "ios/BooksBrowser.xcodeproj/xcshareddata/xcschemes/BooksBrowserUnitTests.xcscheme" \
      "ios/BooksBrowser.xcodeproj/xcshareddata/xcschemes/BooksBrowserUITests.xcscheme" \
      "ios/BooksBrowser.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
    rg --files ios/BooksBrowser ios/BooksBrowserTests ios/BooksBrowserUITests -g '*.swift' -g '*.plist'
  } | sort -u
}

ios_test_build_cache_key() {
  local xcode_version
  xcode_version="$(xcodebuild -version 2>/dev/null || true)"
  {
    printf 'destination=%s\n' "$DESTINATION"
    printf 'scope=%s\n' "$TEST_SCOPE"
    printf 'scheme=%s\n' "$TEST_SCHEME"
    printf 'xcode=%s\n' "$xcode_version"
    # Hash all inputs in a single shasum process instead of one fork per file
    # (~5.3s -> ~0.05s for ~556 files). Paths are already sorted+unique and
    # relative to the repo root, so the digest stays stable across worktrees
    # and independent of listing order.
    ios_test_build_input_paths \
      | ( cd "$PROJECT_ROOT" && tr '\n' '\0' | xargs -0 shasum -a 256 2>/dev/null )
  } | shasum -a 256 | awk '{print $1}'
}

ios_test_derived_data_root() {
  local cache_key
  cache_key="$(ios_test_build_cache_key)"
  mkdir -p "$TEST_CACHE_ROOT"
  printf '%s/%s\n' "$TEST_CACHE_ROOT" "$cache_key"
}

ios_test_find_xctestrun() {
  local derived_data_root="$1"
  local candidate=""
  [[ -d "$derived_data_root" ]] || return 1
  while IFS= read -r candidate; do
    [[ "$candidate" == *.scoped.xctestrun ]] && continue
    [[ -f "$candidate" ]] || continue
    printf '%s\n' "$candidate"
    return 0
  done < <(find "$derived_data_root" -type f -name '*.xctestrun' | sort)
  return 1
}

ios_test_list_xctestrun_artifacts() {
  local derived_data_root="$1"
  [[ -d "$derived_data_root" ]] || return 0
  find "$derived_data_root" -type f -name '*.xctestrun' | sort
}

ios_test_cached_products_ready() {
  local xctestrun_path="$1"
  local products_root app_bundle unit_bundle ui_bundle
  [[ -n "$xctestrun_path" && -f "$xctestrun_path" ]] || return 1
  products_root="$(dirname "$xctestrun_path")"
  app_bundle="$products_root/Debug-iphonesimulator/BooksBrowser.app"
  unit_bundle="$app_bundle/PlugIns/BooksBrowserTests.xctest"
  ui_bundle="$products_root/Debug-iphonesimulator/BooksBrowserUITests-Runner.app"
  [[ -d "$app_bundle" ]] || return 1
  case "$TEST_SCOPE" in
    unit)
      [[ -d "$unit_bundle" ]] || return 1
      ;;
    ui)
      [[ -d "$ui_bundle" ]] || return 1
      ;;
    all)
      [[ -d "$unit_bundle" && -d "$ui_bundle" ]] || return 1
      ;;
  esac
}

# --- Build -only-testing flags ---
ONLY_FLAGS=()
TEST_TARGET="BooksBrowserTests"
TEST_DIR="$PROJECT_ROOT/ios/BooksBrowserTests"

case "$TEST_SCOPE" in
  unit)
    TEST_TARGET="BooksBrowserTests"
    TEST_DIR="$PROJECT_ROOT/ios/BooksBrowserTests"
    TEST_SCHEME="BooksBrowserUnitTests"
    ;;
  ui)
    TEST_TARGET="BooksBrowserUITests"
    TEST_DIR="$PROJECT_ROOT/ios/BooksBrowserUITests"
    TEST_SCHEME="BooksBrowserUITests"
    ;;
  all)
    TEST_TARGET=""
    TEST_SCHEME="BooksBrowser"
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

if [[ "$LAUNCH_BENCHMARK" -eq 1 && ( -n "$GREP_PATTERN" || -n "$TEST_FILE" || ${#SPECIFIC_TESTS[@]} -gt 0 || "$TEST_SCOPE" == "all" ) ]]; then
  echo "[ios_test] error: --launch-benchmark cannot be combined with --all-targets, --file, --grep, or specific tests" >&2
  exit 1
fi

if [[ -n "$UI_LAUNCH_PROFILE" && "$TEST_SCOPE" == "unit" && "$LAUNCH_BENCHMARK" -eq 0 ]]; then
  echo "[ios_test] error: --ui-launch-profile requires --ui or --all-targets" >&2
  exit 1
fi

if [[ -n "$TEST_CACHE_ACTION" && ( "$LIST_ONLY" -eq 1 || -n "$GREP_PATTERN" || -n "$TEST_FILE" || ${#SPECIFIC_TESTS[@]} -gt 0 ) ]]; then
  echo "[ios_test] error: cache actions cannot be combined with --list, --file, --grep, or specific tests" >&2
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

if [[ "$TEST_SCOPE" == "ui" && -z "$UI_LAUNCH_PROFILE" ]]; then
  UI_LAUNCH_PROFILE="ui-smoke"
fi

if [[ "$LAUNCH_BENCHMARK" -eq 1 ]]; then
  TEST_SCOPE="ui"
  TEST_TARGET="BooksBrowserUITests"
  TEST_DIR="$PROJECT_ROOT/ios/BooksBrowserUITests"
  TEST_SCHEME="BooksBrowserUITests"
  ONLY_FLAGS=("-only-testing:BooksBrowserUITests/BooksBrowserUITests/testLaunchPerformance")
  if [[ -z "$UI_LAUNCH_PROFILE" ]]; then
    UI_LAUNCH_PROFILE="standard"
  fi
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

print_cache_payload() {
  local action="$1" status="$2" cache_key="$3" derived_root="$4" xctestrun_path="$5" products_ready="$6" build_ms="${7:-0}" boot_ms="${8:-0}" error_key="${9:-}" error_message="${10:-}" build_log_path="${11:-}" result_bundle_path="${12:-}"
  jq -n \
    --arg schema "kg.ios.test-cache.v1" \
    --arg action "$action" \
    --arg status "$status" \
    --arg scope "$TEST_SCOPE" \
    --arg scheme "$TEST_SCHEME" \
    --arg uiLaunchProfile "$UI_LAUNCH_PROFILE" \
    --arg destination "$DESTINATION" \
    --arg cacheKey "$cache_key" \
    --arg cacheRoot "$TEST_CACHE_ROOT" \
    --arg derivedRoot "$derived_root" \
    --arg xctestrunPath "$xctestrun_path" \
    --argjson productsReady "$products_ready" \
    --argjson buildMs "$build_ms" \
    --argjson bootMs "$boot_ms" \
    --arg errorKey "$error_key" \
    --arg errorMessage "$error_message" \
    --arg buildLogPath "$build_log_path" \
    --arg resultBundlePath "$result_bundle_path" \
    '{
      schema:$schema,
      generated_at:(now | strftime("%Y-%m-%dT%H:%M:%SZ")),
      action:$action,
      status:$status,
      scope:$scope,
      scheme:$scheme,
      uiLaunchProfile:(if $uiLaunchProfile == "" then null else $uiLaunchProfile end),
      destination:$destination,
      cache:{
        key:$cacheKey,
        root:$cacheRoot,
        derivedDataRoot:$derivedRoot,
        xctestrunPath:(if $xctestrunPath == "" then null else $xctestrunPath end),
        productsReady:$productsReady
      },
      timings:{
        bootMs:$bootMs,
        buildForTestingMs:$buildMs
      },
      artifacts:{
        buildLog:(if $buildLogPath == "" then null else $buildLogPath end),
        resultBundle:(if $resultBundlePath == "" then null else $resultBundlePath end)
      },
      errors:(if $errorKey == "" then [] else [{key:$errorKey,status:"error",error:$errorMessage}] end)
    }'
}

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
LOCK_WAIT_START_MS="$(ios_test_now_ms)"
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
LOCK_WAIT_MS=$(( $(ios_test_now_ms) - LOCK_WAIT_START_MS ))

echo "[ios_test] lock acquired lockWaitMs=$LOCK_WAIT_MS — scope=$TEST_SCOPE running ${#ONLY_FLAGS[@]} selector(s) (0=scheme all targets)..."
START=$(date +%s)
START_MS="$(ios_test_now_ms)"
BOOT_MS=0
XCODEBUILD_MS=0
BUILD_FOR_TESTING_MS=0
TEST_INVOCATION_MS=0
CACHE_STATUS="none"
DERIVED_DATA_ROOT=""
XCTESTRUN_PATH=""
TEST_BODY_MS=0
XCRESULT_SESSION_MS=0
XCRESULT_HARNESS_OVERHEAD_MS=0
INVOCATION_OVERHEAD_MS=0
boot_simulator_if_needed() {
  local boot_start_ms boot_end_ms
  boot_start_ms="$(ios_test_now_ms)"
  "$IOS_OPS" simulator ensure-booted --device "$SIMULATOR_BOOT_SELECTOR" >/dev/null
  boot_end_ms="$(ios_test_now_ms)"
  BOOT_MS=$(( boot_end_ms - boot_start_ms ))
  echo "[ios_test] simulator ensure-booted device=\"$SIMULATOR_BOOT_SELECTOR\" bootMs=$BOOT_MS"
}

ui_test_launch_args_json() {
  if [[ -n "$UI_LAUNCH_PROFILE" ]]; then
    jq -nc --arg profile "$UI_LAUNCH_PROFILE" '["-appLaunchProfile", $profile]'
  else
    jq -nc '[]'
  fi
}

handle_cache_action() {
  local cache_key derived_root xctestrun_path products_ready payload build_log build_result_dir build_result_bundle build_exit
  local action="$1"
  cache_key="$(ios_test_build_cache_key)"
  derived_root="$(ios_test_derived_data_root)"
  DERIVED_DATA_ROOT="$derived_root"
  xctestrun_path="$(ios_test_find_xctestrun "$derived_root" || true)"
  products_ready=false
  if ios_test_cached_products_ready "$xctestrun_path"; then
    products_ready=true
  fi

  case "$action" in
    status)
      payload="$(print_cache_payload status ok "$cache_key" "$derived_root" "$xctestrun_path" "$products_ready")"
      ;;
    clean)
      rm -rf "$derived_root"
      payload="$(print_cache_payload clean ok "$cache_key" "$derived_root" "" false)"
      ;;
    prepare)
      boot_simulator_if_needed
      if [[ "$products_ready" == true ]]; then
        payload="$(print_cache_payload prepare hit "$cache_key" "$derived_root" "$xctestrun_path" true 0 "$BOOT_MS")"
      else
        build_log="$(mktemp)"
        build_result_dir="$(mktemp -d "${TMPDIR:-/tmp}/kg_ios_test_build_result.XXXXXX")"
        build_result_bundle="$build_result_dir/BuildForTesting.xcresult"
        rebuild_test_cache "$build_log" "$build_result_bundle"
        build_exit=$?
        if [[ "$build_exit" -eq 0 ]]; then
          xctestrun_path="$(ios_test_find_xctestrun "$derived_root" || true)"
          products_ready=false
          if ios_test_cached_products_ready "$xctestrun_path"; then
            products_ready=true
          fi
          payload="$(print_cache_payload prepare prepared "$cache_key" "$derived_root" "$xctestrun_path" "$products_ready" "$BUILD_FOR_TESTING_MS" "$BOOT_MS" "" "" "$build_log" "$build_result_bundle")"
        else
          payload="$(print_cache_payload prepare error "$cache_key" "$derived_root" "$xctestrun_path" false "$BUILD_FOR_TESTING_MS" "$BOOT_MS" "build-for-testing" "prepare-cache-failed" "$build_log" "$build_result_bundle")"
        fi
        if [[ "$build_exit" -eq 0 ]]; then
          rm -f "$build_log"
          rm -rf "$build_result_dir"
        fi
      fi
      ;;
    *)
      echo "[ios_test] internal error: unknown cache action '$action'" >&2
      exit 2
      ;;
  esac

  if (( JSON_MODE )); then
    printf '%s\n' "$payload"
  else
    jq -r '
      "[ios][test-cache] action=\(.action) status=\(.status) scope=\(.scope) scheme=\(.scheme)",
      "[ios][test-cache] key=\(.cache.key) root=\(.cache.root) derivedDataRoot=\(.cache.derivedDataRoot)",
      "[ios][test-cache] productsReady=\(.cache.productsReady) xctestrun=\(.cache.xctestrunPath // "")",
      "[ios][test-cache] timings bootMs=\(.timings.bootMs) buildForTestingMs=\(.timings.buildForTestingMs)",
      (if .artifacts.buildLog then "[ios][test-cache] buildLog=\(.artifacts.buildLog) resultBundle=\(.artifacts.resultBundle // "")" else empty end),
      (.errors[]? | "[ios][test-cache] error key=\(.key) status=\(.status) error=\(.error)")
    ' <<<"$payload"
  fi

  if [[ "$(jq -r '.status' <<<"$payload")" == "error" ]]; then
    exit 1
  fi
  exit 0
}

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

run_xcodebuild_test_once() {
  local xcode_pid last_line current_line heartbeat_at now elapsed recent_event xcode_start_ms xcode_end_ms
  xcode_start_ms="$(ios_test_now_ms)"
  KG_UI_TEST_APP_ARGS_JSON="$(ui_test_launch_args_json)" xcodebuild test \
    -project "$XCODEPROJ" \
    -scheme "$TEST_SCHEME" \
    -destination "$DESTINATION" \
    -derivedDataPath "$DERIVED_DATA_ROOT" \
    -parallel-testing-enabled NO \
    -test-timeouts-enabled YES \
    -default-test-execution-time-allowance 60 \
    -maximum-test-execution-time-allowance 120 \
    -resultBundlePath "$RESULT_BUNDLE" \
    ${ONLY_FLAGS[@]+"${ONLY_FLAGS[@]}"} \
    >"$TMPOUT" 2>&1 &
  xcode_pid=$!
  CURRENT_XCODE_PID="$xcode_pid"
  echo "[ios_test] xcodebuild pid=$xcode_pid uiLaunchProfile=${UI_LAUNCH_PROFILE:-standard} log=$TMPOUT xcresult=$RESULT_BUNDLE"

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
  xcode_end_ms="$(ios_test_now_ms)"
  TEST_INVOCATION_MS=$(( xcode_end_ms - xcode_start_ms ))
  XCODEBUILD_MS=$TEST_INVOCATION_MS
  CURRENT_XCODE_PID=""
  current_line=$(wc -l < "$TMPOUT" | tr -d ' ')
  if [[ "$current_line" -gt "$last_line" ]]; then
    emit_new_test_output "$((last_line + 1))" "$current_line"
  fi
  return "$status"
}

run_xcodebuild_test_without_building_once() {
  local xctestrun_path="$1"
  local xcode_pid last_line current_line heartbeat_at now elapsed recent_event xcode_start_ms xcode_end_ms
  xcode_start_ms="$(ios_test_now_ms)"
  KG_UI_TEST_APP_ARGS_JSON="$(ui_test_launch_args_json)" xcodebuild test-without-building \
    -xctestrun "$xctestrun_path" \
    -destination "$DESTINATION" \
    -parallel-testing-enabled NO \
    -test-timeouts-enabled YES \
    -default-test-execution-time-allowance 60 \
    -maximum-test-execution-time-allowance 120 \
    -resultBundlePath "$RESULT_BUNDLE" \
    ${ONLY_FLAGS[@]+"${ONLY_FLAGS[@]}"} \
    >"$TMPOUT" 2>&1 &
  xcode_pid=$!
  CURRENT_XCODE_PID="$xcode_pid"
  echo "[ios_test] xcodebuild pid=$xcode_pid mode=test-without-building uiLaunchProfile=${UI_LAUNCH_PROFILE:-standard} xctestrun=$xctestrun_path log=$TMPOUT xcresult=$RESULT_BUNDLE"

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
  xcode_end_ms="$(ios_test_now_ms)"
  TEST_INVOCATION_MS=$(( xcode_end_ms - xcode_start_ms ))
  XCODEBUILD_MS=$(( BUILD_FOR_TESTING_MS + TEST_INVOCATION_MS ))
  CURRENT_XCODE_PID=""
  current_line=$(wc -l < "$TMPOUT" | tr -d ' ')
  if [[ "$current_line" -gt "$last_line" ]]; then
    emit_new_test_output "$((last_line + 1))" "$current_line"
  fi
  return "$status"
}

rebuild_test_cache() {
  local build_log="$1" build_result_bundle="$2"
  local build_start_ms build_end_ms
  mkdir -p "$DERIVED_DATA_ROOT"
  build_start_ms="$(ios_test_now_ms)"
  xcodebuild build-for-testing \
    -project "$XCODEPROJ" \
    -scheme "$TEST_SCHEME" \
    -destination "$DESTINATION" \
    -parallel-testing-enabled NO \
    -test-timeouts-enabled YES \
    -default-test-execution-time-allowance 60 \
    -maximum-test-execution-time-allowance 120 \
    -derivedDataPath "$DERIVED_DATA_ROOT" \
    -resultBundlePath "$build_result_bundle" \
    >"$build_log" 2>&1
  build_end_ms="$(ios_test_now_ms)"
  BUILD_FOR_TESTING_MS=$(( build_end_ms - build_start_ms ))
}

ensure_xctestrun_ready_or_fail() {
  local xctestrun_path="$1"
  if [[ -z "$xctestrun_path" || ! -f "$xctestrun_path" ]]; then
    local discovered_xctestruns
    discovered_xctestruns="$(ios_test_list_xctestrun_artifacts "$DERIVED_DATA_ROOT" | sed 's#^#[ios_test] discovered=#')"
    cat >"$TMPOUT" <<EOF
[ios_test] error: build-for-testing completed but no .xctestrun artifact was found
[ios_test] derivedDataRoot=$DERIVED_DATA_ROOT
[ios_test] scheme=$TEST_SCHEME
[ios_test] destination=$DESTINATION
EOF
    [[ -n "$discovered_xctestruns" ]] && printf '%s\n' "$discovered_xctestruns" >>"$TMPOUT"
    return 1
  fi
  if ! ios_test_cached_products_ready "$xctestrun_path"; then
    cat >"$TMPOUT" <<EOF
[ios_test] error: .xctestrun exists but cached test products are incomplete
[ios_test] xctestrun=$xctestrun_path
[ios_test] derivedDataRoot=$DERIVED_DATA_ROOT
EOF
    return 1
  fi
}

if [[ -n "$TEST_CACHE_ACTION" ]]; then
  handle_cache_action "$TEST_CACHE_ACTION"
fi

# Run xcodebuild test, capture output to parse results. Xcode can keep the
# shared DerivedData build database locked briefly after the previous simulator
# test process exits, so retry that infrastructure failure before surfacing it.
MAX_BUILD_DB_LOCK_RETRIES=3
ATTEMPT=1
EXIT_CODE=0
boot_simulator_if_needed
DERIVED_DATA_ROOT="$(ios_test_derived_data_root)"
XCTESTRUN_PATH="$(ios_test_find_xctestrun "$DERIVED_DATA_ROOT" || true)"
while :; do
  [[ -n "$TMPOUT" ]] && rm -f "$TMPOUT"
  TMPOUT=$(mktemp)
  [[ -n "$RESULT_DIR" ]] && rm -rf "$RESULT_DIR"
  RESULT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kg_ios_test_result.XXXXXX")"
  RESULT_BUNDLE="$RESULT_DIR/Test.xcresult"
  set +e
  BUILD_FOR_TESTING_MS=0
  TEST_INVOCATION_MS=0
  if ios_test_cached_products_ready "$XCTESTRUN_PATH"; then
    CACHE_STATUS="hit"
    run_xcodebuild_test_without_building_once "$XCTESTRUN_PATH"
    EXIT_CODE=$?
    if [[ "$EXIT_CODE" -ne 0 ]]; then
      CACHE_STATUS="rebuild-after-failure"
      BUILD_LOG="$(mktemp)"
      BUILD_RESULT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kg_ios_test_build_result.XXXXXX")"
      BUILD_RESULT_BUNDLE="$BUILD_RESULT_DIR/BuildForTesting.xcresult"
      rebuild_test_cache "$BUILD_LOG" "$BUILD_RESULT_BUNDLE"
      BUILD_EXIT=$?
      if [[ "$BUILD_EXIT" -eq 0 ]]; then
        XCTESTRUN_PATH="$(ios_test_find_xctestrun "$DERIVED_DATA_ROOT" || true)"
        if ensure_xctestrun_ready_or_fail "$XCTESTRUN_PATH"; then
          run_xcodebuild_test_without_building_once "$XCTESTRUN_PATH"
          EXIT_CODE=$?
        else
          EXIT_CODE=1
        fi
      else
        cat "$BUILD_LOG" >"$TMPOUT"
        EXIT_CODE="$BUILD_EXIT"
      fi
      rm -f "$BUILD_LOG"
      rm -rf "$BUILD_RESULT_DIR"
    fi
  else
    CACHE_STATUS="miss"
    BUILD_LOG="$(mktemp)"
    BUILD_RESULT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kg_ios_test_build_result.XXXXXX")"
    BUILD_RESULT_BUNDLE="$BUILD_RESULT_DIR/BuildForTesting.xcresult"
    rebuild_test_cache "$BUILD_LOG" "$BUILD_RESULT_BUNDLE"
    BUILD_EXIT=$?
    if [[ "$BUILD_EXIT" -eq 0 ]]; then
      XCTESTRUN_PATH="$(ios_test_find_xctestrun "$DERIVED_DATA_ROOT" || true)"
      if ensure_xctestrun_ready_or_fail "$XCTESTRUN_PATH"; then
        run_xcodebuild_test_without_building_once "$XCTESTRUN_PATH"
        EXIT_CODE=$?
        CACHE_STATUS="prepared"
      else
        EXIT_CODE=1
      fi
    else
      cat "$BUILD_LOG" >"$TMPOUT"
      EXIT_CODE="$BUILD_EXIT"
    fi
    rm -f "$BUILD_LOG"
    rm -rf "$BUILD_RESULT_DIR"
  fi
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
END_MS="$(ios_test_now_ms)"
TOTAL_MS=$(( END_MS - START_MS ))
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

read_timing_breakdown_xcresult() {
  local diag_json body_ms session_ms app_launch_avg_ms app_launch_samples
  [[ -n "$RESULT_BUNDLE" && -d "$RESULT_BUNDLE" ]] || return 1
  diag_json="$("$SCRIPT_DIR/ios_diagnostics.py" --kind test --xcresult "$RESULT_BUNDLE" --json 2>/dev/null)" || return 1
  body_ms="$(jq -r '.timings.testBodyMs // empty' <<<"$diag_json" 2>/dev/null)" || return 1
  session_ms="$(jq -r '.timings.xcresultSessionMs // empty' <<<"$diag_json" 2>/dev/null)" || return 1
  app_launch_avg_ms="$(jq -r '.performanceMetrics.appLaunch.averageMs // 0' <<<"$diag_json" 2>/dev/null)" || return 1
  app_launch_samples="$(jq -r '.performanceMetrics.appLaunch.samples // 0' <<<"$diag_json" 2>/dev/null)" || return 1
  [[ "$body_ms" =~ ^[0-9]+$ && "$session_ms" =~ ^[0-9]+$ && "$app_launch_avg_ms" =~ ^[0-9]+$ && "$app_launch_samples" =~ ^[0-9]+$ ]] || return 1
  echo "$body_ms $session_ms $app_launch_avg_ms $app_launch_samples"
}

populate_timing_breakdown() {
  local breakdown body_ms session_ms app_launch_avg_ms app_launch_samples
  TEST_BODY_MS=0
  XCRESULT_SESSION_MS=0
  XCRESULT_HARNESS_OVERHEAD_MS=0
  INVOCATION_OVERHEAD_MS=0
  APP_LAUNCH_AVERAGE_MS=0
  APP_LAUNCH_SAMPLES=0
  breakdown="$(read_timing_breakdown_xcresult || true)"
  [[ -n "$breakdown" ]] || return 0
  read -r body_ms session_ms app_launch_avg_ms app_launch_samples <<<"$breakdown"
  [[ "$body_ms" =~ ^[0-9]+$ && "$session_ms" =~ ^[0-9]+$ && "$app_launch_avg_ms" =~ ^[0-9]+$ && "$app_launch_samples" =~ ^[0-9]+$ ]] || return 0
  TEST_BODY_MS="$body_ms"
  XCRESULT_SESSION_MS="$session_ms"
  APP_LAUNCH_AVERAGE_MS="$app_launch_avg_ms"
  APP_LAUNCH_SAMPLES="$app_launch_samples"
  XCRESULT_HARNESS_OVERHEAD_MS=$(( XCRESULT_SESSION_MS - TEST_BODY_MS ))
  if (( XCRESULT_HARNESS_OVERHEAD_MS < 0 )); then
    XCRESULT_HARNESS_OVERHEAD_MS=0
  fi
  INVOCATION_OVERHEAD_MS=$(( TEST_INVOCATION_MS - XCRESULT_SESSION_MS ))
  if (( INVOCATION_OVERHEAD_MS < 0 )); then
    INVOCATION_OVERHEAD_MS=0
  fi
}

print_timing_summary() {
  echo "[ios_test] timings cacheStatus=$CACHE_STATUS uiLaunchProfile=${UI_LAUNCH_PROFILE:-standard} bootMs=$BOOT_MS buildForTestingMs=$BUILD_FOR_TESTING_MS testInvocationMs=$TEST_INVOCATION_MS testBodyMs=$TEST_BODY_MS xcresultSessionMs=$XCRESULT_SESSION_MS xcresultHarnessOverheadMs=$XCRESULT_HARNESS_OVERHEAD_MS appLaunchAverageMs=$APP_LAUNCH_AVERAGE_MS appLaunchSamples=$APP_LAUNCH_SAMPLES invocationOverheadMs=$INVOCATION_OVERHEAD_MS xcodebuildMs=$XCODEBUILD_MS totalMs=$TOTAL_MS"
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
    --arg uiLaunchProfile "$UI_LAUNCH_PROFILE" \
    --arg elapsed "${ELAPSED}s" \
    --arg executed "$executed" \
    --arg log "$TMPOUT" \
    --arg xcresult "$RESULT_BUNDLE" \
    --argjson lockWaitMs "${LOCK_WAIT_MS:-0}" \
    --argjson bootMs "$BOOT_MS" \
    --argjson xcodebuildMs "$XCODEBUILD_MS" \
    --argjson buildForTestingMs "$BUILD_FOR_TESTING_MS" \
    --argjson testInvocationMs "$TEST_INVOCATION_MS" \
    --argjson testBodyMs "$TEST_BODY_MS" \
    --argjson xcresultSessionMs "$XCRESULT_SESSION_MS" \
    --argjson xcresultHarnessOverheadMs "$XCRESULT_HARNESS_OVERHEAD_MS" \
    --argjson appLaunchAverageMs "$APP_LAUNCH_AVERAGE_MS" \
    --argjson appLaunchSamples "$APP_LAUNCH_SAMPLES" \
    --argjson invocationOverheadMs "$INVOCATION_OVERHEAD_MS" \
    --argjson totalMs "$TOTAL_MS" \
    --arg cacheStatus "$CACHE_STATUS" \
    '{
      schema:$schema,
      kind:$kind,
      status:$result,
      result:$result,
      exit:$exit,
      reason:(if $reason == "" then null else $reason end),
      caller:$caller,
      options:{
        uiLaunchProfile:(if $uiLaunchProfile == "" then null else $uiLaunchProfile end)
      },
      elapsed:$elapsed,
      executed:(if $executed == "" then null else $executed end),
      timings:{
        lockWaitMs:$lockWaitMs,
        bootMs:$bootMs,
        xcodebuildMs:$xcodebuildMs,
        buildForTestingMs:$buildForTestingMs,
        testInvocationMs:$testInvocationMs,
        testBodyMs:$testBodyMs,
        xcresultSessionMs:$xcresultSessionMs,
        xcresultHarnessOverheadMs:$xcresultHarnessOverheadMs,
        appLaunchAverageMs:$appLaunchAverageMs,
        appLaunchSamples:$appLaunchSamples,
        invocationOverheadMs:$invocationOverheadMs,
        totalMs:$totalMs
      },
      cache:{status:$cacheStatus},
      artifacts:{log:$log,xcresult:$xcresult}
    }' >"$VERDICT_JSON_FILE" || true
  type append_run_metric >/dev/null 2>&1 && append_run_metric "$VERDICT_JSON_FILE"
}

populate_timing_breakdown

# Extract summary from xcresult if available
if grep -qE '^\*\* TEST( EXECUTE)? SUCCEEDED' "$TMPOUT" 2>/dev/null; then
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
  print_timing_summary
  echo "[ios_test] ✓ all tests passed ($EXECUTED executed, ${ELAPSED}s) — $CALLER  log=$TMPOUT  xcresult=$RESULT_BUNDLE  verdict=$VERDICT_FILE"
elif grep -qE '^\*\* TEST( EXECUTE)? FAILED' "$TMPOUT" 2>/dev/null; then
  echo ""
  # Show failing test details
  grep -E 'error:|failed' "$TMPOUT" | grep -v 'xcodebuild\|Linker\|frontend' | head -20
  echo ""
  PRESERVE_TMPOUT=1
  echo "RESULT=fail reason=tests-failed caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE" > "$VERDICT_FILE"
  write_json_verdict "fail" "1" "tests-failed" ""
  print_timing_summary
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
  print_timing_summary
  echo "[ios_test] ? inconclusive (exit=$EXIT_CODE, ${ELAPSED}s) — $CALLER  verdict=$VERDICT_FILE" >&2
  echo "[ios_test] full log preserved: $TMPOUT" >&2
  echo "[ios_test] xcresult preserved: $RESULT_BUNDLE" >&2
  EXIT_CODE=1
fi

if [[ "$PRESERVE_TMPOUT" -eq 0 ]]; then
  rm -f "$TMPOUT"
fi
exit $EXIT_CODE
