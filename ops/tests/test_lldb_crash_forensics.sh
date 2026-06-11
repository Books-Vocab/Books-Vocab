#!/bin/bash
# TDD test for ops/lldb_crash_forensics.py — 真機/本機 crash 自動取證 stop-hook。
#
# 契約（由 2026-06-11 spike 釘死：lldb batch mode 的 stop-hook 會在 crash 觸發，
# exception stop reason 拿得到全量 frame）：
#   1. `command script import` 後 stop-hook 已註冊、`kgdump` 命令可用。
#   2. process 因 stack-overflow crash（exception/signal stop）→ 自動寫 dump 檔
#      到 $KG_LLDB_DUMP_DIR，內容含：stop reason、全量 frame 表（含遞迴函式名）、
#      fp 差分 frame size（本 crasher 每層 ≥65536）、stack region 段。
#   3. breakpoint stop 不觸發自動 dump（否則每次斷點都噴檔案）。
#   4. `kgdump` 在任何 stop 點可手動 dump。
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MODULE="$REPO/ops/lldb_crash_forensics.py"
TMP="$(mktemp -d /tmp/kg_lldb_forensics_test.XXXX)"
trap 'rm -rf "$TMP"' EXIT
FAIL=0

fail() { echo "FAIL: $1"; FAIL=1; }

[ -f "$MODULE" ] || { echo "FAIL: module missing: $MODULE"; exit 1; }

# --- crasher：每層 64KB 的無限遞迴 → 必然 stack overflow (EXC_BAD_ACCESS) ---
cat > "$TMP/crasher.c" <<'EOF'
volatile char sink;
__attribute__((noinline)) void eat(int depth) {
    char buf[65536];
    buf[0] = (char)depth;
    sink = buf[0];
    eat(depth + 1);
}
int main(void) { eat(0); return 0; }
EOF
cc -O0 -o "$TMP/crasher" "$TMP/crasher.c" || { echo "FAIL: crasher compile"; exit 1; }

# --- case 1: crash → 自動 dump ---
DUMPS1="$TMP/dumps1"
mkdir -p "$DUMPS1"
KG_LLDB_DUMP_DIR="$DUMPS1" xcrun lldb -b "$TMP/crasher" \
    -o "command script import $MODULE" \
    -o "run" > "$TMP/lldb1.log" 2>&1

grep -q "kg-forensics" "$TMP/lldb1.log" || fail "import 無註冊訊息（kg-forensics）"

DUMP_COUNT=$(find "$DUMPS1" -name "*.txt" ! -name "LATEST*" | wc -l | tr -d ' ')
[ "$DUMP_COUNT" -ge 1 ] || fail "crash 後無自動 dump（count=$DUMP_COUNT）"

DUMP_FILE=$(find "$DUMPS1" -name "*.txt" ! -name "LATEST*" | head -1)
if [ -n "${DUMP_FILE:-}" ]; then
    grep -qi "stop reason" "$DUMP_FILE" || fail "dump 缺 stop reason"
    grep -q "eat" "$DUMP_FILE" || fail "dump 缺遞迴函式名 eat"
    # stack region 必須是真實 bounds（stop-hook 內 HandleCommand 無 process
    # context，必須走 SBProcess API；error 文字不算數）
    grep -qE "region: \[0x[0-9a-f]+ - 0x[0-9a-f]+\)" "$DUMP_FILE" || fail "dump 缺真實 stack region bounds"
    # 全量 frame：crasher 在 8MB stack 上每層 64KB+，深度應 >100
    FRAME_ROWS=$(grep -cE "^ *[0-9]+ +0x" "$DUMP_FILE")
    [ "$FRAME_ROWS" -gt 100 ] || fail "frame 表非全量（rows=$FRAME_ROWS，應 >100）"
    # fp 差分 frame size：至少一層 ≥65536
    grep -E "^ *[0-9]+ +0x" "$DUMP_FILE" | awk '{for(i=1;i<=NF;i++) if ($i ~ /^[0-9]+$/ && $i+0>=65536) found=1} END {exit found?0:1}' \
        || fail "frame size 欄無 ≥65536 的層（fp 差分未實作或錯誤）"
    # LATEST 指標檔
    [ -e "$DUMPS1/LATEST.txt" ] || fail "缺 LATEST.txt 指標"
