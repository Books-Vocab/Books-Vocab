#!/usr/bin/env bash
# ios_build.sh — lock-guarded iOS build for parallel worktree agents
#
# Usage:
#   ./ops/ios_build.sh                           # from project root (any worktree)
#   ./ops/ios_build.sh --timeout 300             # custom lock wait (default: 600s)
#   ./ops/ios_build.sh --extra-settings KEY=VAL  # pass extra xcodebuild settings (repeatable)
#   ./ops/ios_build.sh --swift6                  # shorthand: SWIFT_STRICT_CONCURRENCY=complete
#   ./ops/ios_build.sh --configuration Release   # build configuration (default: Debug)
#
# How it works:
#   1. Spin-waits to acquire an exclusive lock (shlock, macOS built-in)
#   2. Runs xcodebuild against ONE shared DerivedData anchored at the main repo
#      (incremental reuse across worktrees; bounded size; no path-hashed orphans)
#   3. Releases lock via trap on exit
#
# Safe for concurrent calls — second caller blocks until first finishes.

set -euo pipefail

LOCK_FILE="/tmp/kg-ios-build.lock"
TIMEOUT=600
POLL_INTERVAL=3
DESTINATION='platform=iOS Simulator,name=iPhone 17 Pro Max'
CONFIGURATION='Debug'
EXTRA_SETTINGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --destination) DESTINATION="$2"; shift 2 ;;
    --catalyst) DESTINATION='platform=macOS,variant=Mac Catalyst'; shift ;;
    --configuration) CONFIGURATION="$2"; shift 2 ;;
    --extra-settings) EXTRA_SETTINGS+=("$2"); shift 2 ;;
    --swift6) EXTRA_SETTINGS+=("SWIFT_STRICT_CONCURRENCY=complete"); shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Resolve project root from script location
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# Optional run-metrics logging — additive, must never break the build.
METRICS_LIB="$SCRIPT_DIR/lib/ios_run_metrics.sh"
[[ -f "$METRICS_LIB" ]] && source "$METRICS_LIB"
XCODEPROJ="$PROJECT_ROOT/ios/BooksAndVocab.xcodeproj"
IOS_OPS="$SCRIPT_DIR/ios_ops.sh"
# DerivedData policy: one shared, bounded cache anchored at the MAIN repo
# (resolved via git-common-dir, so every worktree maps to the same path). This
# avoids both failure modes:
#   - global default location → a new path-hashed orphan per worktree (110G leak)
#   - worktree-local cache    → zero cross-worktree reuse, ModuleCache rebuilt
#                               from scratch in every worktree
# Concurrent corruption is a non-issue: all builds serialize on the global
# shlock above. Override with KG_IOS_BUILD_DERIVED_DATA_ROOT. If git-common-dir
# can't be resolved, fall back to worktree-local so the build never breaks.
if [[ -n "${KG_IOS_BUILD_DERIVED_DATA_ROOT:-}" ]]; then
  DERIVED_DATA_ROOT="$KG_IOS_BUILD_DERIVED_DATA_ROOT"
else
  GIT_COMMON_DIR="$(git -C "$PROJECT_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -n "$GIT_COMMON_DIR" && -d "$GIT_COMMON_DIR" ]]; then
    DERIVED_DATA_ROOT="$(dirname "$GIT_COMMON_DIR")/.cache/ios-build-derived-data"
  else
    DERIVED_DATA_ROOT="$PROJECT_ROOT/.cache/ios-build-derived-data"
  fi
fi

if [[ ! -d "$XCODEPROJ" ]]; then
  echo "error: $XCODEPROJ not found" >&2
  exit 1
fi

CALLER="${WORKTREE_BRANCH:-$(git -C "$PROJECT_ROOT" branch --show-current 2>/dev/null || echo 'unknown')}"

ios_build_now_ms() {
  perl -MTime::HiRes=time -e 'printf "%.0f\n", time() * 1000'
}

destination_is_simulator() {
  [[ "$DESTINATION" == *"platform=iOS Simulator"* ]]
}

destination_simulator_name() {
  sed -n 's/.*name=\([^,]*\).*/\1/p' <<<"$DESTINATION" | head -1
}

# Progress baseline: compile-event count from last successful build.
# Stored next to DerivedData (shared across worktrees, same cache root).
# First run has no baseline → raw counts only; after first build % is shown.
BUILD_PROGRESS_BASELINE="$DERIVED_DATA_ROOT/kg_build.events_baseline"

# shellcheck source=lib/ios_build_progress.sh
source "$SCRIPT_DIR/lib/ios_build_progress.sh"

