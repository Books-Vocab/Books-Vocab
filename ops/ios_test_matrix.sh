#!/usr/bin/env bash
# ios_test_matrix.sh — run BooksAndVocabTests one Swift file at a time.
#
# Purpose: debug systematically before the final all-tests run. Each file gets
# an isolated xcodebuild invocation through ops/ios_test.sh, with logs preserved.

set -euo pipefail

TIMEOUT=300
START_AT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --start-at) START_AT="$2"; shift 2 ;;
    *) echo "usage: $0 [--timeout seconds] [--start-at FileTests.swift]" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_DIR="$PROJECT_ROOT/ios/BooksAndVocabTests"
LOG_DIR="${TMPDIR:-/tmp}/kg_ios_test_matrix_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

echo "[ios_matrix] logs: $LOG_DIR"

started=0
[[ -z "$START_AT" ]] && started=1

passed=0
failed=0
skipped=0

while IFS= read -r file; do
  base="$(basename "$file")"
  if [[ "$started" -eq 0 ]]; then
    if [[ "$base" == "$START_AT" || "$file" == "$START_AT" ]]; then
      started=1
    else
      skipped=$((skipped + 1))
      continue
    fi
  fi

  log="$LOG_DIR/${base%.swift}.log"
  echo ""
  echo "[ios_matrix] ▶ $base"
  set +e
  "$SCRIPT_DIR/ios_test.sh" --file "$base" --timeout "$TIMEOUT" >"$log" 2>&1
  status=$?
  set -e
  if [[ "$status" -eq 0 ]]; then
    passed=$((passed + 1))
    tail -5 "$log"
    echo "[ios_matrix] ✓ $base"
  else
    failed=$((failed + 1))
    echo "[ios_matrix] ✗ $base (exit=$status)"
    echo "[ios_matrix] log: $log"
    grep -E '✘|error:|FAILED|failed|Time limit|Fatal error' "$log" | tail -40 || true
    echo "[ios_matrix] summary: passed=$passed failed=$failed skipped=$skipped"
    exit "$status"
  fi
done < <(find "$TEST_DIR" -maxdepth 1 -name '*.swift' -print | sort)

echo ""
echo "[ios_matrix] ✓ complete: passed=$passed failed=$failed skipped=$skipped logs=$LOG_DIR"
