#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IOS_DIR="$REPO_ROOT/ios/BooksAndVocab"
OUTPUT="$REPO_ROOT/docs/snapshot/ios_baseline.md"
COMMIT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
DATE="$(date +%Y-%m-%d)"

# 1. Top 10 by line count
TOP10=$(find "$IOS_DIR" -name "*.swift" -exec wc -l {} + \
  | sort -rn | grep -v "total" \
  | awk -v base="$IOS_DIR/" 'NR <= 10 {path=$2; sub(base,"",path); printf "| %d | `%s` |\n", $1, path}')

# 2. Total lines and files
TOTAL_LINES=$(find "$IOS_DIR" -name "*.swift" -exec wc -l {} + | tail -1 | awk '{print $1}')
TOTAL_FILES=$(find "$IOS_DIR" -name "*.swift" | wc -l | tr -d ' ')

# 3. Preview coverage
VIEWS_FILES=$(find "$IOS_DIR/Views" "$IOS_DIR/UIComponents" -name "*.swift" 2>/dev/null | wc -l | tr -d ' ')
PREVIEW_FILES=$(find "$IOS_DIR/Views" "$IOS_DIR/UIComponents" -name "*.swift" -exec grep -l "#Preview" {} \; 2>/dev/null | wc -l | tr -d ' ')

# 4. Concurrency stats
MAIN_ACTOR=$({ grep -r "@MainActor" "$IOS_DIR" --include="*.swift" 2>/dev/null || true; } | wc -l | tr -d ' ')
ASYNC_FUNC=$({ grep -r "async func" "$IOS_DIR" --include="*.swift" 2>/dev/null || true; } | wc -l | tr -d ' ')

cat > "$OUTPUT" << EOF
<!-- doc-meta
tier: snapshot
authority: derived
update_trigger: machine-generated
scope:
  - ios/BooksAndVocab
verified_against: $COMMIT_SHA
-->

# iOS Frontend Baseline

基線日期: $DATE

---

## 1. 檔案規模 Top 10

| 行數 | 路徑 |
|------|------|
$TOP10

總 Swift 行數: $TOTAL_LINES / $TOTAL_FILES 檔案

---

## 2. Preview 覆蓋率

| 範圍 | 數量 |
|------|------|
| Views/ + UIComponents/ 檔案總數 | $VIEWS_FILES |
| 含 #Preview 的檔案數 | $PREVIEW_FILES |

---

## 3. 並行模式統計

| 標記 | 出現次數 |
|------|------|
| @MainActor | $MAIN_ACTOR |
| async func | $ASYNC_FUNC |
EOF

echo "Generated: $OUTPUT (verified_against: $COMMIT_SHA)"
