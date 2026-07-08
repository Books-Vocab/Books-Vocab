#!/usr/bin/env bash
# ios_test.sh — run iOS unit tests with clean pass/fail output
#
# Usage:
#   ./ops/ios_test.sh                             # run ALL tests in BooksAndVocabTests
#   ./ops/ios_test.sh testName1 testName2 ...     # run specific tests (method names)
#   ./ops/ios_test.sh -g "notebook"               # grep: run tests whose METHOD name OR
#                                                 # suite/container name (@Suite struct / class)
#                                                 # matches — `-g FooTests` runs the whole suite.
#                                                 # File names are NOT matched; repeat -g to OR
#                                                 # patterns together.
#   ./ops/ios_test.sh --file FooTests             # .swift suffix optional; bare type name also works
#   ./ops/ios_test.sh --ui testLaunchShowsPrimaryTabs
#   ./ops/ios_test.sh --launch-benchmark
#   ./ops/ios_test.sh --ui --ui-launch-profile ui-smoke testLaunchShowsPrimaryTabs
#   ./ops/ios_test.sh --ui --dataset <name>       # inject ops/fixtures/ui_worlds/<name>.json into the app (KG_FIXTURE_DATASET_B64)
#   ./ops/ios_test.sh --ui --dataset-file <path>  # same, arbitrary dataset path
#   ./ops/ios_test.sh --all-targets               # run scheme test action, including UI tests
#   ./ops/ios_test.sh --coverage [--coverage-fail-under <percent>]
#   ./ops/ios_test.sh --device <name|UDID>        # target a specific simulator (parallel agents)
#   ./ops/ios_test.sh --destination '<xcodebuild destination>'   # full -destination override
#   ./ops/ios_test.sh --unit --lease              # auto-claim a pool simulator for this run (parallel agents)
#   KG_IOS_TEST_ALLOW_SHARED_SIM=1 ./ops/ios_test.sh ...         # explicit opt-out for single-machine debugging
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
DEFAULT_SIMULATOR='iPhone 17 Pro Max'
DESTINATION=''            # resolved after arg parsing (see device resolution below)
DESTINATION_OVERRIDE=''   # set by --destination (full xcodebuild destination string)
DEVICE_OVERRIDE="${KG_IOS_TEST_DEVICE:-}"  # set by --device (name or UDID); enables per-agent simulators
AUTO_LEASE="${KG_IOS_TEST_AUTOLEASE:-0}"   # --lease: claim a pool simulator for this run, release on exit
LEASED_DEVICE=''                            # udid of an auto-leased simulator, released in cleanup
LEASE_OWNER_TOKEN="kg-ios-test-$$-$(date +%s)-${RANDOM:-0}"
SIMULATOR_BOOT_SELECTOR=''
GREP_PATTERN=""
TEST_FILE=""
TEST_SCOPE="unit"
SPECIFIC_TESTS=()
LIST_ONLY=0
TEST_SCHEME="BooksAndVocab"
TEST_CACHE_ACTION=""
JSON_MODE=0
UI_LAUNCH_PROFILE="${KG_IOS_TEST_UI_LAUNCH_PROFILE:-}"
LAUNCH_BENCHMARK=0
COVERAGE_ENABLED=0
COVERAGE_FAIL_UNDER=""
COVERAGE_TARGET="${KG_IOS_TEST_COVERAGE_TARGET:-BooksAndVocab}"
UI_FIXTURE_DATASET_NAME=""
UI_FIXTURE_DATASET_FILE=""
UI_FIXTURE_DATASET_B64=""
STAGED_DATASET_XCTESTRUN=""
UI_TEST_REVIEW_ROOT=""
UI_TEST_REVIEW_HTML=""

build_ui_test_variant_id() {
  local parts=()
  if [[ -n "$UI_FIXTURE_DATASET_NAME" ]]; then
    parts+=("dataset:$UI_FIXTURE_DATASET_NAME")
  elif [[ -n "$UI_FIXTURE_DATASET_FILE" ]]; then
    parts+=("dataset-file:$(basename "$UI_FIXTURE_DATASET_FILE")")
  fi
  if [[ -n "$UI_LAUNCH_PROFILE" ]]; then
    parts+=("profile:$UI_LAUNCH_PROFILE")
  fi
  if [[ ${#parts[@]} -eq 0 ]]; then
    printf 'default'
    return
  fi
  local joined="${parts[0]}"
  local part
  for part in "${parts[@]:1}"; do
    joined+="+$part"
  done
  printf '%s' "$joined"
}
UI_TEST_FLOW_ID=""
UI_TEST_VARIANT_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      # 印整段 header comment（到第一個非 # 行為止），不再硬編行號（曾因
      # header 增行而把尾段 usage 默默截掉）。
      awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
      exit 0
      ;;
    -g|--grep)
      # 重複 -g 累積成 OR regex（歷史 footgun：後者無聲覆蓋前者 → 以為跑了
      # 兩個測試實際只跑一個）。pattern 是 awk ERE，頂層 | 即聯集。
      # 空 pattern 直接拒絕：累積後的空 alternative 會匹配一切（silent broadening）。
      if [[ -z "$2" ]]; then
        echo "[ios_test] error: -g/--grep 不接受空 pattern" >&2
        exit 2
      fi
      if [[ -n "$GREP_PATTERN" ]]; then
        GREP_PATTERN="$GREP_PATTERN|$2"
      else
        GREP_PATTERN="$2"
      fi
      shift 2 ;;
    --file)
      # 重複 --file 只會保留最後一個、靜默丟棄其餘 → 曾誘發 false-green（以為跑了多檔，
      # 其實只跑最後一檔）。檔名不是 regex、沒有聯集載體，故報錯而非像 -g 那樣累積。
      if [[ -n "$TEST_FILE" ]]; then
        echo "[ios_test] error: --file 只能指定一次（重複會靜默覆蓋）。多檔請改用重複 -g <方法名>（自動 OR）或 --grep '<A>|<B>'，或分多次執行。" >&2
        exit 2
      fi
      TEST_FILE="$2"; shift 2 ;;
    --unit) TEST_SCOPE="unit"; shift ;;
    --ui) TEST_SCOPE="ui"; shift ;;
    --all-targets|--scheme) TEST_SCOPE="all"; shift ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --device) DEVICE_OVERRIDE="$2"; shift 2 ;;        # name or UDID; pick a specific simulator
    --destination) DESTINATION_OVERRIDE="$2"; shift 2 ;;  # full xcodebuild -destination override
    --lease) AUTO_LEASE=1; shift ;;                   # claim a pool simulator for this run (parallel agents)
    --list) LIST_ONLY=1; shift ;;   # dry-run: print resolved -only-testing flags, no xcodebuild
    --prepare-cache) TEST_CACHE_ACTION="prepare"; shift ;;
    --cache-status) TEST_CACHE_ACTION="status"; shift ;;
    --clean-cache) TEST_CACHE_ACTION="clean"; shift ;;
    --json) JSON_MODE=1; shift ;;
    --ui-launch-profile) UI_LAUNCH_PROFILE="$2"; shift 2 ;;
    --launch-benchmark) LAUNCH_BENCHMARK=1; shift ;;
    --coverage) COVERAGE_ENABLED=1; shift ;;
    --coverage-fail-under) COVERAGE_ENABLED=1; COVERAGE_FAIL_UNDER="$2"; shift 2 ;;
    --dataset) UI_FIXTURE_DATASET_NAME="${2:?--dataset needs value}"; shift 2 ;;
    --dataset-file) UI_FIXTURE_DATASET_FILE="${2:?--dataset-file needs value}"; shift 2 ;;
    *) SPECIFIC_TESTS+=("$1"); shift ;;
  esac
done

if [[ -n "$COVERAGE_FAIL_UNDER" && ! "$COVERAGE_FAIL_UNDER" =~ ^([0-9]+)(\.[0-9]+)?$ ]]; then
  echo "[ios_test] error: --coverage-fail-under must be numeric percent (0..100)" >&2
  exit 2
fi
if [[ -n "$COVERAGE_FAIL_UNDER" ]]; then
  awk -v value="$COVERAGE_FAIL_UNDER" 'BEGIN { exit !(value >= 0 && value <= 100) }' || {
    echo "[ios_test] error: --coverage-fail-under must be between 0 and 100" >&2
    exit 2
  }
fi

COVERAGE_XCODEBUILD_ARGS=()
if [[ "$COVERAGE_ENABLED" -eq 1 ]]; then
  COVERAGE_XCODEBUILD_ARGS=(-enableCodeCoverage YES)
fi

# Resolve the simulator destination. Precedence: --destination (full override)
# > --device (name|UDID) > default. A UDID-shaped value targets `id=`, anything
# else `name=`. SIMULATOR_BOOT_SELECTOR feeds `simulator ensure-booted` and
# accepts a name or UDID directly. This makes the script target-agnostic so
# parallel agents can each run on their own leased simulator.
if [[ -n "$DESTINATION_OVERRIDE" ]]; then
  DESTINATION="$DESTINATION_OVERRIDE"
  SIMULATOR_BOOT_SELECTOR="${DEVICE_OVERRIDE:-$DEFAULT_SIMULATOR}"