fi

# --- case 2: breakpoint stop 不自動 dump；kgdump 手動可 dump ---
DUMPS2="$TMP/dumps2"
mkdir -p "$DUMPS2"
KG_LLDB_DUMP_DIR="$DUMPS2" xcrun lldb -b "$TMP/crasher" \
    -o "command script import $MODULE" \
    -o "breakpoint set -n main" \
    -o "run" \
    -o "script import glob,os; print('BP_DUMPS=%d' % len([p for p in glob.glob(os.environ['KG_LLDB_DUMP_DIR']+'/*.txt') if 'LATEST' not in p]))" \
    -o "kgdump" \
    -o "script import glob,os; print('MANUAL_DUMPS=%d' % len([p for p in glob.glob(os.environ['KG_LLDB_DUMP_DIR']+'/*.txt') if 'LATEST' not in p]))" \
    > "$TMP/lldb2.log" 2>&1

grep -q "BP_DUMPS=0" "$TMP/lldb2.log" || fail "breakpoint stop 觸發了自動 dump（應為 0）"
grep -q "MANUAL_DUMPS=1" "$TMP/lldb2.log" || fail "kgdump 手動 dump 失敗（應為 1）"

# --- case 3: 致命 signal（SIGABRT）分支也要自動 dump ---
cat > "$TMP/aborter.c" <<'EOF'
#include <stdlib.h>
int main(void) { abort(); return 0; }
EOF
cc -O0 -o "$TMP/aborter" "$TMP/aborter.c" || { echo "FAIL: aborter compile"; exit 1; }
DUMPS3="$TMP/dumps3"
mkdir -p "$DUMPS3"
KG_LLDB_DUMP_DIR="$DUMPS3" xcrun lldb -b "$TMP/aborter" \
    -o "command script import $MODULE" \
    -o "run" > "$TMP/lldb3.log" 2>&1
ABORT_DUMPS=$(find "$DUMPS3" -name "*.txt" ! -name "LATEST*" | wc -l | tr -d ' ')
[ "$ABORT_DUMPS" -ge 1 ] || fail "SIGABRT 未觸發自動 dump（_FATAL_SIGNALS 分支回歸）"

# --- case 4: dump 寫不出去必須出聲（不可靜默失敗）---
# 用普通檔案擋路讓 dump dir 不可建（os.makedirs 必失敗）
touch "$TMP/blocker"
KG_LLDB_DUMP_DIR="$TMP/blocker/sub" xcrun lldb -b "$TMP/crasher" \
    -o "command script import $MODULE" \
    -o "run" > "$TMP/lldb4.log" 2>&1 || true
grep -q "kg-forensics.*FAILED" "$TMP/lldb4.log" || fail "dump 失敗時未在 console 出聲（靜默失敗回歸）"

# --- case 5: 安裝器 marker 邊界 —— END 遺失時拒絕改寫，不吃掉使用者設定 ---
FAKE_HOME="$TMP/fakehome"
mkdir -p "$FAKE_HOME"
printf '# user stuff before\n# >>> kg-crash-forensics >>>\ncommand script import /old/path.py\n# user stuff after (END marker 遺失)\n' > "$FAKE_HOME/.lldbinit"
if HOME="$FAKE_HOME" "$REPO/ops/install_lldb_forensics.sh" >/dev/null 2>&1; then
    fail "END marker 遺失時安裝器應拒絕改寫"
fi
grep -q "user stuff after" "$FAKE_HOME/.lldbinit" || fail "安裝器吃掉了 marker 後的使用者設定"

if [ "$FAIL" -eq 0 ]; then
    echo "PASS: lldb_crash_forensics 全部斷言通過"
else
    for log in "$TMP"/lldb*.log; do
        echo "=== $(basename "$log") tail ==="; tail -15 "$log"
    done
    exit 1
fi
