#!/usr/bin/env bash
# ios_build.sh — lock-guarded iOS build for parallel worktree agents
#
# Usage:
#   ./ops/ios_build.sh                  # from project root (any worktree)
#   ./ops/ios_build.sh --timeout 300    # custom lock wait (default: 600s)
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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --destination) DESTINATION="$2"; shift 2 ;;
    --catalyst) DESTINATION='platform=macOS,variant=Mac Catalyst'; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Resolve project root from script location
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XCODEPROJ="$PROJECT_ROOT/ios/BooksBrowser.xcodeproj"
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

# --- Lock acquire (shlock spin-wait) ---
cleanup() { rm -f "$LOCK_FILE"; }

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
    "$IOS_OPS" simulator ensure-booted --device "$SIMULATOR_BOOT_SELECTOR" >/dev/null
    BOOT_END_MS="$(ios_build_now_ms)"
    BOOT_MS=$(( BOOT_END_MS - BOOT_START_MS ))
    echo "[ios_build] simulator ensure-booted device=\"$SIMULATOR_BOOT_SELECTOR\" bootMs=$BOOT_MS"
  fi
fi

set +e
XCODEBUILD_START_MS="$(ios_build_now_ms)"
xcodebuild \
  -project "$XCODEPROJ" \
  -scheme BooksBrowser \
  -destination "$DESTINATION" \
  -derivedDataPath "$DERIVED_DATA_ROOT" \
  -resultBundlePath "$RESULT_BUNDLE" \
  -quiet build \
  >"$TMPOUT" 2>&1
EXIT_CODE=$?
XCODEBUILD_END_MS="$(ios_build_now_ms)"
XCODEBUILD_MS=$(( XCODEBUILD_END_MS - XCODEBUILD_START_MS ))
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
VERDICT_FILE="${TMPDIR:-/tmp}/kg_ios_build_verdict"
VERDICT_JSON_FILE="$VERDICT_FILE.json"
write_json_verdict() {
  local result="$1" exit_code="$2"
  jq -nc \
    --arg schema "kg.ios.run-verdict.v1" \
    --arg kind "build" \
    --arg result "$result" \
    --arg exit "$exit_code" \
    --arg caller "$CALLER" \
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
}
if [[ $EXIT_CODE -eq 0 ]]; then
  echo "RESULT=ok EXIT=0 caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE" > "$VERDICT_FILE"
  write_json_verdict "ok" "0"
  echo "[ios_build] timings lockWaitMs=$LOCK_WAIT_MS bootMs=$BOOT_MS xcodebuildMs=$XCODEBUILD_MS totalMs=$TOTAL_MS"
  echo "[ios_build] ✓ build succeeded (${ELAPSED}s) — $CALLER  log=$TMPOUT  xcresult=$RESULT_BUNDLE  verdict=$VERDICT_FILE"
else
  echo "RESULT=fail EXIT=$EXIT_CODE caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE" > "$VERDICT_FILE"
  write_json_verdict "fail" "$EXIT_CODE"
  echo "[ios_build] timings lockWaitMs=$LOCK_WAIT_MS bootMs=$BOOT_MS xcodebuildMs=$XCODEBUILD_MS totalMs=$TOTAL_MS"
  echo "[ios_build] ✗ build failed (exit $EXIT_CODE, ${ELAPSED}s) — $CALLER  log=$TMPOUT  xcresult=$RESULT_BUNDLE  verdict=$VERDICT_FILE" >&2
fi

exit $EXIT_CODE