elif [[ -n "$DEVICE_OVERRIDE" ]]; then
  SIMULATOR_BOOT_SELECTOR="$DEVICE_OVERRIDE"
  if [[ "$DEVICE_OVERRIDE" =~ ^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$ ]]; then
    DESTINATION="platform=iOS Simulator,id=$DEVICE_OVERRIDE"
  else
    DESTINATION="platform=iOS Simulator,name=$DEVICE_OVERRIDE"
  fi
else
  DESTINATION="platform=iOS Simulator,name=$DEFAULT_SIMULATOR"
  SIMULATOR_BOOT_SELECTOR="$DEFAULT_SIMULATOR"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XCODEPROJ="$PROJECT_ROOT/ios/BooksAndVocab.xcodeproj"
IOS_OPS="$SCRIPT_DIR/ios_ops.sh"
TEST_CACHE_ROOT="${KG_IOS_TEST_CACHE_ROOT:-$PROJECT_ROOT/.cache/ios-test-derived-data}"
UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    UV_BIN="$HOME/.local/bin/uv"
  else
    UV_BIN="uv"
  fi
fi

# shellcheck source=lib/ios_test_discovery.sh
source "$SCRIPT_DIR/lib/ios_test_discovery.sh"
# shellcheck source=lib/ios_build_progress.sh
source "$SCRIPT_DIR/lib/ios_build_progress.sh"
# shellcheck source=lib/ios_cache_evict.sh
source "$SCRIPT_DIR/lib/ios_cache_evict.sh"
# shellcheck source=lib/ios_test_video_archive.sh
source "$SCRIPT_DIR/lib/ios_test_video_archive.sh"
# shellcheck source=lib/ios_run_verdict.sh
source "$SCRIPT_DIR/lib/ios_run_verdict.sh"
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
      "ios/BooksAndVocab.xcodeproj/project.pbxproj" \
      "ios/BooksAndVocab.xcodeproj/xcshareddata/xcschemes/BooksAndVocab.xcscheme" \
      "ios/BooksAndVocab.xcodeproj/xcshareddata/xcschemes/BooksAndVocabUnitTests.xcscheme" \
      "ios/BooksAndVocab.xcodeproj/xcshareddata/xcschemes/BooksAndVocabUITests.xcscheme" \
      "ios/BooksAndVocab.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
    rg --files ios/BooksAndVocab ios/BooksAndVocabTests ios/BooksAndVocabUITests -g '*.swift' -g '*.plist'
  } | sort -u
}

ios_test_build_cache_key() {
  local xcode_version
  xcode_version="$(xcodebuild -version 2>/dev/null || true)"
  # Key on platform+arch, NOT the specific device name/UDID. build-for-testing
  # products are per (platform, arch, configuration) and identical across
  # simulators of the same platform, so a pool of leased devices shares ONE warm
  # cache instead of each device fragmenting its own. A genuinely different
  # platform (e.g. Mac Catalyst via --destination) still gets a distinct key.
  local platform_token
  platform_token="$(printf '%s' "$DESTINATION" | sed -n 's/.*platform=\([^,]*\).*/\1/p' | tr '[:upper:] ' '[:lower:]-')"
  [[ -n "$platform_token" ]] || platform_token="unknown"
  {
    printf 'platform=%s\n' "$platform_token"
    printf 'arch=%s\n' "$(uname -m)"
    printf 'scope=%s\n' "$TEST_SCOPE"
    printf 'scheme=%s\n' "$TEST_SCHEME"
    printf 'coverage=%s\n' "$COVERAGE_ENABLED"
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
  app_bundle="$products_root/Debug-iphonesimulator/BooksAndVocab.app"
  unit_bundle="$app_bundle/PlugIns/BooksAndVocabTests.xctest"
  ui_bundle="$products_root/Debug-iphonesimulator/BooksAndVocabUITests-Runner.app"
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

# A build-for-testing that is interrupted (INT/TERM) or fails mid-write leaves
# the product bundle DIRECTORIES in place but their contents incomplete, which
# the -d checks above cannot distinguish from a good build. The sentinel below is
# written (under the build lock) ONLY after a build verifiably completes, so hit
# detection and the rebuild double-check require it — a poisoned/partial cache is
# never treated as ready and is rebuilt instead of served to parallel agents.
IOS_TEST_CACHE_SENTINEL=".kg-test-cache-complete"
ios_test_cache_is_complete() {
  local xctestrun_path="$1"
  [[ -n "$DERIVED_DATA_ROOT" && -f "$DERIVED_DATA_ROOT/$IOS_TEST_CACHE_SENTINEL" ]] || return 1
  ios_test_cached_products_ready "$xctestrun_path"
}

# --- Build -only-testing flags ---
ONLY_FLAGS=()
TEST_TARGET="BooksAndVocabTests"
TEST_DIR="$PROJECT_ROOT/ios/BooksAndVocabTests"

case "$TEST_SCOPE" in
  unit)
    TEST_TARGET="BooksAndVocabTests"
    TEST_DIR="$PROJECT_ROOT/ios/BooksAndVocabTests"
    TEST_SCHEME="BooksAndVocabUnitTests"
    ;;
  ui)
    TEST_TARGET="BooksAndVocabUITests"
    TEST_DIR="$PROJECT_ROOT/ios/BooksAndVocabUITests"
    TEST_SCHEME="BooksAndVocabUITests"
    ;;
  all)
    TEST_TARGET=""
    TEST_SCHEME="BooksAndVocab"
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

if [[ -n "$UI_FIXTURE_DATASET_NAME" && -n "$UI_FIXTURE_DATASET_FILE" ]]; then
  echo "[ios_test] error: choose either --dataset or --dataset-file" >&2
  exit 1
fi
if [[ -n "$UI_FIXTURE_DATASET_NAME" ]]; then
  UI_FIXTURE_DATASET_FILE="$PROJECT_ROOT/ops/fixtures/ui_worlds/$UI_FIXTURE_DATASET_NAME.json"
fi
if [[ "$TEST_SCOPE" == "ui" && -z "$UI_FIXTURE_DATASET_FILE" && "$LIST_ONLY" -eq 0 && -z "$TEST_CACHE_ACTION" ]]; then
  echo "[ios_test] error: --ui requires --dataset <name> or --dataset-file <path> (UI World is the single source of truth)" >&2
  available_worlds="$(cd "$PROJECT_ROOT/ops/fixtures/ui_worlds" 2>/dev/null && ls -- *.json 2>/dev/null | sed 's/\.json$//' | paste -sd ' ' - || true)"
  echo "[ios_test] available datasets (ops/fixtures/ui_worlds/): ${available_worlds:-none}" >&2
  exit 1
