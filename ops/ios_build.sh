#!/usr/bin/env bash
# ios_build.sh — lock-guarded iOS build for parallel worktree agents
#
# Usage:
#   ./ops/ios_build.sh                  # from project root (any worktree)
#   ./ops/ios_build.sh --timeout 300    # custom lock wait (default: 600s)
#
# How it works:
#   1. Spin-waits to acquire an exclusive lock (shlock, macOS built-in)
#   2. Runs xcodebuild (shared DerivedData → incremental builds)
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

if [[ ! -d "$XCODEPROJ" ]]; then
  echo "error: $XCODEPROJ not found" >&2
  exit 1
fi

CALLER="${WORKTREE_BRANCH:-$(git -C "$PROJECT_ROOT" branch --show-current 2>/dev/null || echo 'unknown')}"

# --- Lock acquire (shlock spin-wait) ---
cleanup() { rm -f "$LOCK_FILE"; }

echo "[ios_build] caller=$CALLER waiting for lock..."
WAITED=0
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

echo "[ios_build] lock acquired by $CALLER (pid=$$) — building..."
START=$(date +%s)
TMPOUT="$(mktemp "${TMPDIR:-/tmp}/kg_ios_build.XXXXXX").log"
RESULT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kg_ios_build_result.XXXXXX")"
RESULT_BUNDLE="$RESULT_DIR/Build.xcresult"

set +e
xcodebuild \
  -project "$XCODEPROJ" \
  -scheme BooksBrowser \
  -destination "$DESTINATION" \
  -resultBundlePath "$RESULT_BUNDLE" \
  -quiet build \
  >"$TMPOUT" 2>&1
EXIT_CODE=$?
set -e

ELAPSED=$(( $(date +%s) - START ))
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
if [[ $EXIT_CODE -eq 0 ]]; then
  echo "RESULT=ok EXIT=0 caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE" > "$VERDICT_FILE"
  echo "[ios_build] ✓ build succeeded (${ELAPSED}s) — $CALLER  log=$TMPOUT  xcresult=$RESULT_BUNDLE  verdict=$VERDICT_FILE"
else
  echo "RESULT=fail EXIT=$EXIT_CODE caller=$CALLER elapsed=${ELAPSED}s log=$TMPOUT xcresult=$RESULT_BUNDLE" > "$VERDICT_FILE"
  echo "[ios_build] ✗ build failed (exit $EXIT_CODE, ${ELAPSED}s) — $CALLER  log=$TMPOUT  xcresult=$RESULT_BUNDLE  verdict=$VERDICT_FILE" >&2
fi

exit $EXIT_CODE
