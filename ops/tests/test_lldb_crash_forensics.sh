#!/bin/bash
# TDD test for ops/lldb_crash_forensics.py — 真機/本機 crash 自動取證 stop-hook。
#
# 契約（由 2026-06-11 spike 釘死：lldb batch mode 的 stop-hook 會在 crash 觸發，
# exception stop reason 拿得到全量 frame）：
#   1. `command script import` 後 stop-hook 已註冊、`kgdump` 命令可用。
#   2. process 因 stack-overflow crash（exception/signal stop）→ 自動寫 dump 檔
#      到 ${KG_LLDB_DUMP_DIR}，內容含：stop reason、全量 frame 表（含遞迴函式名）、
#      fp 差分 frame size（本 crasher 每層 ≥65536）、stack region 段。
#   3. breakpoint stop 不觸發自動 dump（否則每次斷點都噴檔案）。
#   4. `kgdump` 在任何 stop 點可手動 dump。
#
# 每顆 lldb 有兩道界線（IMP-20260805-c6f5e3，缺一不可）：
#   ① `-k quit` —— `--batch` 在 target crash 時會**回到互動 prompt**（`lldb --help`：
#      `--one-line-on-crash <command>` "When in batch mode, tells the debugger to run
#      this one-line lldb command if the target crashes"）。本檔四個 case 有三個以
#      crash 收尾，於是 lldb 把 dump 寫完之後就坐在 prompt 不退：2026-08-05 實測一顆
#      掛滿 2.5 分鐘仍 alive 且 dump 早已落地，本條 entry 記錄過的那顆掛了 65 分鐘。
#      補上 `-k quit` 後同一個 case 實測 3/3 皆 3–5s、rc=0、dump 完整、零殘留程序。
#   ② 有界等待 —— ① 是根因，但它押注在「lldb 會照 flag 行事」。真的再掛時本檔必須在
#      有限時間內**紅**，而不是把 cutover gate 掛死：heartbeat 只證明程序還活著，不證明
#      它在前進，所以界線得由這裡自己畫（逾時 → 具名 FAIL + TERM→KILL + 清殘留）。
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MODULE="$REPO/ops/lldb_crash_forensics.py"
TMP="$(mktemp -d /tmp/kg_lldb_forensics_test.XXXX)"
FAIL=0

# 有界等待原語（heartbeat + TERM→KILL）沿用既有的 kg_probe_wait_pid，不另造一套。
# shellcheck source=../lib/review_probe_lib.sh
. "$REPO/ops/lib/review_probe_lib.sh"

# 逾時預算：實測單顆 crash case 3–5s（`-k quit` 之後）。180s 給的是「機器爆滿時仍算
# 正常」的兩個數量級餘裕，超過就一定是掛住而不是慢。
CASE_TIMEOUT="${KG_LLDB_CASE_TIMEOUT:-180}"
: "${KG_PROBE_POLL_SECS:=2}"
: "${KG_PROBE_HEARTBEAT_SECS:=15}"
export KG_PROBE_POLL_SECS KG_PROBE_HEARTBEAT_SECS
# lldb 命令是可注入的接縫：ops/tests/test_lldb_forensics_timeout.sh 用一支永不結束的
# 假 lldb 換掉它，證明「四個呼叫點都真的有界」——那條測試沒有這個接縫就只能改成
# grep 原始碼，而 grep 證明不了行為。
LLDB_CMD_LINE="${KG_LLDB_CMD:-xcrun lldb}"
read -r -a LLDB_CMD <<<"$LLDB_CMD_LINE"

fail() { echo "FAIL: $1"; FAIL=1; }

# 殺掉 argv 指向本輪 TMP 的殘留程序（lldb 自己 + inferior）。debugserver 的 argv 不含
# 任何路徑（`debugserver --native-regs --setsid --fd=8`），字串比對抓不到它——但它在
# inferior 死掉、與 lldb 的連線斷掉之後會自行退出，所以殺 inferior 就夠。刻意不做
# 「殺掉所有 debugserver」：那會打掉使用者當下的 Xcode debug session。
kill_tmp_procs() {
  local sig="$1" pid
  for pid in $(pgrep -f "$TMP" 2>/dev/null); do
    [ "$pid" = "$$" ] && continue
    kill "-$sig" "$pid" 2>/dev/null || true
  done
}