fi
if [[ -n "$UI_FIXTURE_DATASET_FILE" ]]; then
  # 限 --ui：UI World env 會被 app 內 FixtureDatasetStore 全程讀取。
  if [[ "$TEST_SCOPE" != "ui" ]]; then
    echo "[ios_test] error: --dataset/--dataset-file requires --ui" >&2
    exit 1
  fi
  # --list / cache action 不會執行 staging，silent ignore 會誤導「dataset 已生效」。
  if [[ "$LIST_ONLY" -eq 1 || -n "$TEST_CACHE_ACTION" ]]; then
    echo "[ios_test] error: --dataset/--dataset-file cannot be combined with --list or cache actions (dataset only applies to an actual test run)" >&2
    exit 1
  fi
  if [[ ! -f "$UI_FIXTURE_DATASET_FILE" ]]; then
    echo "[ios_test] error: dataset file not found: $UI_FIXTURE_DATASET_FILE" >&2
    exit 1
  fi
  if ! "$UV_BIN" run --python 3.13 python "$PROJECT_ROOT/ops/ui_world_manifest.py" validate "$UI_FIXTURE_DATASET_FILE" --label "UITest UI World dataset" >/dev/null; then
    exit 1
  fi
  UI_FIXTURE_DATASET_B64="$(base64 <"$UI_FIXTURE_DATASET_FILE" | tr -d '\n')"
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
  # Tolerant resolution: agents routinely pass a type/suite name ("FooTests")
  # instead of the on-disk filename ("FooTests.swift"), since Swift convention
  # makes them identical bar the extension. Fall back to appending .swift, then
  # to a stem search under the test dir, before failing.
  if [[ ! -f "$FILE_PATH" ]]; then
    if [[ "$FILE_PATH" != *.swift && -f "$FILE_PATH.swift" ]]; then
      FILE_PATH="$FILE_PATH.swift"
    else
      stem="$(basename "$TEST_FILE")"; stem="${stem%.swift}"
      stem_matches=()
      while IFS= read -r m; do stem_matches+=("$m"); done < <(find "$TEST_DIR" -type f -name "$stem.swift" 2>/dev/null)
      if [[ "${#stem_matches[@]}" -gt 1 ]]; then
        echo "[ios_test] '$TEST_FILE' is ambiguous — ${#stem_matches[@]} files match '$stem.swift':" >&2
        printf '  %s\n' "${stem_matches[@]}" >&2
        echo "[ios_test] pass a path-qualified --file to disambiguate" >&2
        exit 1
      fi
      [[ "${#stem_matches[@]}" -eq 1 ]] && FILE_PATH="${stem_matches[0]}"
    fi
  fi
  [[ -f "$FILE_PATH" ]] || { echo "[ios_test] test file not found: $TEST_FILE (tried .swift suffix and stem search under $TEST_DIR)" >&2; exit 1; }
  UI_TEST_FLOW_ID="$(basename "$FILE_PATH" .swift)"
  while IFS= read -r flag; do
    [[ -n "$flag" ]] && ONLY_FLAGS+=("$flag")
  done < <(discover_file_only_flags "$FILE_PATH" "" "$TEST_TARGET")
  if [[ ${#ONLY_FLAGS[@]} -eq 0 ]]; then
    echo "[ios_test] no tests discovered in file '$TEST_FILE'" >&2
    exit 1
  fi
  echo "[ios_test] matched ${#ONLY_FLAGS[@]} tests in file '$TEST_FILE' ($TEST_TARGET)"
elif [[ -n "$GREP_PATTERN" ]]; then
  UI_TEST_FLOW_ID="$GREP_PATTERN"
  # Auto-discover test funcs matching the pattern, attributing each func to its
  # OWN enclosing top-level container (struct / @Suite struct / class). See
  # lib/ios_test_discovery.sh for the discovery contract.
  while IFS= read -r flag; do
    [[ -n "$flag" ]] && ONLY_FLAGS+=("$flag")
  done < <(discover_only_flags "$TEST_DIR" "$GREP_PATTERN" "$TEST_TARGET")
  if [[ ${#ONLY_FLAGS[@]} -eq 0 ]]; then
    echo "[ios_test] no tests matching pattern '$GREP_PATTERN'" >&2
    echo "[ios_test] 注意：-g 匹配測試「方法名」（func/@Test）與「suite/容器名」（@Suite struct/class），不匹配檔名。" >&2
    echo "[ios_test] 確認名稱 → --list 搭配更寬的 pattern；單一檔案 → --file <TypeName>（.swift 可省）。" >&2
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

if [[ -z "$UI_TEST_FLOW_ID" ]]; then
  UI_TEST_FLOW_ID="$TEST_TARGET"
fi

if [[ "$TEST_SCOPE" == "ui" && -z "$UI_LAUNCH_PROFILE" ]]; then
  UI_LAUNCH_PROFILE="ui-smoke"
fi

if [[ "$LAUNCH_BENCHMARK" -eq 1 ]]; then
  TEST_SCOPE="ui"
  TEST_TARGET="BooksAndVocabUITests"
  TEST_DIR="$PROJECT_ROOT/ios/BooksAndVocabUITests"
  TEST_SCHEME="BooksAndVocabUITests"
  ONLY_FLAGS=("-only-testing:BooksAndVocabUITests/BooksAndVocabUITests/testLaunchPerformance")
  if [[ -z "$UI_LAUNCH_PROFILE" ]]; then
    UI_LAUNCH_PROFILE="standard"
  fi
fi
UI_TEST_VARIANT_ID="$(build_ui_test_variant_id)"

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
UI_TEST_SCREENSHOT_DIR=""
UI_TEST_CONTACT_SHEET=""
UI_TEST_SCREENSHOT_MANIFEST=""
UI_TEST_VIDEO=""
UI_TEST_VIDEO_PID=""
TEST_DEVICE_LOCK_HELD=0
TEST_DEVICE_LOCK_FILE=""
DEVICE_RUN_LOCK_WAIT_MS=0
test_log_line_count() {
  local log_path="${1:-${TMPOUT:-}}"
  [[ -n "$log_path" && -f "$log_path" ]] || return 1
  wc -l < "$log_path" | tr -d ' '
}
write_missing_test_log_marker() {
  local log_path="${1:-${TMPOUT:-}}"
  [[ -n "$log_path" ]] || return 1
  cat >"$log_path" <<EOF
[ios_test] error: xcodebuild log path disappeared before diagnostics could read it
[ios_test] log=$log_path
EOF
}
cleanup() {
  if [[ -n "${CURRENT_XCODE_PID:-}" ]] && kill -0 "$CURRENT_XCODE_PID" 2>/dev/null; then
    kill "$CURRENT_XCODE_PID" 2>/dev/null || true
  fi
  if [[ -n "${UI_TEST_VIDEO_PID:-}" ]] && kill -0 "$UI_TEST_VIDEO_PID" 2>/dev/null; then
    kill -INT "$UI_TEST_VIDEO_PID" 2>/dev/null || true
  fi
  release_test_device_lock
  release_build_lock   # ownership-guarded; only removes the lock if we still hold it
  if [[ -n "${LEASED_DEVICE:-}" ]]; then
    "$IOS_OPS" simulator release --device "$LEASED_DEVICE" --owner-token "$LEASE_OWNER_TOKEN" >/dev/null 2>&1 || true
    LEASED_DEVICE=''
  fi
  if [[ "$PRESERVE_TMPOUT" -eq 0 ]]; then
    rm -f "${TMPOUT:-}"
  fi
  rm -f "${STAGED_DATASET_XCTESTRUN:-}"
}

# Fine-grained build lock (shared /tmp/kg-ios-build.lock with ios_build.sh).
# Held ONLY around build-for-testing — the sole writer of the shared DerivedData
# — and released before test execution. Parallel agents running
# test-without-building read immutable, content-keyed cache products on their own
# leased simulators, so they no longer queue behind each other's test runs (which
# was measured at 246s/309s lockWait for 3 concurrent runs). See
# docs/reference/ios_deriveddata_policy.md.
LOCK_HELD=0
LOCK_WAIT_MS=0
acquire_build_lock() {
  [[ "$LOCK_HELD" -eq 1 ]] && return 0
  echo "[ios_test] caller=$CALLER waiting for build lock..."
  local waited=0 lock_wait_start_ms holder_pid
  lock_wait_start_ms="$(ios_test_now_ms)"
  while ! shlock -f "$LOCK_FILE" -p $$; do
    holder_pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [[ -n "$holder_pid" ]] && ! kill -0 "$holder_pid" 2>/dev/null; then
      # Re-check the lock still holds the SAME dead PID before stealing — another
      # waiter may have acquired it fresh between our cat and rm (steal only our
      # observed dead lock, never a live one).
      if [[ "$(cat "$LOCK_FILE" 2>/dev/null || echo "")" == "$holder_pid" ]]; then
        echo "[ios_test] stale lock (pid=$holder_pid dead), stealing"
        rm -f "$LOCK_FILE"
      fi
      continue
    fi
    sleep "$POLL_INTERVAL"
    waited=$((waited + POLL_INTERVAL))
    if [[ $waited -ge $TIMEOUT ]]; then
      echo "[ios_test] error: timed out after ${TIMEOUT}s waiting for build lock" >&2
      exit 1
    fi
  done
  LOCK_HELD=1
  LOCK_WAIT_MS=$(( LOCK_WAIT_MS + ($(ios_test_now_ms) - lock_wait_start_ms) ))
  echo "[ios_test] build lock acquired lockWaitMs=$LOCK_WAIT_MS"
}
release_build_lock() {
  [[ "$LOCK_HELD" -eq 1 ]] || return 0
  # Only remove the lock if we still own it — another agent may have acquired it
  # after we released, and we must never delete someone else's lock.
  [[ "$(cat "$LOCK_FILE" 2>/dev/null || echo "")" == "$$" ]] && rm -f "$LOCK_FILE"
  LOCK_HELD=0
}

destination_requires_device_lock() {
  [[ "$DESTINATION" == *"platform=iOS Simulator"* ]]
}

env_flag_enabled() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

running_in_isolation_enforced_context() {
  env_flag_enabled "${KG_IOS_TEST_REQUIRE_ISOLATED_SIM:-}" && return 0
  env_flag_enabled "${CI:-}" && return 0
  [[ "$PROJECT_ROOT" == *"/.codex/worktrees/"* ]] && return 0
  [[ -n "${WORKTREE_BRANCH:-}" ]] && return 0
  return 1
}

should_require_isolated_simulator() {
  destination_requires_device_lock || return 1
  [[ -n "$DEVICE_OVERRIDE" || -n "$DESTINATION_OVERRIDE" || "$AUTO_LEASE" -eq 1 ]] && return 1
  [[ "$LIST_ONLY" -eq 1 ]] && return 1
  case "${TEST_CACHE_ACTION:-}" in
    status|prepare|clean) return 1 ;;
  esac
  env_flag_enabled "${KG_IOS_TEST_ALLOW_SHARED_SIM:-}" && return 1
  running_in_isolation_enforced_context
}

enforce_isolated_simulator_or_fail() {
  should_require_isolated_simulator || return 0
  cat >&2 <<EOF
[ios_test] error: shared default simulator is disallowed in agent/CI worktree runs
[ios_test] requested destination=$DESTINATION
[ios_test] fix: pass --lease, --device <udid|name>, or --destination '<xcodebuild destination>'
[ios_test] override: KG_IOS_TEST_ALLOW_SHARED_SIM=1
EOF
  exit 1
}

device_lock_key() {
  local raw_selector="${SIMULATOR_BOOT_SELECTOR:-$DESTINATION}"
  printf '%s' "$raw_selector" | shasum -a 256 | awk '{print $1}'
}

acquire_test_device_lock() {
  [[ "$TEST_DEVICE_LOCK_HELD" -eq 1 ]] && return 0
  destination_requires_device_lock || return 0
  local waited=0 lock_wait_start_ms holder_pid lock_key
  lock_key="$(device_lock_key)"
  TEST_DEVICE_LOCK_FILE="/tmp/kg-ios-test-device-${lock_key}.lock"
  echo "[ios_test] caller=$CALLER waiting for device lock selector=\"${SIMULATOR_BOOT_SELECTOR:-$DESTINATION}\"..."
  lock_wait_start_ms="$(ios_test_now_ms)"
  while ! shlock -f "$TEST_DEVICE_LOCK_FILE" -p $$; do
    holder_pid=$(cat "$TEST_DEVICE_LOCK_FILE" 2>/dev/null || echo "")
    if [[ -n "$holder_pid" ]] && ! kill -0 "$holder_pid" 2>/dev/null; then
      if [[ "$(cat "$TEST_DEVICE_LOCK_FILE" 2>/dev/null || echo "")" == "$holder_pid" ]]; then
        echo "[ios_test] stale device lock (pid=$holder_pid dead), stealing"
        rm -f "$TEST_DEVICE_LOCK_FILE"
      fi
      continue
    fi
    sleep "$POLL_INTERVAL"
    waited=$((waited + POLL_INTERVAL))
    if [[ $waited -ge $TIMEOUT ]]; then
      echo "[ios_test] error: timed out after ${TIMEOUT}s waiting for device lock" >&2
      exit 1
    fi
  done
  TEST_DEVICE_LOCK_HELD=1
  DEVICE_RUN_LOCK_WAIT_MS=$(( DEVICE_RUN_LOCK_WAIT_MS + ($(ios_test_now_ms) - lock_wait_start_ms) ))
  echo "[ios_test] device lock acquired deviceRunLockWaitMs=$DEVICE_RUN_LOCK_WAIT_MS"
}

release_test_device_lock() {
  [[ "$TEST_DEVICE_LOCK_HELD" -eq 1 ]] || return 0
  [[ "$(cat "$TEST_DEVICE_LOCK_FILE" 2>/dev/null || echo "")" == "$$" ]] && rm -f "$TEST_DEVICE_LOCK_FILE"
  TEST_DEVICE_LOCK_HELD=0
}
trap cleanup EXIT INT TERM

# Auto-lease a pool simulator for this run (parallel agents). Engaged by --lease
# / KG_IOS_TEST_AUTOLEASE only when no explicit device/destination was given —
# explicit targeting always wins. Done after the trap is armed so the lease is
# always released on exit, and after the validation gates so we never lease for
# a run that would have errored out anyway.
if [[ "$AUTO_LEASE" -eq 1 && -z "$DEVICE_OVERRIDE" && -z "$DESTINATION_OVERRIDE" \
      && "$TEST_CACHE_ACTION" != "status" && "$TEST_CACHE_ACTION" != "clean" ]]; then
  lease_json="$(
    KG_IOS_SIM_LEASE_OWNER_PID=$$ \
    KG_IOS_SIM_LEASE_OWNER_TOKEN="$LEASE_OWNER_TOKEN" \
      "$IOS_OPS" simulator lease --json 2>/dev/null
  )"
  LEASED_DEVICE="$(jq -r '.udid // empty' <<<"$lease_json" 2>/dev/null)"
  if [[ -z "$LEASED_DEVICE" ]]; then
    echo "[ios_test] error: --lease requested but simulator pool is exhausted" >&2
    exit 1
  fi
  echo "[ios_test] leased simulator udid=$LEASED_DEVICE"
  DESTINATION="platform=iOS Simulator,id=$LEASED_DEVICE"
  SIMULATOR_BOOT_SELECTOR="$LEASED_DEVICE"
fi

enforce_isolated_simulator_or_fail

echo "[ios_test] caller=$CALLER scope=$TEST_SCOPE running ${#ONLY_FLAGS[@]} selector(s) (0=scheme all targets)..."
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
lease_json=""
boot_simulator_if_needed() {
  local boot_start_ms boot_end_ms
  boot_start_ms="$(ios_test_now_ms)"
  echo "[ios_test] simulator ensure-booted — device=\"$SIMULATOR_BOOT_SELECTOR\" (up to ~30s if cold-starting from scratch)..."
  "$IOS_OPS" simulator ensure-booted --device "$SIMULATOR_BOOT_SELECTOR"
  boot_end_ms="$(ios_test_now_ms)"
  BOOT_MS=$(( boot_end_ms - boot_start_ms ))
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
  if ios_test_cache_is_complete "$xctestrun_path"; then
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
        # Guard with `|| build_exit=$?`: this runs under `set -e`, so a non-zero
        # return would abort before we can build the error payload below.
        build_exit=0
        rebuild_test_cache "$build_log" "$build_result_bundle" || build_exit=$?
        if [[ "$build_exit" -eq 0 ]]; then
          xctestrun_path="$(ios_test_find_xctestrun "$derived_root" || true)"
          products_ready=false
          if ios_test_cache_is_complete "$xctestrun_path"; then
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

should_rebuild_after_test_without_building_failure() {
  grep -qE '^\*\* TEST( EXECUTE)? FAILED' "$TMPOUT" 2>/dev/null && return 1
  grep -qE 'Failed to read xctestrun file|no \.xctestrun artifact|cached test products are incomplete|failed to load test bundle|failed to create test runner|test runner exited before starting|unable to find.*xctestrun|xctestrun file.*(missing|invalid|not found)' "$TMPOUT" 2>/dev/null
}

# test-without-building 不會把 xcodebuild 行內 env 傳進 test runner process——
# xctestrun 的 TestingEnvironmentVariables 才是 runner env 的注入面（catalog
# pipeline 同法）。複製 base xctestrun 再 upsert，不污染共享 build cache 原檔；
# 副本必須與原檔同目錄（__TESTROOT__ 相對於 xctestrun 所在目錄解析）。
# 不可經 command substitution 呼叫：cleanup trap 靠父 shell 的
# STAGED_DATASET_XCTESTRUN 刪檔，subshell 賦值傳不回來（曾為死碼）。
stage_fixture_dataset_xctestrun() {
  local base_path="$1" staged_path="$2"
  cp "$base_path" "$staged_path" || return 1
  local key=':TestConfigurations:0:TestTargets:0:TestingEnvironmentVariables:KG_FIXTURE_DATASET_B64'
  if ! /usr/libexec/PlistBuddy -c "Set $key $UI_FIXTURE_DATASET_B64" "$staged_path" 2>/dev/null; then
    /usr/libexec/PlistBuddy -c "Add $key string $UI_FIXTURE_DATASET_B64" "$staged_path" || return 1
  fi
}

run_xcodebuild_test_without_building_once() {
  local xctestrun_path="$1"
  local xcode_pid last_line current_line heartbeat_at tick_at emitted_this_loop now elapsed recent_event xcode_start_ms xcode_end_ms log_missing
  if [[ -n "$UI_FIXTURE_DATASET_B64" ]]; then
    # 父 shell 先賦值 STAGED_DATASET_XCTESTRUN 再 cp：即使 staging 半途失敗，
    # cleanup trap 也能刪掉殘檔。.scoped.xctestrun 字尾使 ios_test_find_xctestrun
    # 永不撿到副本（SIGKILL 漏刪也不污染後續 discovery）；同 PID retry 時 cp
    # 覆寫同名檔，不累積。
    STAGED_DATASET_XCTESTRUN="${xctestrun_path%.xctestrun}_dataset_$$.scoped.xctestrun"
    if ! stage_fixture_dataset_xctestrun "$xctestrun_path" "$STAGED_DATASET_XCTESTRUN"; then
      echo "[ios_test] error: failed to stage fixture dataset into xctestrun" >&2
      return 1
    fi
    xctestrun_path="$STAGED_DATASET_XCTESTRUN"
    echo "[ios_test] fixture dataset staged: $(basename "$xctestrun_path") (KG_FIXTURE_DATASET_B64 ← ${UI_FIXTURE_DATASET_FILE})"
  fi
  acquire_test_device_lock
  start_ui_test_recording
  xcode_start_ms="$(ios_test_now_ms)"
  KG_UI_TEST_APP_ARGS_JSON="$(ui_test_launch_args_json)" \
  KG_UI_TEST_SCREENSHOT_DIR="$UI_TEST_SCREENSHOT_DIR" \
  xcodebuild test-without-building \
    -xctestrun "$xctestrun_path" \
    -destination "$DESTINATION" \
    ${COVERAGE_XCODEBUILD_ARGS[@]+"${COVERAGE_XCODEBUILD_ARGS[@]}"} \
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
  log_missing=0
  heartbeat_at=$(date +%s)
  tick_at=$(date +%s)
  while kill -0 "$xcode_pid" 2>/dev/null; do
    if ! current_line="$(test_log_line_count "$TMPOUT")"; then
      log_missing=1
      echo "[ios_test] warning: xcodebuild log path disappeared while test was running: $TMPOUT" >&2
      break
    fi
    emitted_this_loop=0
    if [[ "$current_line" -gt "$last_line" ]]; then
      emit_new_test_output "$((last_line + 1))" "$current_line"
      last_line="$current_line"
      emitted_this_loop=1
    fi

    now=$(date +%s)
    if [[ $((now - heartbeat_at)) -ge 30 ]]; then
      # Detail heartbeat every 30s: which test is currently running.
      elapsed=$((now - START))
      recent_event="$(last_test_event)"
      [[ -n "$recent_event" ]] || recent_event="xcodebuild still running"
      echo "[ios_test] … still running (${elapsed}s, pid=$xcode_pid, log=$TMPOUT) — last: $recent_event"
      heartbeat_at="$now"
      tick_at="$now"
    elif [[ "$emitted_this_loop" -eq 0 && $((now - tick_at)) -ge 3 ]]; then
      # Short keep-alive tick every 3s, but only when no test output was printed
      # this loop (a slow/hung single test) — so it never floods a fast run.
      printf '[ios_test] ··· %ds\n' "$((now - START))"
      tick_at="$now"
    fi
    sleep 2
  done

  wait "$xcode_pid"
  local status=$?
  xcode_end_ms="$(ios_test_now_ms)"
  TEST_INVOCATION_MS=$(( xcode_end_ms - xcode_start_ms ))
  XCODEBUILD_MS=$(( BUILD_FOR_TESTING_MS + TEST_INVOCATION_MS ))
  CURRENT_XCODE_PID=""
  stop_ui_test_recording
  release_test_device_lock
  if ! current_line="$(test_log_line_count "$TMPOUT")"; then
    [[ "$log_missing" -eq 1 ]] && write_missing_test_log_marker "$TMPOUT" || true
    current_line="$(test_log_line_count "$TMPOUT" 2>/dev/null || echo 0)"
  fi
  if [[ "$current_line" -gt "$last_line" ]]; then
    emit_new_test_output "$((last_line + 1))" "$current_line"
  fi
  return "$status"
}

rebuild_test_cache() {
  local build_log="$1" build_result_bundle="$2"
  local build_start_ms build_end_ms
  mkdir -p "$DERIVED_DATA_ROOT"
  # Acquire the build lock ONLY for the write to shared DerivedData, and release
  # the moment the build finishes — test execution runs unlocked.
  acquire_build_lock
  # Keyed caches grow unbounded (one full DerivedData per config hash; 94G on
  # 2026-06-10 → exit=73 disk full). Evict under the build lock — unlocked
  # readers are protected by resolve-time touch + the min-age window.
  kg_ios_cache_evict "$TEST_CACHE_ROOT" "$(basename "$DERIVED_DATA_ROOT")"
  # Double-checked locking: another agent may have built this exact (content-keyed)
  # cache while we waited for the lock. If the products are now ready, skip the
  # rebuild — both to avoid redundant work and, critically, to avoid overwriting
  # products another agent may already be reading during its unlocked test run.
  local _xctestrun build_rc
  _xctestrun="$(ios_test_find_xctestrun "$DERIVED_DATA_ROOT" 2>/dev/null || true)"
  if [[ -n "$_xctestrun" ]] && ios_test_cache_is_complete "$_xctestrun"; then
    # Waiter path: another agent built this exact cache while we held/waited for
    # the lock. We skipped the rebuild, so this run is a (lock-serialized) HIT,
    # not a builder — let the caller label cacheStatus truthfully.
    REBUILD_DID_BUILD=0
    release_build_lock
    return 0
  fi
  REBUILD_DID_BUILD=1
  # A previous build may have been interrupted, leaving a partial cache with no
  # sentinel. Clear the stale completion marker before rebuilding so a crash
  # mid-build below can never leave an old sentinel pointing at fresh-but-partial
  # products.
  rm -f "$DERIVED_DATA_ROOT/$IOS_TEST_CACHE_SENTINEL" 2>/dev/null || true
  # Separate baseline from ios_build.sh because build-for-testing also compiles
  # test targets and has a higher event count (~1390 vs ~1100 for a plain build).
  local bft_baseline="$DERIVED_DATA_ROOT/kg_build_for_testing.events_baseline"
  build_start_ms="$(ios_test_now_ms)"
  local bft_start_s bft_monitor_pid
  bft_start_s=$(date +%s)
  bft_monitor_pid=$(start_build_monitor "$build_log" "$bft_baseline" "[ios_test][build-for-testing]" "$bft_start_s")
  xcodebuild build-for-testing \
    -project "$XCODEPROJ" \
    -scheme "$TEST_SCHEME" \
    -destination "$DESTINATION" \
    ${COVERAGE_XCODEBUILD_ARGS[@]+"${COVERAGE_XCODEBUILD_ARGS[@]}"} \
    -parallel-testing-enabled NO \
    -test-timeouts-enabled YES \
    -default-test-execution-time-allowance 60 \
    -maximum-test-execution-time-allowance 120 \
    -derivedDataPath "$DERIVED_DATA_ROOT" \
    -resultBundlePath "$build_result_bundle" \
    >"$build_log" 2>&1
  build_rc=$?
  kill "$bft_monitor_pid" 2>/dev/null || true
  wait "$bft_monitor_pid" 2>/dev/null || true
  build_end_ms="$(ios_test_now_ms)"
  BUILD_FOR_TESTING_MS=$(( build_end_ms - build_start_ms ))
  local bft_compile_count
  bft_compile_count=$(count_compile_events "$build_log")
  echo "[ios_test][build-for-testing] finished (${BUILD_FOR_TESTING_MS}ms, ${bft_compile_count} compile events, exit=$build_rc)"
  if [[ "$build_rc" -eq 0 && "$bft_compile_count" -gt 0 ]]; then
    echo "$bft_compile_count" > "$bft_baseline"
  fi
  # Mark the cache complete ONLY when the build exited 0 AND produced ready
  # products — written while still holding the lock so the sentinel is atomic
  # with the build from a concurrent agent's view. An interrupted build never
  # reaches here (cleanup runs instead), so no sentinel is written and the next
  # agent rebuilds.
  if [[ "$build_rc" -eq 0 ]]; then
    _xctestrun="$(ios_test_find_xctestrun "$DERIVED_DATA_ROOT" 2>/dev/null || true)"
    if [[ -n "$_xctestrun" ]] && ios_test_cached_products_ready "$_xctestrun"; then
      : > "$DERIVED_DATA_ROOT/$IOS_TEST_CACHE_SENTINEL"
    fi
  fi
  release_build_lock
  # Propagate the real build-for-testing exit code. A compile failure (build_rc
  # != 0) MUST surface here so callers print the build log (the actual compiler
  # diagnostics) instead of the misleading "no .xctestrun artifact" message —
  # fail loud, no silent fallback.
  return "$build_rc"
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

prepare_ui_step_screenshot_dir() {
  UI_TEST_SCREENSHOT_DIR=""
  UI_TEST_CONTACT_SHEET=""
  UI_TEST_QUICK4_SHEET=""
  UI_TEST_SCREENSHOT_MANIFEST=""
  UI_TEST_VIDEO=""
  [[ "$TEST_SCOPE" == "ui" || "$TEST_SCOPE" == "all" ]] || return 0
  UI_TEST_SCREENSHOT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kg_ios_ui_steps.XXXXXX")"
}

# Explicit simulator UDID for this run, when one exists: leased pool sim, or a
# --device/--destination that carries `id=`. Name-based default destinations
# return 1 (no recording / no device field) — `simctl io booted` would be
# ambiguous with several pool sims booted.
resolve_run_device_udid() {
  if [[ -n "${LEASED_DEVICE:-}" ]]; then
    printf '%s\n' "$LEASED_DEVICE"
    return 0
  fi
  case "${DESTINATION:-}" in
    *"id="*) printf '%s\n' "${DESTINATION##*id=}"; return 0 ;;
  esac
  return 1
}

# Screen recording around the UI-scope test invocation. The mp4 lands next to
# the step screenshots so the whole visual-evidence trio+video shares one dir.
start_ui_test_recording() {
  [[ -n "${UI_TEST_SCREENSHOT_DIR:-}" && -d "${UI_TEST_SCREENSHOT_DIR:-}" ]] || return 0
  local udid
  if ! udid="$(resolve_run_device_udid)"; then
    echo "[ios_test][ui-video] skip: no explicit simulator udid (use --lease or --device <udid>)"
    return 0
  fi
  UI_TEST_VIDEO="$UI_TEST_SCREENSHOT_DIR/run_recording.mp4"
  xcrun simctl io "$udid" recordVideo --codec h264 --force "$UI_TEST_VIDEO" >/dev/null 2>&1 &
  UI_TEST_VIDEO_PID=$!
  echo "[ios_test][ui-video] recording udid=$udid pid=$UI_TEST_VIDEO_PID out=$UI_TEST_VIDEO"
}

stop_ui_test_recording() {
  [[ -n "${UI_TEST_VIDEO_PID:-}" ]] || return 0
  if kill -0 "$UI_TEST_VIDEO_PID" 2>/dev/null; then
    # simctl finalizes the mp4 container on SIGINT; give it a bounded window
    # before escalating, else a wedged recorder would hang the verdict path.
    kill -INT "$UI_TEST_VIDEO_PID" 2>/dev/null || true
    local waited=0
    while kill -0 "$UI_TEST_VIDEO_PID" 2>/dev/null && [[ "$waited" -lt 100 ]]; do
      sleep 0.1
      waited=$((waited + 1))
    done
    kill -0 "$UI_TEST_VIDEO_PID" 2>/dev/null && kill -9 "$UI_TEST_VIDEO_PID" 2>/dev/null || true
  fi
  wait "$UI_TEST_VIDEO_PID" 2>/dev/null || true
  UI_TEST_VIDEO_PID=""
  if [[ -n "${UI_TEST_VIDEO:-}" && -s "${UI_TEST_VIDEO:-}" ]]; then
    echo "[ios_test][ui-video] saved $UI_TEST_VIDEO"
  else
    if [[ -n "${UI_TEST_VIDEO:-}" ]]; then
      echo "[ios_test][ui-video] warning: recording missing or empty out=$UI_TEST_VIDEO" >&2
    fi
    UI_TEST_VIDEO=""
  fi
}

# Move the finalized recording out of the mktemp dir into the repo archive
# (build/snapshots/uitest-videos/) and repoint UI_TEST_VIDEO so the verdict's
# artifacts.uiVideo references the stable copy instead of a path the OS will
# reclaim. The catalog review page embeds the archive via its index.json.
archive_ui_test_recording() {
  [[ -n "${UI_TEST_VIDEO:-}" && -s "${UI_TEST_VIDEO:-}" ]] || return 0
  local archived
  if archived="$(uitest_video_archive "$UI_TEST_VIDEO" \
      "$PROJECT_ROOT/build/snapshots/uitest-videos" \
      "$TEST_SCOPE" "$CALLER")" && [[ -n "$archived" ]]; then
    UI_TEST_VIDEO="$archived"
    echo "[ios_test][ui-video] archived $archived"
  else
    echo "[ios_test][ui-video] warning: archive failed, keeping tmp path $UI_TEST_VIDEO" >&2
  fi
}

build_ui_test_review_page() {
  local review_status="${1:-}"
  [[ "$TEST_SCOPE" == "ui" || "$TEST_SCOPE" == "all" ]] || return 0

  local stem
  if [[ -n "${UI_TEST_VIDEO:-}" ]]; then
    stem="$(basename "$UI_TEST_VIDEO" .mp4)"
  else
    stem="$(date -u +%Y%m%d-%H%M%S)-$TEST_SCOPE"
  fi
  UI_TEST_REVIEW_ROOT="$PROJECT_ROOT/build/snapshots/uitest-runs/$stem"
  mkdir -p "$UI_TEST_REVIEW_ROOT"

  if [[ -z "${UI_TEST_SCREENSHOT_DIR:-}" || ! -d "$UI_TEST_SCREENSHOT_DIR" ]]; then
    UI_TEST_SCREENSHOT_DIR="$UI_TEST_REVIEW_ROOT"
  fi
  if [[ -z "${UI_TEST_SCREENSHOT_MANIFEST:-}" || ! -s "$UI_TEST_SCREENSHOT_MANIFEST" ]]; then
    UI_TEST_SCREENSHOT_MANIFEST="$UI_TEST_REVIEW_ROOT/input_review_manifest.json"
    jq -nc --arg flow "$UI_TEST_FLOW_ID" --arg variant "$UI_TEST_VARIANT_ID" \
      '{
        schema:"kg.visual-review.sheet.v1",
        source:"uitest",
        title:$flow,
        variant:$variant,
        items:[]
      }' >"$UI_TEST_SCREENSHOT_MANIFEST"
  fi

  local args=(
    "$SCRIPT_DIR/uitest_review_page.py"
    --screenshot-dir "$UI_TEST_SCREENSHOT_DIR"
    --manifest "$UI_TEST_SCREENSHOT_MANIFEST"
    --out-root "$UI_TEST_REVIEW_ROOT"
    --flow-id "$UI_TEST_FLOW_ID"
    --variant-id "$UI_TEST_VARIANT_ID"
    --test-file "${FILE_PATH:-}"
    --device "$(resolve_run_device_udid 2>/dev/null || true)"
    --log "$TMPOUT"
    --json
  )
  [[ -n "$review_status" ]] && args+=(--status "$review_status")
  [[ -n "${UI_TEST_CONTACT_SHEET:-}" ]] && args+=(--contact-sheet "$UI_TEST_CONTACT_SHEET")
  [[ -n "${UI_TEST_QUICK4_SHEET:-}" ]] && args+=(--quick4-sheet "$UI_TEST_QUICK4_SHEET")
  [[ -n "${UI_TEST_VIDEO:-}" ]] && args+=(--video "$UI_TEST_VIDEO")

  local payload
  if payload="$("${args[@]}" 2>/dev/null)" && [[ -n "$payload" ]]; then
    UI_TEST_REVIEW_HTML="$(printf '%s' "$payload" | jq -r '.html // empty' 2>/dev/null || true)"
    echo "[ios_test][ui-review] html=$UI_TEST_REVIEW_HTML"
  else
    echo "[ios_test][ui-review] warning: failed to build standalone UIreview root=$UI_TEST_REVIEW_ROOT" >&2
    UI_TEST_REVIEW_ROOT=""
    UI_TEST_REVIEW_HTML=""
  fi
}

build_ui_step_contact_sheet() {
  [[ -n "${UI_TEST_SCREENSHOT_DIR:-}" && -d "$UI_TEST_SCREENSHOT_DIR" ]] || return 0
  if ! compgen -G "$UI_TEST_SCREENSHOT_DIR/*.png" >/dev/null; then
    export_ui_step_attachments_from_xcresult
  fi
  compgen -G "$UI_TEST_SCREENSHOT_DIR/*.png" >/dev/null || return 0

  UI_TEST_SCREENSHOT_MANIFEST="$UI_TEST_SCREENSHOT_DIR/review_manifest.json"
  UI_TEST_CONTACT_SHEET="$UI_TEST_SCREENSHOT_DIR/contact_sheet.png"
  if "$SCRIPT_DIR/catalog_contact_sheet.py" "$UI_TEST_SCREENSHOT_DIR" \
      --source uitest \
      --appearance light \
      --cols 3 \
      --cell-width 260 \
      --out "$UI_TEST_CONTACT_SHEET" \
      --manifest-out "$UI_TEST_SCREENSHOT_MANIFEST" \
      --json >/dev/null 2>&1; then
    echo "[ios_test][ui-steps] screenshots=$UI_TEST_SCREENSHOT_DIR contactSheet=$UI_TEST_CONTACT_SHEET"
  else
    echo "[ios_test][ui-steps] warning: failed to build contact sheet dir=$UI_TEST_SCREENSHOT_DIR" >&2
    UI_TEST_CONTACT_SHEET=""
    UI_TEST_SCREENSHOT_MANIFEST=""
    return 0
  fi

  # Quick visual summary — four evenly-spaced steps in one row, large cells —
  # so agents can eyeball the flow without opening the full sheet.
  UI_TEST_QUICK4_SHEET="$UI_TEST_SCREENSHOT_DIR/quick4_contact_sheet.png"
  if "$SCRIPT_DIR/catalog_contact_sheet.py" "$UI_TEST_SCREENSHOT_DIR" \
      --source uitest \
      --appearance light \
      --take evenly:4 \
      --cols 4 \
      --cell-width 380 \
      --out "$UI_TEST_QUICK4_SHEET" \
      --json >/dev/null 2>&1; then
    echo "[ios_test][ui-steps] quick4=$UI_TEST_QUICK4_SHEET"
  else
    echo "[ios_test][ui-steps] warning: failed to build quick4 sheet dir=$UI_TEST_SCREENSHOT_DIR" >&2
    UI_TEST_QUICK4_SHEET=""
  fi
}

export_ui_step_attachments_from_xcresult() {
  [[ -n "${RESULT_BUNDLE:-}" && -d "$RESULT_BUNDLE" ]] || return 0
  [[ -n "${UI_TEST_SCREENSHOT_DIR:-}" && -d "$UI_TEST_SCREENSHOT_DIR" ]] || return 0

  local attachment_dir
  attachment_dir="$(mktemp -d "${TMPDIR:-/tmp}/kg_ios_ui_attachments.XXXXXX")"
  if ! xcrun xcresulttool export attachments \
      --path "$RESULT_BUNDLE" \
      --output-path "$attachment_dir" >/dev/null 2>&1; then
    rm -rf "$attachment_dir"
    return 0
  fi

  if ! uv run --python 3.13 python - "$attachment_dir" "$UI_TEST_SCREENSHOT_DIR" <<'PY'
import json
import re
import shutil
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
manifest = source / "manifest.json"
if not manifest.exists():
    raise SystemExit(0)

seen: set[str] = set()
for test in json.loads(manifest.read_text(encoding="utf-8")):
    for attachment in test.get("attachments", []):
        name = attachment.get("suggestedHumanReadableName", "")
        match = re.match(r"Step ([0-9]{2}-[^_]+).*\.png$", name)
        if not match:
            continue
        step_name = match.group(1)
        if step_name in seen:
            continue
        exported = attachment.get("exportedFileName", "")
        source_file = source / exported
        if not source_file.exists():
            continue
        shutil.copyfile(source_file, target / f"{step_name}.png")
        seen.add(step_name)
PY
  then
    echo "[ios_test][ui-steps] warning: failed to export step attachments from xcresult=$RESULT_BUNDLE" >&2
  fi
  rm -rf "$attachment_dir"
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
# LRU liveness: mark this key as in-use even on the unlocked cache-hit path,
# so a concurrent builder's eviction never removes products mid-read.
[[ -d "$DERIVED_DATA_ROOT" ]] && touch "$DERIVED_DATA_ROOT" 2>/dev/null || true
XCTESTRUN_PATH="$(ios_test_find_xctestrun "$DERIVED_DATA_ROOT" || true)"
while :; do
  [[ -n "$TMPOUT" ]] && rm -f "$TMPOUT"
  TMPOUT=$(mktemp)
  [[ -n "$RESULT_DIR" ]] && rm -rf "$RESULT_DIR"
  RESULT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kg_ios_test_result.XXXXXX")"
  RESULT_BUNDLE="$RESULT_DIR/Test.xcresult"
  prepare_ui_step_screenshot_dir
  set +e
  BUILD_FOR_TESTING_MS=0
  TEST_INVOCATION_MS=0
  if ios_test_cache_is_complete "$XCTESTRUN_PATH"; then
    CACHE_STATUS="hit"
    run_xcodebuild_test_without_building_once "$XCTESTRUN_PATH"
    EXIT_CODE=$?
    if [[ "$EXIT_CODE" -ne 0 ]] && should_rebuild_after_test_without_building_failure; then
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
        # Truthful label: "prepared" only if THIS run did the build; a concurrent
        # agent that waited on the lock and skipped the rebuild (double-check hit)
        # is a "hit", not a builder. Discriminated by REBUILD_DID_BUILD, not by
        # buildForTestingMs.
        if [[ "${REBUILD_DID_BUILD:-1}" -eq 1 ]]; then CACHE_STATUS="prepared"; else CACHE_STATUS="hit"; fi
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
    | jq -r '.counts.effectiveTests // (.counts.passedTests + .counts.failedTests + .counts.expectedFailures) // empty' 2>/dev/null)"
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
  echo "[ios_test] timings cacheStatus=$CACHE_STATUS uiLaunchProfile=${UI_LAUNCH_PROFILE:-standard} deviceRunLockWaitMs=$DEVICE_RUN_LOCK_WAIT_MS bootMs=$BOOT_MS buildForTestingMs=$BUILD_FOR_TESTING_MS testInvocationMs=$TEST_INVOCATION_MS testBodyMs=$TEST_BODY_MS xcresultSessionMs=$XCRESULT_SESSION_MS xcresultHarnessOverheadMs=$XCRESULT_HARNESS_OVERHEAD_MS appLaunchAverageMs=$APP_LAUNCH_AVERAGE_MS appLaunchSamples=$APP_LAUNCH_SAMPLES invocationOverheadMs=$INVOCATION_OVERHEAD_MS xcodebuildMs=$XCODEBUILD_MS totalMs=$TOTAL_MS"
}

COVERAGE_JSON='null'
COVERAGE_VERDICT="not-requested"
COVERAGE_REASON=""
populate_coverage_summary() {
  [[ "$COVERAGE_ENABLED" -eq 1 ]] || return 0
  local coverage_args=("$SCRIPT_DIR/ios_coverage.py" "--xcresult" "$RESULT_BUNDLE" "--target" "$COVERAGE_TARGET" "--json")
  if [[ -n "$COVERAGE_FAIL_UNDER" ]]; then
    coverage_args+=("--fail-under-lines" "$COVERAGE_FAIL_UNDER")
  fi
  local coverage_out coverage_rc=0
  if coverage_out="$(uv run --python 3.13 python "${coverage_args[@]}" 2>/dev/null)"; then
    coverage_rc=0
  else
    coverage_rc=$?
  fi
  if jq -e . >/dev/null 2>&1 <<<"$coverage_out"; then
    COVERAGE_JSON="$(jq -c . <<<"$coverage_out")"
    COVERAGE_VERDICT="$(jq -r '.verdict // "error"' <<<"$COVERAGE_JSON")"
  else
    COVERAGE_JSON="$(jq -nc --arg schema "kg.ios.coverage.v1" --arg error "coverage parser emitted invalid JSON" '{schema:$schema,verdict:"error",summary:{target:null,lineCoverage:null,coveredLines:null,executableLines:null,fileCount:0,lowestFiles:[]},thresholds:{lineCoverage:{failUnder:null}},targets:[],errors:[{key:"coverage-unavailable",status:"error",error:$error}]}')"
    COVERAGE_VERDICT="error"
  fi
  case "$COVERAGE_VERDICT" in
    pass) COVERAGE_REASON="" ;;
    fail) COVERAGE_REASON="coverage-fail-under" ;;
    *) COVERAGE_REASON="coverage-unavailable" ;;
  esac
  jq -r '"[ios][coverage] verdict=\(.verdict) target=\(.summary.target // "unknown") lineCoverage=\(.summary.lineCoverage // "unknown") coveredLines=\(.summary.coveredLines // "unknown") executableLines=\(.summary.executableLines // "unknown") fileCount=\(.summary.fileCount // 0) failUnder=\(.thresholds.lineCoverage.failUnder // "none")"' <<<"$COVERAGE_JSON"
  jq -r '(.summary.lowestFiles // [])[0:3][] | "[ios][coverage][low] file=\(.path // .name) lineCoverage=\(.lineCoverage // "unknown") coveredLines=\(.coveredLines // "unknown") executableLines=\(.executableLines // "unknown")"' <<<"$COVERAGE_JSON"
  return "$coverage_rc"
}

