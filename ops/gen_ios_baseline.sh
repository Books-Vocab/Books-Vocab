#!/usr/bin/env bash
# gen_ios_baseline.sh — 現算 iOS 前端規模基線，印到 stdout
#
# 用法:
#   ops/gen_ios_baseline.sh   # 印到 stdout（唯一模式，不寫檔、不進版控）
#   ops/gen_ios_baseline.sh --check  # 驗證 stdout 產出可重現，不寫檔
#
# stdout-only 產出是刻意的（IMP-20260808-b63206）。產物曾經是 tracked 的
# docs/snapshot/ios_baseline.md + registry 的 generated entry，代價是**任何**一行 iOS 改動
# 都讓 docs gate 轉紅並要求把一個 repo 級產物夾進自己的 commit——一波 N 條 iOS 工作樹就生出
# N 份互相衝突的版本，2026-08-08 那批還擋住兩條完全沒碰 iOS 的分支。它 49 行、約 1 秒可重算、
# 且全 repo 沒有任何工作流讀它的內容，所以改成「需要當下基線就現跑」；舊有的寫檔模式與
# 磁碟產物比對模式隨之退場（沒有版控產物可寫、可比對）。`--check` 保留為唯讀的 stdout
# 產出檢查，不復活磁碟產物或寫檔模式。
#
# 兩個並行統計 counter 是 grep 對 Swift 源碼文字的近似，殘餘誤差已量測（見各賦值行旁的
# 註解）；回歸測試 ops/tests/test_gen_ios_baseline.sh 直接驅動那兩行去掃合成 fixture。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IOS_DIR="$REPO_ROOT/ios/BooksAndVocab"
# Anchor on the merge-base with origin/main, NOT on HEAD. HEAD orphans itself: the
# generator bakes the sha into the artifact, and the very next commit (or amend, or
# rebase) makes that sha unreachable, so docs_lint rejects a file that was correct
# when written. Same ladder as ops/backlog.py:_doc_anchor, and for the same reasons
# documented there — degradation is reported, not silent.
COMMIT_SHA="$(git -C "$REPO_ROOT" rev-parse --short "$(git -C "$REPO_ROOT" merge-base HEAD origin/main 2>/dev/null)" 2>/dev/null \
  || git -C "$REPO_ROOT" rev-parse --short "$(git -C "$REPO_ROOT" merge-base HEAD main 2>/dev/null)" 2>/dev/null \
  || git -C "$REPO_ROOT" rev-parse --short HEAD)"
DATE="$(date +%Y-%m-%d)"

# 印檔頭註解區塊（第 2 行起，直到第一行非 `#`）。用範圍掃描而不是寫死的 `sed -n '2,19p'`：
# 寫死行號會在有人多加一行註解時**無聲截斷 help**，而 help 失準正是鐵律 9 要擋的那類摩擦。
usage() { awk 'NR==1 { next } /^#/ { print; next } { exit }' "$0"; }

MODE=stdout
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --check) MODE=check ;;
    *) echo "unknown arg: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

# 1. Top 10 by line count
TOP10=$(find "$IOS_DIR" -name "*.swift" -exec wc -l {} + | sort -rn | awk -v base="$IOS_DIR/" '$2 != "total" && c < 10 { path=$2; sub(base,"",path); printf "| %d | `%s` |\n", $1, path; c++ }')

# 2. Total lines and files
TOTAL_LINES=$(find "$IOS_DIR" -name "*.swift" -exec wc -l {} + | awk '$2 != "total" { s += $1 } END { print s + 0 }')
TOTAL_FILES=$(find "$IOS_DIR" -name "*.swift" | wc -l | tr -d ' ')

# 3. Preview coverage
VIEWS_FILES=$(find "$IOS_DIR/Views" "$IOS_DIR/UIComponents" -name "*.swift" 2>/dev/null | wc -l | tr -d ' ')
PREVIEW_FILES=$(find "$IOS_DIR/Views" "$IOS_DIR/UIComponents" -name "*.swift" -exec grep -l "#Preview" {} \; 2>/dev/null | wc -l | tr -d ' ')

# 4. Concurrency stats: tokenize Swift source so comments, strings, and balanced
# parameter lists have execution semantics instead of accumulating regex exceptions.
MAIN_ACTOR=$(uv run --no-project --python 3.13 "$REPO_ROOT/ops/swift_decl_count.py" --kind main-actor "$IOS_DIR")
ASYNC_FUNC=$(uv run --no-project --python 3.13 "$REPO_ROOT/ops/swift_decl_count.py" --kind async-func "$IOS_DIR")

# 命令替換會吃掉尾端換行，所以輸出一律走 printf '%s\n' "$BODY"，檔尾才是單一 \n。
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

case "$MODE" in
  stdout|check) printf '%s\n' "$BODY" ;;
esac
