#!/usr/bin/env bash
# test_lldb_forensics_timeout.sh — IMP-20260805-c6f5e3：證明
# ops/tests/test_lldb_crash_forensics.sh 的**每一顆** lldb 都有界。
#
# 為什麼要另立一支：那支測試自己的 PASS 涵蓋不到「掛住」。掛住的時候它不會紅——它會
# 一個字都不輸出地活著，而 streaming_command 的 heartbeat 每 20 秒忠實回報 alive=true，
# 於是一個永遠不會結束的 block gate 看起來完全健康（實測一次 elapsed=4541s 仍 alive）。
# heartbeat 證明的是「程序存在」，不是「程序在前進」，所以界線必須由被測腳本自己畫，
# 而「界線真的存在」必須由外面這支證。
#
# 方法：給它一顆**永遠不會結束的假 lldb**，看它會不會在有限時間內自己紅。
# 刻意不用 grep 原始碼當斷言：grep 只證明字串在某處，不證明四個呼叫點都真的走那條路
# （四個裡漏掉一個，就是 gate 掛死的那一個）。
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TARGET="$REPO/ops/tests/test_lldb_crash_forensics.sh"
TMP="$(mktemp -d -t kg_lldb_timeout_XXXXXX)"

# shellcheck source=../lib/review_probe_lib.sh
. "$REPO/ops/lib/review_probe_lib.sh"

FAIL=0
ok()     { echo "  ✓ $1"; }
fail_t() { echo "  ✗ $1"; FAIL=1; }

MARKER="kg-fake-lldb-$$"
FAKE="$TMP/$MARKER"
# 假 lldb 不用 `exec sleep`：exec 之後 argv 只剩 `sleep`，marker 消失，殘留檢查就變成
# 恆真。用迴圈保留 argv 裡的 marker，被 TERM 時最多留一顆活不過 1 秒的 sleep。
cat > "$FAKE" <<'EOF'
#!/bin/sh
while :; do sleep 1; done
EOF
chmod +x "$FAKE"

# 任何離開路徑都收屍（含早退），再清目錄——OUT 在 TMP 裡，所以清理只能發生在最後。
cleanup() { pkill -9 -f "$MARKER" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

[ -x "$TARGET" ] || { echo "FAIL: target missing or not executable: $TARGET"; exit 1; }

echo "── 假 lldb 永不結束時，被測腳本必須在有限時間內具名失敗 ──"

OUT="$TMP/target.out"
OUTER_BUDGET=90
KG_LLDB_CMD="$FAKE" KG_LLDB_CASE_TIMEOUT=3 KG_PROBE_POLL_SECS=1 KG_PROBE_HEARTBEAT_SECS=60 \
  "$TARGET" >"$OUT" 2>&1 </dev/null &
target_pid=$!
start="$SECONDS"
KG_PROBE_POLL_SECS=2 KG_PROBE_HEARTBEAT_SECS=20 \
  kg_probe_wait_pid "$target_pid" "$OUTER_BUDGET" "lldb-forensics-under-fake"
wait_rc=$?
elapsed=$((SECONDS - start))

if [ "$wait_rc" -eq 3 ]; then
  fail_t "被測腳本在 ${OUTER_BUDGET}s 內沒有結束——lldb 呼叫仍是無界的（外層已 TERM→KILL）"
else
  ok "被測腳本自己收斂（elapsed=${elapsed}s，外層預算 ${OUTER_BUDGET}s）"
fi

# rc=0 表示 pid 以 0 結束；逾時的 lldb 必須讓被測腳本**紅**，不可被吞掉。
if [ "$wait_rc" -eq 0 ]; then
  fail_t "被測腳本在四顆 lldb 全部逾時的情況下仍回綠——逾時被吞了"
elif [ "$wait_rc" -eq 1 ]; then
  ok "逾時讓被測腳本以非零 exit 收尾"
fi

# 四個呼叫點逐一具名。少一個 = 那個呼叫點沒走有界路徑，正是會掛死 gate 的那顆。
hit=0
for label in case1-crash case2-breakpoint case3-sigabrt case4-dump-failure; do
  if grep -q "TIMEOUT lldb:${label}" "$OUT"; then
    hit=$((hit + 1))
  else
    fail_t "呼叫點 ${label} 沒有印出具名逾時（未走 run_lldb 或未使用 KG_LLDB_CMD 接縫）"
  fi
done
[ "$hit" -eq 4 ] && ok "四個 lldb 呼叫點都在預算內具名逾時"

# 逾時路徑必須收屍：假 lldb 不可留在系統裡。
sleep 2
leftover="$(pgrep -f "$MARKER" 2>/dev/null | wc -l | tr -d ' ')"
if [ "$leftover" != "0" ]; then
  pkill -9 -f "$MARKER" 2>/dev/null || true
  fail_t "逾時後留下 ${leftover} 個假 lldb 殘留程序（已代為清掉）"
else
  ok "逾時後零殘留程序"
fi

if [ "$FAIL" -eq 0 ]; then
  echo "PASS: lldb 呼叫點全部有界"
else
  echo "=== 被測腳本輸出 tail ==="
  tail -20 "$OUT" 2>/dev/null
  exit 1
fi