emit_ui_runner_lifecycle() {
  [[ "$TEST_SCOPE" == "ui" || "$TEST_SCOPE" == "all" ]] || return 0
  local device="${SIMULATOR_BOOT_SELECTOR:-}" safe_device screenshot_path
  [[ -n "$device" ]] || return 0

  echo "[ios_test][ui-lifecycle] destination=$DESTINATION device=$device" >&2
  xcrun simctl list devices available 2>/dev/null \
    | grep -F "$device" \
    | sed 's/^/[ios_test][ui-lifecycle] device-state /' >&2 || true
  xcrun simctl spawn "$device" launchctl print user/501/com.apple.testmanagerd 2>/dev/null \
    | awk '
        /state =|pid =|runs =|last exit code =|active count =/ {
          gsub(/^[[:space:]]+/, "", $0)
          print "[ios_test][ui-lifecycle] testmanagerd " $0
        }
      ' >&2 || echo "[ios_test][ui-lifecycle] testmanagerd unavailable" >&2
  xcrun simctl spawn "$device" /bin/ps -axo pid,ppid,stat,comm,args 2>/dev/null \
    | grep -E 'BooksAndVocab|UITests-Runner|testmanagerd' \
    | sed 's/^/[ios_test][ui-lifecycle] process /' >&2 || echo "[ios_test][ui-lifecycle] process none" >&2
  safe_device="$(printf '%s' "$device" | tr -c '[:alnum:]._- ' '_')"
  screenshot_path="${TMPDIR:-/tmp}/kg_ios_ui_lifecycle_${safe_device}_$$.png"
  if xcrun simctl io "$device" screenshot "$screenshot_path" >/dev/null 2>&1; then
    echo "[ios_test][ui-lifecycle] screenshot=$screenshot_path" >&2
  else
    echo "[ios_test][ui-lifecycle] screenshot unavailable" >&2
  fi
}

