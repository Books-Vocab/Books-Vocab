#!/usr/bin/env bash
# ios_clean_derived_data.sh — reclaim stale Xcode build artifacts.
#
# Three leak sources are swept:
#   1. Path-hashed BooksAndVocab-* dirs under the global default DerivedData
#      location (Xcode GUI / any xcodebuild run that did NOT pass an explicit
#      -derivedDataPath). ops/ios_build.sh now keeps DerivedData inside the
#      worktree, so new global orphans should stop appearing — this catches
#      GUI builds and anything pre-dating that fix.
#   2. Keyed DerivedData caches (.cache/ios-test-derived-data,
#      .cache/ios-catalog-derived-data) — same LRU eviction the build paths
#      run automatically (lib/ios_cache_evict.sh), exposed for manual sweeps.
#      Honors KG_IOS_CACHE_KEEP / KG_IOS_CACHE_EVICT_MIN_AGE_HOURS.
#   3. Simulator devices whose runtime is gone (`simctl delete unavailable`).
#
# Default: dry-run. Pass --apply to actually delete. --days N (default 7)
# only removes global DerivedData dirs untouched for N+ days.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/ios_cache_evict.sh
source "$SCRIPT_DIR/lib/ios_cache_evict.sh"

APPLY=0
DAYS=7
DERIVED_DATA_GLOBAL="$HOME/Library/Developer/Xcode/DerivedData"
KEYED_ROOTS=(
  "${KG_IOS_TEST_CACHE_ROOT:-$PROJECT_ROOT/.cache/ios-test-derived-data}"
  "${KG_IOS_OPS_CATALOG_CACHE_ROOT:-$PROJECT_ROOT/.cache/ios-catalog-derived-data}"
)
RECEIPT_ROOT="${KG_IOS_CACHE_CLEANUP_RECEIPT_ROOT:-$PROJECT_ROOT/build/ios-report/retained/receipts}"
RUN_ID="cache-cleanup-$(date -u '+%Y%m%d-%H%M%S')-$$"
RECEIPT_PATH="$RECEIPT_ROOT/$RUN_ID.json"
RECEIPT_STATUS="running"
RECEIPT_REASON=""
RECEIPT_STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
RECEIPT_DISK_BEFORE_BYTES=""
RECEIPT_CACHE_BEFORE_BYTES=""
RECEIPT_CACHE_AFTER_BYTES=""

free_bytes() {
  local available_kb
  available_kb="$(df -k / | awk 'NR==2 {print $4; exit}')"
  [[ "$available_kb" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$((available_kb * 1024))"
}

allocated_bytes() {
  local total_kb=0 path size_kb
  for path in "${KEYED_ROOTS[@]}"; do
    [[ -e "$path" ]] || continue
    size_kb="$(du -sk "$path" 2>/dev/null | awk 'NR==1 {print $1; exit}')"
    [[ "$size_kb" =~ ^[0-9]+$ ]] || size_kb=0
    total_kb=$((total_kb + size_kb))
  done
  printf '%s\n' "$((total_kb * 1024))"
}

ancestor_pids() {
  local cursor="${1:-$$}" parent
  printf '%s\n' "$cursor"
  while [[ "$cursor" =~ ^[0-9]+$ ]] && (( cursor > 1 )); do
    parent="$(ps -o ppid= -p "$cursor" 2>/dev/null | tr -d ' ' || true)"
    [[ "$parent" =~ ^[0-9]+$ ]] || break
    (( parent > 1 )) || break
    printf '%s\n' "$parent"
    [[ "$parent" == "$cursor" ]] && break
    cursor="$parent"
  done
}

active_ios_consumers() {
  local ignored
  ignored=" $(ancestor_pids "$$" | tr '\n' ' ') "
  ps -axo pid=,ppid=,command= 2>/dev/null | awk -v ignored="$ignored" '
    function is_ignored(pid) { return index(ignored, " " pid " ") > 0 }
    {
      pid = $1
      if (is_ignored(pid)) next
      command = $3
      for (i = 4; i <= NF; i++) command = command " " $i
      if (command ~ /(^|\/)(xcodebuild|ios_test[.]sh|run_ui_evidence[.]sh|ios_ui_run_many[.]py)([[:space:]]|$)/) {
        print $0
      }
    }
  '
}

active_ios_locks() {
  local path raw pid
  for path in /tmp/kg-ios-build.lock /tmp/kg-ios-ui-video.lock /tmp/kg-ios-test-device-*.lock; do
    [[ -e "$path" ]] || continue
    raw="$(sed -n '1p' "$path" 2>/dev/null || true)"
    if [[ ! "$raw" =~ ^[0-9]+$ ]]; then
      printf '%s status=invalid value=%s\n' "$path" "$raw"
      continue
    fi
    pid="$raw"
    if kill -0 "$pid" 2>/dev/null; then
      printf '%s status=active pid=%s\n' "$path" "$pid"
    fi
  done
}

write_receipt() {
  local exit_code="${1:-0}" finished_at temporary status
  finished_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  status="$RECEIPT_STATUS"
  [[ "$status" == "running" ]] && status="$([[ "$exit_code" -eq 0 ]] && echo success || echo failure)"
  mkdir -p "$RECEIPT_ROOT" 2>/dev/null || return 0
  temporary="$RECEIPT_PATH.tmp"
  jq -n \
    --arg schema "kg.ios.cache-cleanup.v1" \
    --arg runID "$RUN_ID" \
    --arg status "$status" \
    --arg reason "$RECEIPT_REASON" \
    --arg startedAt "$RECEIPT_STARTED_AT" \
    --arg finishedAt "$finished_at" \
    --arg root "$PROJECT_ROOT" \
    --arg mode "$([[ "$APPLY" -eq 1 ]] && echo apply || echo preview)" \
    --arg receipt "$RECEIPT_PATH" \
    --argjson diskBefore "${RECEIPT_DISK_BEFORE_BYTES:-null}" \
    --argjson cacheBefore "${RECEIPT_CACHE_BEFORE_BYTES:-null}" \
    --argjson cacheAfter "${RECEIPT_CACHE_AFTER_BYTES:-null}" \
    '{
      schema:$schema, runID:$runID, status:$status,
      reason:(if $reason == "" then null else $reason end),
      startedAt:$startedAt, finishedAt:$finishedAt, root:$root, mode:$mode,
      diskFreeBytesBefore:$diskBefore,
      cacheAllocatedBytesBefore:$cacheBefore,
      cacheAllocatedBytesAfter:$cacheAfter,
      receipt:$receipt
    }' > "$temporary" 2>/dev/null && mv -f "$temporary" "$RECEIPT_PATH" 2>/dev/null || true
}

RECEIPT_DISK_BEFORE_BYTES="$(free_bytes 2>/dev/null || true)"
trap 'write_receipt "$?"' EXIT
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --days) DAYS="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

