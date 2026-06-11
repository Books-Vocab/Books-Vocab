#!/bin/bash
# 離線測試 ios_device_logs.sh 的命令組裝（--dry-run，不碰真機）。
# 釘住 pymobiledevice3 介面事實：syslog live 用 -pn 過濾 process、
# crash pull 用 --match regex 過濾 basename、syslog collect 產 .logarchive。
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TOOL="$REPO/ops/ios_device_logs.sh"
FAIL=0
fail() { echo "FAIL: $1"; FAIL=1; }

[ -x "$TOOL" ] || { echo "FAIL: tool 不存在或不可執行"; exit 1; }

# syslog → syslog live + -pn 預設 process + timeout 預設 30s
OUT=$("$TOOL" syslog --dry-run)
echo "$OUT" | grep -q "syslog live" || fail "syslog 未走 syslog live"
echo "$OUT" | grep -q -- "-pn BooksAndVocab" || fail "syslog 未帶預設 process 過濾"
echo "$OUT" | grep -q "timeout 30" || fail "syslog 未帶預設 30s timeout"

# syslog --proc / --duration 0（無 timeout）/ --match / --out 透傳
OUT=$("$TOOL" syslog --proc otherproc --duration 0 --match cloudkit --out /tmp/x.log --dry-run)
echo "$OUT" | grep -q -- "-pn otherproc" || fail "--proc 未透傳"
echo "$OUT" | grep -q "timeout" && fail "--duration 0 不應帶 timeout"
echo "$OUT" | grep -q -- "-m cloudkit" || fail "--match 未透傳成 -m"
echo "$OUT" | grep -q -- "-o /tmp/x.log" || fail "--out 未透傳成 -o"

# syslog --duration 非數字 → fail-fast（不可靜默落入無 timeout 永久串流）
if "$TOOL" syslog --duration abc --dry-run >/dev/null 2>&1; then fail "--duration 非數字應非零退出"; fi

# collect → syslog collect 到輸出目錄 + --age-limit 透傳
OUT=$("$TOOL" collect --out /tmp/kg_la_test --age-limit 2 --dry-run)
echo "$OUT" | grep -q "syslog collect" || fail "collect 未走 syslog collect"
echo "$OUT" | grep -q "/tmp/kg_la_test" || fail "collect 未帶輸出目錄"
echo "$OUT" | grep -q -- "--age-limit 2" || fail "--age-limit 未透傳"

# crashes → crash ls，depth 2（iOS 會把已讀 .ips retire 進 /Retired/，depth 1 誤判沒 crash）
OUT=$("$TOOL" crashes --dry-run)
echo "$OUT" | grep -q -- "crash ls -d 2" || fail "crashes 未帶 depth 2（Retired 不可見）"

# pull-crashes → crash pull + 預設 --match BooksAndVocab + 預設輸出目錄
# + 雙掃 top-level 與 /Retired（enumerate 不遞迴，已讀 .ips 被 retire 進子目錄）
OUT=$("$TOOL" pull-crashes --dry-run)
echo "$OUT" | grep -q "crash pull" || fail "pull-crashes 未走 crash pull"
echo "$OUT" | grep -q -- "--match BooksAndVocab" || fail "pull-crashes 未帶預設 process match"
echo "$OUT" | grep -q "/tmp/kg_device_crashes" || fail "pull-crashes 未帶預設輸出目錄"
echo "$OUT" | grep -q -- "--remote-file /Retired" || fail "pull-crashes 未掃 /Retired"
CNT=$(echo "$OUT" | grep -c "crash pull")
[ "$CNT" -eq 2 ] || fail "pull-crashes 應發 2 條 pull（top-level + Retired），實際 $CNT"

# pull-crashes --parse → 追加 remote parse-latest（afc 操作，吃 --match 不吃本地目錄）
OUT=$("$TOOL" pull-crashes --parse --dry-run)
echo "$OUT" | grep -q -- "crash parse-latest --match BooksAndVocab" || fail "--parse 未追加 remote parse-latest --match"

# parse → crash parse <remote.ips>
OUT=$("$TOOL" parse /BooksAndVocab-2026-06-11-150059.ips --dry-run)
echo "$OUT" | grep -q -- "crash parse /BooksAndVocab-2026-06-11-150059.ips" || fail "parse 未帶 remote 檔名"

# --udid 透傳到 pymobiledevice3
OUT=$("$TOOL" crashes --udid FAKE-UDID --dry-run)
echo "$OUT" | grep -q -- "--udid FAKE-UDID" || fail "--udid 未透傳"

# 未知子命令 → usage + 非零
if "$TOOL" frobnicate >/dev/null 2>&1; then fail "未知子命令應非零退出"; fi

# --help → exit 0 + 用法，且不得洩漏程式碼（usage sed 行號範圍錯的慣性 bug）
"$TOOL" --help | grep -q "用法" || fail "--help 未印用法"
"$TOOL" --help | grep -q "set -uo pipefail" && fail "usage 洩漏程式碼（sed 範圍超出註解區）"

if [ "$FAIL" -eq 0 ]; then echo "PASS: ios_device_logs 全部斷言通過"; else exit 1; fi
