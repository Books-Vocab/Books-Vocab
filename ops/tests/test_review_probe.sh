#!/bin/bash
# review_flip_probe 純邏輯單元測試（不碰真機）。
# 覆蓋 ops/lib/review_probe_lib.sh：等待原語的四種出口、heartbeat、
# lockState 判讀、verdict 行格式。device 相依薄殼不在此 mock，由真機 run 驗。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$SCRIPT_DIR/../lib/review_probe_lib.sh"

PASS=0
FAIL=0
note() { printf '%s\n' "$*"; }
ok()   { PASS=$((PASS + 1)); note "  ok  - $1"; }
bad()  { FAIL=$((FAIL + 1)); note "  FAIL- $1"; }
check() { # check <desc> <actual> <expected>
  if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 (got=$2 want=$3)"; fi
}

[[ -f "$LIB" ]] || { note "missing lib: $LIB"; exit 1; }
source "$LIB"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 快輪詢讓測試秒級完成
export KG_PROBE_POLL_SECS=1
export KG_PROBE_HEARTBEAT_SECS=1

note "case 1: early_success 條件成立 → rc=0，提早返回"
sleep 30 & pid=$!
start=$SECONDS
touch "$TMP/marker1"
rc=0; kg_probe_wait_pid "$pid" 20 "c1" "test -f '$TMP/marker1'" 2>/dev/null || rc=$?
check "rc==0" "$rc" "0"
check "提早返回（<5s）" "$(( SECONDS - start < 5 ))" "1"
kill "$pid" 2>/dev/null || true

note "case 2: 等 marker 期間 pid 早死 → rc=2"
sleep 1 & pid=$!
rc=0; kg_probe_wait_pid "$pid" 20 "c2" "test -f '$TMP/never'" 2>/dev/null || rc=$?
check "rc==2" "$rc" "2"

note "case 3: timeout → rc=3 且 pid 被 kill"
sleep 60 & pid=$!
rc=0; kg_probe_wait_pid "$pid" 2 "c3" "test -f '$TMP/never'" 2>/dev/null || rc=$?
check "rc==3" "$rc" "3"
sleep 1
if kill -0 "$pid" 2>/dev/null; then bad "pid 應已被 kill"; kill -9 "$pid" 2>/dev/null || true; else ok "pid 已被 kill"; fi

note "case 4: 無 early_success，pid 正常結束 → rc=0"
sleep 1 & pid=$!
rc=0; kg_probe_wait_pid "$pid" 20 "c4" 2>/dev/null || rc=$?
check "rc==0" "$rc" "0"

note "case 5: 無 early_success，pid 非零結束 → rc=1"
( sleep 1; exit 5 ) & pid=$!
rc=0; kg_probe_wait_pid "$pid" 20 "c5" 2>/dev/null || rc=$?
check "rc==1" "$rc" "1"

note "case 6: heartbeat 落在 stderr 且含 elapsed"
sleep 60 & pid=$!
hb="$TMP/hb.log"
# timeout 與 hb 拉開（5 vs 1）：排程停滯下 elapsed 跳格也不會先觸 timeout
rc=0; kg_probe_wait_pid "$pid" 5 "c6-label" "test -f '$TMP/never'" 2>"$hb" || rc=$?
kill -9 "$pid" 2>/dev/null || true
if grep -q 'c6-label' "$hb" && grep -q 'elapsed=' "$hb"; then
  ok "heartbeat 行存在且含 label/elapsed"
else
  bad "heartbeat 缺失: $(cat "$hb")"
fi

note "case 6b: pid 死後 marker 已到 → rc=0 非 2（死後補查競態窗）"
# 有狀態 early_cmd：第一次呼叫（loop top）回 1 並留痕，第二次（死後補查）回 0
# —— 精準注入「early 檢查未到 → 程序退出 → marker 其實已寫」的時序。
ec_flaky() { if [[ -f "$TMP/c6b_seen" ]]; then return 0; fi; touch "$TMP/c6b_seen"; return 1; }
sleep 0.1 & pid=$!
sleep 0.5   # 確保 pid 已死，loop top 第一次 early 檢查必走「未到」分支
rc=0; kg_probe_wait_pid "$pid" 20 "c6b" "ec_flaky" 2>/dev/null || rc=$?
check "rc==0（非 launch_process_died 誤判）" "$rc" "0"