# Machine-readable verdict file — survives even when stdout/stderr is piped
# (e.g. `ios_test.sh | tail`, where the pipeline's exit code is tail's, not the
# script's). Read this instead of trusting a piped `$?`.
#
# Per-invocation UNIQUE path (multi-session race guard): VERDICT_FILE is
# `kg_ios_test_verdict.<epochTs>-<pid>` (or KG_IOS_VERDICT_FILE when a wrapper
# pins it), so a session can never mistake another session's verdict for its
# own AND the run-metrics source has no concurrent writer (the old
# fixed-path-then-private-copy dance is gone). The historical fixed path stays
# as a last-writer-wins LATEST pointer for `ios_ops runs`. See
# ops/lib/ios_run_verdict.sh.
kg_ios_verdict_init test "$PROJECT_ROOT"
write_json_verdict() {
  local result="$1" exit_code="$2" reason="$3" executed="$4"
  build_ui_test_review_page "$result"
  jq -nc \
    --arg schema "kg.ios.run-verdict.v1" \
    --arg kind "test" \
    --arg result "$result" \
    --arg exit "$exit_code" \
    --arg reason "$reason" \
    --arg caller "$CALLER" \
    --arg cwd "$PROJECT_ROOT" \
    --arg verdictFile "$VERDICT_FILE" \
    --argjson ts "$(date +%s)" \
    --argjson pid "$$" \
    --arg uiLaunchProfile "$UI_LAUNCH_PROFILE" \
    --arg elapsed "${ELAPSED}s" \
    --arg executed "$executed" \
    --arg log "$TMPOUT" \
    --arg xcresult "$RESULT_BUNDLE" \
    --arg uiContactSheet "$UI_TEST_CONTACT_SHEET" \
    --arg uiQuick4Sheet "$UI_TEST_QUICK4_SHEET" \
    --arg uiVisualReviewManifest "$UI_TEST_SCREENSHOT_MANIFEST" \
    --arg uiScreenshotDir "$UI_TEST_SCREENSHOT_DIR" \
    --arg uiVideo "$UI_TEST_VIDEO" \
    --arg uiReviewRoot "$UI_TEST_REVIEW_ROOT" \
    --arg uiReviewHtml "$UI_TEST_REVIEW_HTML" \
    --arg device "$(resolve_run_device_udid 2>/dev/null || true)" \
    --argjson lockWaitMs "${LOCK_WAIT_MS:-0}" \
    --argjson deviceRunLockWaitMs "${DEVICE_RUN_LOCK_WAIT_MS:-0}" \
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
    --argjson coverage "$COVERAGE_JSON" \
    '{
      schema:$schema,
      kind:$kind,
      status:$result,
      result:$result,
      exit:$exit,
      reason:(if $reason == "" then null else $reason end),
      caller:$caller,
      invocation:{ts:$ts,pid:$pid,cwd:$cwd,verdictFile:$verdictFile},
      options:{
        uiLaunchProfile:(if $uiLaunchProfile == "" then null else $uiLaunchProfile end)
      },
      elapsed:$elapsed,
      executed:(if $executed == "" then null else $executed end),
      device:(if $device == "" then null else $device end),
      timings:{
        lockWaitMs:$lockWaitMs,
        deviceRunLockWaitMs:$deviceRunLockWaitMs,
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
      coverage:$coverage,
      artifacts:{
        log:$log,
        xcresult:$xcresult,
        uiContactSheet:(if $uiContactSheet == "" then null else $uiContactSheet end),
        uiQuick4Sheet:(if $uiQuick4Sheet == "" then null else $uiQuick4Sheet end),
        uiVisualReviewManifest:(if $uiVisualReviewManifest == "" then null else $uiVisualReviewManifest end),
        uiScreenshotDir:(if $uiScreenshotDir == "" then null else $uiScreenshotDir end),
        uiVideo:(if $uiVideo == "" then null else $uiVideo end),
        uiReviewRoot:(if $uiReviewRoot == "" then null else $uiReviewRoot end),
        uiReviewHtml:(if $uiReviewHtml == "" then null else $uiReviewHtml end)
      }
    }' >"$VERDICT_JSON_FILE" || true
  # The per-invocation JSON has no concurrent writer, so per-run metric
  # attribution is correct even when many agents finish at once.
  type append_run_metric >/dev/null 2>&1 && append_run_metric "$VERDICT_JSON_FILE"
  kg_ios_verdict_publish
}