cleanup() {
  if pgrep -f "$TMP" >/dev/null 2>&1; then
    kill_tmp_procs TERM
    sleep 1
    kill_tmp_procs KILL
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

# run_lldb <label> <logfile> <lldb 參數...> —— 有界跑一顆 lldb。
# 逾時不是靜默、不是掛住：具名 FAIL + 收屍，然後讓後面的斷言照常跑完（它們會因為
# 缺 dump 而紅，但**根因那一行**已經先印出來了）。
run_lldb() {
  local label="$1" log="$2"
  shift 2
  local pid rc start="$SECONDS"
  "${LLDB_CMD[@]}" -b -k "quit" "$@" >"$log" 2>&1 </dev/null &
  pid=$!
  kg_probe_wait_pid "$pid" "$CASE_TIMEOUT" "lldb:$label"
  rc=$?
  if [ "$rc" -eq 3 ]; then
    fail "TIMEOUT lldb:${label} 超過 ${CASE_TIMEOUT}s 未結束（已 TERM→KILL）；log=$log"
    kill_tmp_procs TERM
    sleep 1
    kill_tmp_procs KILL
    return 3
  fi
  echo "  lldb:${label} 結束 elapsed=$((SECONDS - start))s"
  return 0
}

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
export KG_LLDB_DUMP_DIR="$DUMPS1"
run_lldb case1-crash "$TMP/lldb1.log" "$TMP/crasher" \
    -o "command script import $MODULE" \
    -o "run"

grep -q "kg-forensics" "$TMP/lldb1.log" || fail "import 無註冊訊息（kg-forensics）"

DUMP_COUNT=$(find "$DUMPS1" -name "*.txt" ! -name "LATEST*" | wc -l | tr -d ' ')
[ "$DUMP_COUNT" -ge 1 ] || fail "crash 後無自動 dump（count=${DUMP_COUNT}）"

DUMP_FILE=$(find "$DUMPS1" -name "*.txt" ! -name "LATEST*" | head -1)
if [ -n "${DUMP_FILE:-}" ]; then
    grep -qi "stop reason" "$DUMP_FILE" || fail "dump 缺 stop reason"
    grep -q "eat" "$DUMP_FILE" || fail "dump 缺遞迴函式名 eat"
    # stack region 必須是真實 bounds（stop-hook 內 HandleCommand 無 process
    # context，必須走 SBProcess API；error 文字不算數）
    grep -qE "region: \[0x[0-9a-f]+ - 0x[0-9a-f]+\)" "$DUMP_FILE" || fail "dump 缺真實 stack region bounds"
    # 全量 frame：crasher 在 8MB stack 上每層 64KB+，深度應 >100
    FRAME_ROWS=$(grep -cE "^ *[0-9]+ +0x" "$DUMP_FILE")
    [ "$FRAME_ROWS" -gt 100 ] || fail "frame 表非全量（rows=${FRAME_ROWS}，應 >100）"
    # fp 差分 frame size：至少一層 ≥65536
    grep -E "^ *[0-9]+ +0x" "$DUMP_FILE" | awk '{for(i=1;i<=NF;i++) if ($i ~ /^[0-9]+$/ && $i+0>=65536) found=1} END {exit found?0:1}' \
        || fail "frame size 欄無 ≥65536 的層（fp 差分未實作或錯誤）"
    # LATEST 指標檔
    [ -e "$DUMPS1/LATEST.txt" ] || fail "缺 LATEST.txt 指標"
fi

# --- case 2: breakpoint stop 不自動 dump；kgdump 手動可 dump ---
DUMPS2="$TMP/dumps2"
mkdir -p "$DUMPS2"
export KG_LLDB_DUMP_DIR="$DUMPS2"
run_lldb case2-breakpoint "$TMP/lldb2.log" "$TMP/crasher" \
    -o "command script import $MODULE" \
    -o "breakpoint set -n main" \
    -o "run" \
    -o "script import glob,os; print('BP_DUMPS=%d' % len([p for p in glob.glob(os.environ['KG_LLDB_DUMP_DIR']+'/*.txt') if 'LATEST' not in p]))" \
    -o "kgdump" \
    -o "script import glob,os; print('MANUAL_DUMPS=%d' % len([p for p in glob.glob(os.environ['KG_LLDB_DUMP_DIR']+'/*.txt') if 'LATEST' not in p]))"

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
export KG_LLDB_DUMP_DIR="$DUMPS3"
run_lldb case3-sigabrt "$TMP/lldb3.log" "$TMP/aborter" \
    -o "command script import $MODULE" \
    -o "run"
ABORT_DUMPS=$(find "$DUMPS3" -name "*.txt" ! -name "LATEST*" | wc -l | tr -d ' ')
[ "$ABORT_DUMPS" -ge 1 ] || fail "SIGABRT 未觸發自動 dump（_FATAL_SIGNALS 分支回歸）"

# --- case 4: dump 寫不出去必須出聲（不可靜默失敗）---
# 用普通檔案擋路讓 dump dir 不可建（os.makedirs 必失敗）
touch "$TMP/blocker"
export KG_LLDB_DUMP_DIR="$TMP/blocker/sub"
run_lldb case4-dump-failure "$TMP/lldb4.log" "$TMP/crasher" \
    -o "command script import $MODULE" \
    -o "run" || true
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
