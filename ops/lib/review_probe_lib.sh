# review_flip_probe 純邏輯 helpers（無真機依賴，可單測）。
# 由 ops/review_flip_probe.sh source；測試 ops/tests/test_review_probe.sh。
# bash 3.2 + set -u 相容。

# kg_probe_wait_pid <pid> <timeout_secs> <label> [early_success_cmd]
# 統一等待原語（取代各路徑手搓的輪詢迴圈）：
#   rc=0  early_success_cmd 成立（提早返回）；無 early_success_cmd 時 = pid 以 0 結束
#   rc=1  pid 非零結束（無 early_success_cmd 模式）
#   rc=2  等待 early_success 期間 pid 早死
#   rc=3  逾時（pid 已被本函式 TERM→KILL）
# heartbeat：每 KG_PROBE_HEARTBEAT_SECS（預設 15s）印一行到 stderr，
# 讓「在等什麼、等多久了、何時放棄」對人和 agent 都可見。
# 輪詢間隔 KG_PROBE_POLL_SECS（預設 5s）。
kg_probe_wait_pid() {
  local pid="$1" timeout_secs="$2" label="$3" early_cmd="${4:-}"
  local poll="${KG_PROBE_POLL_SECS:-5}"
  local hb="${KG_PROBE_HEARTBEAT_SECS:-15}"
  local start="$SECONDS" last_hb=0 elapsed=0 rc=0

  while :; do
    if [[ -n "$early_cmd" ]] && eval "$early_cmd"; then
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      [[ -n "$early_cmd" ]] && return 2
      rc=0
      wait "$pid" 2>/dev/null || rc=$?
      [[ "$rc" -eq 0 ]] && return 0
      return 1
    fi
    elapsed=$((SECONDS - start))
    if ((elapsed >= timeout_secs)); then
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
      return 3
    fi
    if ((elapsed - last_hb >= hb)); then
      echo "[$label] waiting… elapsed=${elapsed}s/${timeout_secs}s" >&2
      last_hb="$elapsed"
    fi
    sleep "$poll"
  done
}

# kg_probe_passcode_required <lockstate_json_path>
# 判讀 `devicectl device info lockState --json-output` 的結果。
# 輸出 true / false / unknown（檔案缺、JSON 壞、欄位缺一律 unknown——
# 不可矇成 false 讓鎖屏裝置溜進懸掛路徑，也不可矇成 true 誤擋好機）。
kg_probe_passcode_required() {
  local json="$1" val
  val="$(jq -r '.result.passcodeRequired' "$json" 2>/dev/null || true)"
  case "$val" in
    true | false) echo "$val" ;;
    *) echo "unknown" ;;
  esac
}

# kg_probe_write_verdict <file> <result> [key=value ...]
# verdict 檔單行契約：`RESULT=<result> [key=value ...]`，固定由呼叫端給鍵序。
kg_probe_write_verdict() {
  local file="$1" result="$2"
  shift 2
  local line="RESULT=$result" part
  for part in "$@"; do
    line="$line $part"
  done
  printf '%s\n' "$line" >"$file"
}