note "case 7: lockState 判讀 — 鎖著"
cat >"$TMP/locked.json" <<'EOF'
{"result": {"deviceIdentifier": "X", "passcodeRequired": true, "unlockedSinceBoot": true}}
EOF
check "locked→true" "$(kg_probe_passcode_required "$TMP/locked.json")" "true"

note "case 8: lockState 判讀 — 解鎖"
cat >"$TMP/unlocked.json" <<'EOF'
{"result": {"deviceIdentifier": "X", "passcodeRequired": false, "unlockedSinceBoot": true}}
EOF
check "unlocked→false" "$(kg_probe_passcode_required "$TMP/unlocked.json")" "false"

note "case 9: lockState 判讀 — 檔案缺 / JSON 壞 → unknown（不可矇）"
check "missing→unknown" "$(kg_probe_passcode_required "$TMP/nope.json")" "unknown"
printf 'not json' >"$TMP/garbage.json"
check "garbage→unknown" "$(kg_probe_passcode_required "$TMP/garbage.json")" "unknown"

note "case 10: verdict 行格式 RESULT=<r> <detail> 固定鍵序"
v="$TMP/verdict"
kg_probe_write_verdict "$v" "invalid" "reason=device_locked" "console=/c" "jsonl=/j" "out=/o"
line="$(cat "$v")"
check "verdict 行" "$line" "RESULT=invalid reason=device_locked console=/c jsonl=/j out=/o"

note "case 11: bash 3.2 + set -u 相容（空 detail 不炸）"
rc=0; ( set -u; kg_probe_write_verdict "$TMP/v2" "pass" ) || rc=$?
check "空 detail rc==0" "$rc" "0"
check "空 detail 行" "$(cat "$TMP/v2")" "RESULT=pass"

note "case 12: review_flip_probe shell requires explicit UI World"
set +e
out="$("$SCRIPT_DIR/../review_flip_probe.sh" --simulator --skip-build 2>&1)"
rc=$?
set -e
check "missing dataset rc==64" "$rc" "64"
if grep -q -- '--dataset <name> or --dataset-file <path> is required' <<<"$out"; then
  ok "missing dataset error is explicit"
else
  bad "missing dataset error unclear: $out"
fi

note "case 13: review_flip_probe rejects dataset + dataset-file together"
set +e
out="$("$SCRIPT_DIR/../review_flip_probe.sh" --simulator --dataset marketing_demo --dataset-file "$TMP/nope.json" --skip-build 2>&1)"
rc=$?
set -e
check "exclusive dataset rc==64" "$rc" "64"
if grep -q 'choose either --dataset or --dataset-file' <<<"$out"; then
  ok "dataset exclusivity error is explicit"
else
  bad "dataset exclusivity error unclear: $out"
fi

note "case 14: review_flip_probe validates UI World asset hashes before launch"
jq '.assets.books.catalog_reader_epub.sha256 = "0000000000000000000000000000000000000000000000000000000000000000"' \
  "$SCRIPT_DIR/../fixtures/ui_worlds/marketing_demo.json" >"$TMP/bad_hash_ui_world.json"
set +e
out="$("$SCRIPT_DIR/../review_flip_probe.sh" --simulator --dataset-file "$TMP/bad_hash_ui_world.json" --skip-build 2>&1)"
rc=$?
set -e
check "asset hash drift rc==64" "$rc" "64"
if grep -q 'assets.books.catalog_reader_epub.sha256 mismatch' <<<"$out"; then
  ok "asset hash drift error names the asset"
else
  bad "asset hash drift error unclear: $out"
fi

note ""
note "passed=$PASS failed=$FAIL"
[[ "$FAIL" -eq 0 ]]