consumers="$(active_ios_consumers)"
locks="$(active_ios_locks)"
if [[ -n "$consumers" || -n "$locks" ]]; then
  RECEIPT_STATUS="blocked"
  RECEIPT_REASON="active-ios-consumer-or-lock"
  echo "[ios_clean] blocked: active iOS consumer or lock exists" >&2
  [[ -n "$consumers" ]] && printf '%s\n' "$consumers" >&2
  [[ -n "$locks" ]] && printf '%s\n' "$locks" >&2
  exit 75
fi

RECEIPT_CACHE_BEFORE_BYTES="$(allocated_bytes 2>/dev/null || true)"
echo "[ios_clean] mode=$([[ $APPLY -eq 1 ]] && echo apply || echo dry-run) days=$DAYS"

# 1. Global path-hashed orphans (BooksAndVocab-<hash>) older than $DAYS days.
if [[ -d "$DERIVED_DATA_GLOBAL" ]]; then
  while IFS= read -r dir; do
    [[ -n "$dir" ]] || continue
    size="$(du -sh "$dir" 2>/dev/null | cut -f1)"
    echo "[ios_clean] orphan $size  $dir"
    [[ $APPLY -eq 1 ]] && rm -rf "$dir"
  done < <(find "$DERIVED_DATA_GLOBAL" -maxdepth 1 -name 'BooksAndVocab-*' -type d -mtime "+$DAYS" 2>/dev/null)
fi

# 2. Keyed in-repo caches — current_key 留空（手動 sweep 沒有「本 run 在用」
#    的概念），靠 keep-N + min-age 視窗保護進行中的 run；--apply 才真刪。
for keyed_root in "${KEYED_ROOTS[@]}"; do
  KG_IOS_CACHE_EVICT_DRY_RUN=$(( 1 - APPLY )) kg_ios_cache_evict "$keyed_root" ""
done

# 3. Simulators whose runtime no longer exists.
if [[ $APPLY -eq 1 ]]; then
  xcrun simctl delete unavailable 2>/dev/null || true
  echo "[ios_clean] simctl delete unavailable done"
else
  echo "[ios_clean] (dry-run) would run: xcrun simctl delete unavailable"
fi

RECEIPT_CACHE_AFTER_BYTES="$(allocated_bytes 2>/dev/null || true)"
RECEIPT_STATUS="$([[ "$APPLY" -eq 1 ]] && echo success || echo preview)"
echo "[ios_clean] done"