populate_timing_breakdown
build_ui_step_contact_sheet
archive_ui_test_recording
build_ui_test_review_page
populate_coverage_summary || true

# Extract summary from xcresult if available
if grep -qE '^\*\* TEST( EXECUTE)? SUCCEEDED' "$TMPOUT" 2>/dev/null; then
  EXECUTED="$(count_executed_tests_xcresult || count_executed_tests)"
  if [[ "$EXECUTED" -eq 0 ]]; then
    echo ""
    echo "[ios_test] ✗ FALSE GREEN: xcodebuild reported TEST SUCCEEDED but 0 tests executed" >&2
    echo "[ios_test]   (likely a stale/bogus -only-testing test ID matched nothing) — $CALLER" >&2
    emit_ui_runner_lifecycle
    echo "RESULT=fail reason=false-green-0-executed caller=$CALLER log=$TMPOUT xcresult=$RESULT_BUNDLE $(kg_ios_verdict_identity_kv)" > "$VERDICT_FILE"
    write_json_verdict "fail" "1" "false-green-0-executed" "0"
    rm -f "$TMPOUT"
    exit 1
  fi
  if [[ "$COVERAGE_ENABLED" -eq 1 && "$COVERAGE_VERDICT" != "pass" ]]; then
    echo ""
    echo "[ios_test] ✗ coverage gate failed: $COVERAGE_REASON" >&2
    PRESERVE_TMPOUT=1
    echo "RESULT=fail reason=$COVERAGE_REASON caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE $(kg_ios_verdict_identity_kv)" > "$VERDICT_FILE"
    write_json_verdict "fail" "1" "$COVERAGE_REASON" "$EXECUTED"
    print_timing_summary
    echo "[ios_test] ✗ tests passed but coverage failed (${ELAPSED}s) — $CALLER  verdict=$VERDICT_FILE" >&2
    echo "[ios_test] full log preserved: $TMPOUT" >&2
    echo "[ios_test] xcresult preserved: $RESULT_BUNDLE" >&2
    exit 1
  fi
  echo ""
  echo "RESULT=ok executed=$EXECUTED caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE $(kg_ios_verdict_identity_kv)" > "$VERDICT_FILE"
  write_json_verdict "ok" "0" "" "$EXECUTED"
  print_timing_summary
  echo "[ios_test] ✓ all tests passed ($EXECUTED executed, ${ELAPSED}s) — $CALLER  log=$TMPOUT  xcresult=$RESULT_BUNDLE  verdict=$VERDICT_FILE"
