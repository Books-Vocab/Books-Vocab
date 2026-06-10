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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --days) DAYS="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

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
for keyed_root in \
  "${KG_IOS_TEST_CACHE_ROOT:-$PROJECT_ROOT/.cache/ios-test-derived-data}" \
  "${KG_IOS_OPS_CATALOG_CACHE_ROOT:-$PROJECT_ROOT/.cache/ios-catalog-derived-data}"; do
  KG_IOS_CACHE_EVICT_DRY_RUN=$(( 1 - APPLY )) kg_ios_cache_evict "$keyed_root" ""
done

# 3. Simulators whose runtime no longer exists.
if [[ $APPLY -eq 1 ]]; then
  xcrun simctl delete unavailable 2>/dev/null || true
  echo "[ios_clean] simctl delete unavailable done"
else
  echo "[ios_clean] (dry-run) would run: xcrun simctl delete unavailable"
fi

echo "[ios_clean] done"
