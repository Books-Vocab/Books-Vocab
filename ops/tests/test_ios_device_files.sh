#!/bin/bash
# 離線測試 ios_device_files.sh 的命令組裝（--dry-run，不碰真機）。
# 釘住 devicectl 的旗標不一致事實：info files 用 --username、copy from 用 --user。
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TOOL="$REPO/ops/ios_device_files.sh"
FAIL=0
fail() { echo "FAIL: $1"; FAIL=1; }

[ -x "$TOOL" ] || { echo "FAIL: tool 不存在或不可執行"; exit 1; }

# list → info files + --username
OUT=$("$TOOL" list --device FAKE-1111 --dry-run --sub Documents)
echo "$OUT" | grep -q "device info files" || fail "list 未走 info files"
echo "$OUT" | grep -q -- "--username mobile" || fail "list 未用 --username（devicectl info files 的旗標）"
echo "$OUT" | grep -q -- "--subdirectory Documents" || fail "list 未帶 --subdirectory"
echo "$OUT" | grep -q -- "--device FAKE-1111" || fail "list 未帶指定裝置"

# pull → copy from + --user
OUT=$("$TOOL" pull "Documents/x.bin" /tmp/x.bin --device FAKE-1111 --dry-run)
echo "$OUT" | grep -q "device copy from" || fail "pull 未走 copy from"
echo "$OUT" | grep -q -- "--user mobile" || fail "pull 未用 --user（devicectl copy from 的旗標）"
echo "$OUT" | grep -q -- "--source Documents/x.bin" || fail "pull 未帶 source"

# pull-store → 兩 store × 三件套 = 6 條 copy 命令
OUT=$("$TOOL" pull-store --device FAKE-1111 --dry-run --out /tmp/kg_dft_test)
CNT=$(echo "$OUT" | grep -c "device copy from")
[ "$CNT" -eq 6 ] || fail "pull-store 應發 6 條 copy（CloudStore+LocalStore 三件套），實際 $CNT"
echo "$OUT" | grep -q "CloudStore.store-wal" || fail "pull-store 缺 wal"

# 自訂 bundle id 透傳
OUT=$("$TOOL" list --device FAKE-1111 --app com.example.other --dry-run)
echo "$OUT" | grep -q -- "--domain-identifier com.example.other" || fail "--app 未透傳"

# 未知子命令 → usage + 非零
if "$TOOL" frobnicate >/dev/null 2>&1; then fail "未知子命令應非零退出"; fi

if [ "$FAIL" -eq 0 ]; then echo "PASS: ios_device_files 全部斷言通過"; else exit 1; fi