elif grep -qE '^\*\* TEST( EXECUTE)? FAILED' "$TMPOUT" 2>/dev/null; then
  echo ""
  # Show failing test details
  grep -E 'error:|failed' "$TMPOUT" | grep -v 'xcodebuild\|Linker\|frontend' | head -20 || true
  echo ""
  PRESERVE_TMPOUT=1
  echo "RESULT=fail reason=tests-failed caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE $(kg_ios_verdict_identity_kv)" > "$VERDICT_FILE"
  write_json_verdict "fail" "1" "tests-failed" ""
  print_timing_summary
  emit_ui_runner_lifecycle
  echo "[ios_test] ✗ tests failed (${ELAPSED}s) — $CALLER  verdict=$VERDICT_FILE" >&2
  echo "[ios_test] full log preserved: $TMPOUT" >&2
  echo "[ios_test] xcresult preserved: $RESULT_BUNDLE" >&2
  EXIT_CODE=1
else
  echo ""
  # Show last 10 lines for unexpected output
  tail -10 "$TMPOUT"
  PRESERVE_TMPOUT=1
  # Inconclusive (no TEST SUCCEEDED/FAILED marker — e.g. a compile/build
  # failure). Never report success, but PRESERVE a meaningful upstream non-zero
  # code: xcodebuild's 65 for a build failure flows through here, letting callers
  # distinguish "build broke" (65) from "tests failed" (1). Only coerce a
  # spurious 0 up to 1 so an inconclusive run can never exit green.
  [[ "$EXIT_CODE" -eq 0 ]] && EXIT_CODE=1
  echo "RESULT=inconclusive EXIT=$EXIT_CODE caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE $(kg_ios_verdict_identity_kv)" > "$VERDICT_FILE"
  write_json_verdict "inconclusive" "$EXIT_CODE" "" ""
  print_timing_summary
  emit_ui_runner_lifecycle
  echo "[ios_test] ? inconclusive (exit=$EXIT_CODE, ${ELAPSED}s) — $CALLER  verdict=$VERDICT_FILE" >&2
  echo "[ios_test] full log preserved: $TMPOUT" >&2
  echo "[ios_test] xcresult preserved: $RESULT_BUNDLE" >&2
fi

if [[ "$PRESERVE_TMPOUT" -eq 0 ]]; then
  rm -f "$TMPOUT"
fi
exit $EXIT_CODE