# --- Lock acquire (shlock spin-wait) ---
MONITOR_PID=""
cleanup() {
  rm -f "$LOCK_FILE"
  [[ -n "$MONITOR_PID" ]] && kill "$MONITOR_PID" 2>/dev/null || true
}

echo "[ios_build] caller=$CALLER waiting for lock..."
WAITED=0
LOCK_WAIT_START_MS="$(ios_build_now_ms)"
while ! shlock -f "$LOCK_FILE" -p $$; do
  # Check if holder PID is still alive; if not, steal lock
  HOLDER_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
  if [[ -n "$HOLDER_PID" ]] && ! kill -0 "$HOLDER_PID" 2>/dev/null; then
    # Re-check the lock still holds the SAME dead PID before stealing — another
    # waiter may have acquired it fresh between our cat and rm (steal only our
    # observed dead lock, never a live one).
    if [[ "$(cat "$LOCK_FILE" 2>/dev/null || echo "")" == "$HOLDER_PID" ]]; then
      echo "[ios_build] stale lock (pid=$HOLDER_PID dead), stealing"
      rm -f "$LOCK_FILE"
    fi
    continue
  fi
  if (( WAITED >= TIMEOUT )); then
    echo "[ios_build] error: timed out after ${TIMEOUT}s waiting for lock (holder=$HOLDER_PID)" >&2
    exit 1
  fi
  sleep "$POLL_INTERVAL"
  WAITED=$(( WAITED + POLL_INTERVAL ))
done
trap cleanup EXIT
LOCK_WAIT_MS=$(( $(ios_build_now_ms) - LOCK_WAIT_START_MS ))

echo "[ios_build] lock acquired by $CALLER (pid=$$) lockWaitMs=$LOCK_WAIT_MS — building..."
echo "[ios_build] derivedDataRoot=$DERIVED_DATA_ROOT"
START=$(date +%s)
START_MS="$(ios_build_now_ms)"
BOOT_MS=0
XCODEBUILD_MS=0
TMPOUT="$(mktemp "${TMPDIR:-/tmp}/kg_ios_build.XXXXXX").log"
RESULT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kg_ios_build_result.XXXXXX")"
RESULT_BUNDLE="$RESULT_DIR/Build.xcresult"

if destination_is_simulator; then
  SIMULATOR_BOOT_SELECTOR="$(destination_simulator_name)"
  if [[ -n "$SIMULATOR_BOOT_SELECTOR" ]]; then
    BOOT_START_MS="$(ios_build_now_ms)"
    echo "[ios_build] simulator ensure-booted — device=\"$SIMULATOR_BOOT_SELECTOR\" (up to ~30s if cold-starting from scratch)..."
    "$IOS_OPS" simulator ensure-booted --device "$SIMULATOR_BOOT_SELECTOR"
    BOOT_END_MS="$(ios_build_now_ms)"
    BOOT_MS=$(( BOOT_END_MS - BOOT_START_MS ))
  fi
fi

set +e
XCODEBUILD_START_MS="$(ios_build_now_ms)"
BUILD_START_S=$(date +%s)
# -quiet is intentionally omitted: without it xcodebuild emits one line per
# compiled file (SwiftCompile/CompileC), which the progress monitor counts to
# show %. All output still goes to $TMPOUT — stdout stays clean.
MONITOR_PID=$(start_build_monitor "$TMPOUT" "$BUILD_PROGRESS_BASELINE" "[ios_build]" "$BUILD_START_S")
xcodebuild \
  -project "$XCODEPROJ" \
  -scheme BooksAndVocab \
  -configuration "$CONFIGURATION" \
  -destination "$DESTINATION" \
  -derivedDataPath "$DERIVED_DATA_ROOT" \
  -resultBundlePath "$RESULT_BUNDLE" \
  "${EXTRA_SETTINGS[@]+"${EXTRA_SETTINGS[@]}"}" \
  build \
  >"$TMPOUT" 2>&1
EXIT_CODE=$?
kill "$MONITOR_PID" 2>/dev/null || true
wait "$MONITOR_PID" 2>/dev/null || true
MONITOR_PID=""
XCODEBUILD_END_MS="$(ios_build_now_ms)"
XCODEBUILD_MS=$(( XCODEBUILD_END_MS - XCODEBUILD_START_MS ))
COMPILE_EVENT_COUNT=$(count_compile_events "$TMPOUT")
set -e

ELAPSED=$(( $(date +%s) - START ))
END_MS="$(ios_build_now_ms)"
TOTAL_MS=$(( END_MS - START_MS ))
DIAGNOSTICS="$SCRIPT_DIR/ios_diagnostics.py"
if [[ -x "$DIAGNOSTICS" ]]; then
  diag_result="fail"; [[ $EXIT_CODE -eq 0 ]] && diag_result="pass"
  "$DIAGNOSTICS" --xcresult "$RESULT_BUNDLE" --log "$TMPOUT" --result "$diag_result" --limit 40 || true
