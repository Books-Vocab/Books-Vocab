#!/usr/bin/env bash
# gen_ios_baseline.sh — 產生 docs/snapshot/ios_baseline.md（registry entry: generated.ios_baseline）
#
# 用法:
#   ops/gen_ios_baseline.sh          # 印到 stdout（預設，不寫檔）
#   ops/gen_ios_baseline.sh --write  # 寫入 docs/snapshot/ios_baseline.md
#   ops/gen_ios_baseline.sh --check  # 比對磁碟產物與現算輸出，不一致印 STALE 並 exit 1
#
# 為什麼預設不再寫檔：--check 由 docs/registry.yml 的 `check:` 欄接進 docs_lint.sh 的
# registry gate。若本腳本仍無條件寫檔，gate 會把它正在檢查的那個檔改成通過（自己把自己
# 轉綠），並弄髒 cutover 依賴的乾淨樹前提。
#
# --check 比對前會濾掉兩個「時鐘」：整段 <!-- doc-meta -->（內含每次 commit 都會變的
# verified_against）與 `基線日期:`（每天都會變）。不濾就會做出一個每天自轉紅、一週內被
# 關掉的 gate。濾掉的僅此兩者；所有實質度量（Top-10、總行數、檔案數、Preview 覆蓋、
# @MainActor / async func 計數）都仍在比對範圍內。
#
# STALE / up to date 的用語沿用 ops/gen_web_tokens.py 既有 idiom（印出該跑哪條命令）。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IOS_DIR="$REPO_ROOT/ios/BooksAndVocab"
OUTPUT="$REPO_ROOT/docs/snapshot/ios_baseline.md"
COMMIT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
DATE="$(date +%Y-%m-%d)"

usage() { sed -n '2,19p' "$0"; }

MODE=stdout
for arg in "$@"; do
  case "$arg" in
    --write) MODE=write ;;
    --check) MODE=check ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

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

# 命令替換會吃掉尾端換行，所以之後一律用 printf '%s\n' "$BODY" 輸出，
# 檔尾才會是既有 committed 檔一樣的單一 \n。
BODY="$(cat << EOF
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
)"

# 濾掉兩個時鐘：doc-meta 整段 + 基線日期。其餘一律保留。
normalize() {
  awk '
    NR==1 && $0=="<!-- doc-meta" { m=1; next }
    m && $0=="-->"               { m=0; next }
    m                            { next }
    /^基線日期: /                { next }
    { print }
  '
}

case "$MODE" in
  stdout)
    printf '%s\n' "$BODY"
    ;;
  write)
    printf '%s\n' "$BODY" > "$OUTPUT"
    echo "Generated: $OUTPUT (verified_against: $COMMIT_SHA)"
    ;;
  check)
    if [ ! -f "$OUTPUT" ]; then
      echo "STALE $OUTPUT 不存在(跑: ./ops/gen_ios_baseline.sh --write)"
      exit 1
    fi
    if ! diff -q <(printf '%s\n' "$BODY" | normalize) <(normalize < "$OUTPUT") >/dev/null; then
      echo "STALE $OUTPUT — 內容與 generator 輸出不一致(跑: ./ops/gen_ios_baseline.sh --write)"
      exit 1
    fi
    echo "$OUTPUT is up to date."
    ;;
esac
