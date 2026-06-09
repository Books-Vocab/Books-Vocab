#!/usr/bin/env bash
# ios_clean_derived_data.sh — reclaim stale Xcode build artifacts.
#
# Two leak sources are swept:
#   1. Path-hashed BooksBrowser-* dirs under the global default DerivedData
#      location (Xcode GUI / any xcodebuild run that did NOT pass an explicit
#      -derivedDataPath). ops/ios_build.sh now keeps DerivedData inside the
#      worktree, so new global orphans should stop appearing — this catches
#      GUI builds and anything pre-dating that fix.
#   2. Simulator devices whose runtime is gone (`simctl delete unavailable`).
#
# Default: dry-run. Pass --apply to actually delete. --days N (default 7)
# only removes global DerivedData dirs untouched for N+ days.

set -euo pipefail

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

# 1. Global path-hashed orphans (BooksBrowser-<hash>) older than $DAYS days.
if [[ -d "$DERIVED_DATA_GLOBAL" ]]; then
  while IFS= read -r dir; do
    [[ -n "$dir" ]] || continue
    size="$(du -sh "$dir" 2>/dev/null | cut -f1)"
    echo "[ios_clean] orphan $size  $dir"
    [[ $APPLY -eq 1 ]] && rm -rf "$dir"
  done < <(find "$DERIVED_DATA_GLOBAL" -maxdepth 1 -name 'BooksBrowser-*' -type d -mtime "+$DAYS" 2>/dev/null)
fi

# 2. Simulators whose runtime no longer exists.
if [[ $APPLY -eq 1 ]]; then
  xcrun simctl delete unavailable 2>/dev/null || true
  echo "[ios_clean] simctl delete unavailable done"
else
  echo "[ios_clean] (dry-run) would run: xcrun simctl delete unavailable"
fi

echo "[ios_clean] done"