else
  echo "[ios_build] diagnostics unavailable: $DIAGNOSTICS" >&2
fi

# Machine-readable verdict file — survives even when stdout/stderr is piped
# (e.g. `ios_build.sh | tail`, where the pipeline's exit code is tail's 0, not
# the build's). Read this instead of trusting a piped `$?`.
#
# Per-invocation UNIQUE path (multi-session race guard): VERDICT_FILE is
# `kg_ios_build_verdict.<epochTs>-<pid>` (or KG_IOS_VERDICT_FILE when a wrapper
# pins it); the historical fixed path stays as a last-writer-wins LATEST
# pointer for `ios_ops runs`. See ops/lib/ios_run_verdict.sh.
# shellcheck source=lib/ios_run_verdict.sh
source "$SCRIPT_DIR/lib/ios_run_verdict.sh"
kg_ios_verdict_init build "$PROJECT_ROOT"
write_json_verdict() {
  local result="$1" exit_code="$2"
  jq -nc \
    --arg schema "kg.ios.run-verdict.v1" \
    --arg kind "build" \
    --arg result "$result" \
    --arg exit "$exit_code" \
    --arg caller "$CALLER" \
    --arg cwd "$PROJECT_ROOT" \
    --arg verdictFile "$VERDICT_FILE" \
    --argjson ts "$(date +%s)" \
    --argjson pid "$$" \
    --arg elapsed "${ELAPSED}s" \
    --arg log "$TMPOUT" \
    --arg xcresult "$RESULT_BUNDLE" \
    --argjson lockWaitMs "$LOCK_WAIT_MS" \
    --argjson bootMs "$BOOT_MS" \
    --argjson xcodebuildMs "$XCODEBUILD_MS" \
    --argjson totalMs "$TOTAL_MS" \
    '{
      schema:$schema,
      kind:$kind,
      status:$result,
      result:$result,
      exit:$exit,
      reason:null,
      caller:$caller,
      invocation:{ts:$ts,pid:$pid,cwd:$cwd,verdictFile:$verdictFile},
      elapsed:$elapsed,
      executed:null,
      timings:{
        lockWaitMs:$lockWaitMs,
        bootMs:$bootMs,
        xcodebuildMs:$xcodebuildMs,
        totalMs:$totalMs
      },
      artifacts:{log:$log,xcresult:$xcresult}
    }' >"$VERDICT_JSON_FILE" || true
  type append_run_metric >/dev/null 2>&1 && append_run_metric "$VERDICT_JSON_FILE"
  kg_ios_verdict_publish
}
if [[ $EXIT_CODE -eq 0 ]]; then
  # Persist compile-event count as the baseline for future % estimates.
  # Written only on success so a failed partial build never poisons the baseline.
  if [[ "$COMPILE_EVENT_COUNT" -gt 0 ]]; then
    mkdir -p "$DERIVED_DATA_ROOT"
    echo "$COMPILE_EVENT_COUNT" > "$BUILD_PROGRESS_BASELINE"
  fi
  echo "RESULT=ok EXIT=0 caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE $(kg_ios_verdict_identity_kv)" > "$VERDICT_FILE"
  write_json_verdict "ok" "0"
  echo "[ios_build] timings lockWaitMs=$LOCK_WAIT_MS bootMs=$BOOT_MS xcodebuildMs=$XCODEBUILD_MS totalMs=$TOTAL_MS"
  echo "[ios_build] ✓ build succeeded (${ELAPSED}s, ${COMPILE_EVENT_COUNT} compile events) — $CALLER  log=$TMPOUT  xcresult=$RESULT_BUNDLE  verdict=$VERDICT_FILE"
else
  echo "RESULT=fail EXIT=$EXIT_CODE caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE $(kg_ios_verdict_identity_kv)" > "$VERDICT_FILE"
  write_json_verdict "fail" "$EXIT_CODE"
  echo "[ios_build] timings lockWaitMs=$LOCK_WAIT_MS bootMs=$BOOT_MS xcodebuildMs=$XCODEBUILD_MS totalMs=$TOTAL_MS"
  echo "[ios_build] ✗ build failed (exit $EXIT_CODE, ${ELAPSED}s) — $CALLER  log=$TMPOUT  xcresult=$RESULT_BUNDLE  verdict=$VERDICT_FILE" >&2
fi

exit $EXIT_CODE
