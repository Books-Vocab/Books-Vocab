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
#
# Both counters are grep approximations of "what a Swift lexer would see". Their residual
# error was measured on 2026-08-06 against a lexer that strips comments/strings and walks
# balanced parens; the numbers below are that measurement, not an estimate. Re-measure
# before widening either pattern — see ops/tests/test_gen_ios_baseline.sh.
#
# `@MainActor` also shows up in doc comments *discussing* isolation; that is prose, not an
# annotation. Dropping lines whose first non-space token is `//` landed exactly on the
# lexer's count (298 raw -> 252). Uncovered: block comments and string literals (0 today).
MAIN_ACTOR=$({ grep -rh "@MainActor" "$IOS_DIR" --include="*.swift" 2>/dev/null || true; } | { grep -v "^[[:space:]]*//" || true; } | wc -l | tr -d ' ')
# Swift word order is `func f() async`, never the literal `async func` — the old pattern
# was structurally 0 forever while the tree held 290 declarations (IMP-20260805-958999).
# Two arms: same-line signatures, plus the lines that close a multi-line signature with
# `) async`. Measured 292 vs a lexer's 290. The 2 extras are non-async funcs taking an
# `@escaping () async ->` parameter; the anchored arm was verified *set-equal* to the
# lexer's 71 multi-line declarations (no misses, no extras). Do NOT relax the second arm
# to a bare `\) async`: unanchored it also swallows closure-typed properties such as
# `var sleep: (Duration) async -> Void` (323, i.e. 33 wrong).
ASYNC_FUNC=$({ grep -rE "func [^{]*\)[[:space:]]*async|^[[:space:]]*\)[[:space:]]*async" "$IOS_DIR" --include="*.swift" 2>/dev/null || true; } | wc -l | tr -d ' ')

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
