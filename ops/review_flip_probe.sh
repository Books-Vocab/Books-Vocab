#!/usr/bin/env bash
# review_flip_probe.sh — review-flip 自主量測 run（simulator / 真機）
#
# 一鍵跑完：build → install → launch（fixture 卡組 + autopilot 翻卡）→
# 收 console marker → 拉 JSONL → 預登門檻 verdict。人只需要保證裝置插著解鎖。
#
# Usage:
#   ./ops/review_flip_probe.sh --simulator --dataset <name> [opts]
#   ./ops/review_flip_probe.sh --device <udid> --dataset-file <path> [opts]
# Options:
#   --dataset NAME   UI World under ops/fixtures/ui_worlds/<name>.json（必填，與 --dataset-file 擇一）
#   --dataset-file P UI World JSON path（必填，與 --dataset 擇一）
#   --flips N       翻卡次數（預設 30）
#   --min-flips N   verdict 有效性下限（預設 = --flips）
#   --timeout SECS  等 done/abort marker 的上限（預設 60 + 4×flips）
#   --release       Release configuration（Debug 量測有 observation/最佳化噪音；
#                   Release 才是使用者真相）
#   --instruments   （device only）xctrace 'Animation Hitches' + Time Profiler
#                   包住整個 run — render-server 側 hitch 真相 + hitch 區間內
#                   主執行緒堆疊，同 trace 對時；trace 存 artifacts 目錄。
#                   此模式無 console marker，完成以 time-limit + JSONL 為準。
#   --skip-build    跳過 build，直接用上次產物
#   --out DIR       artifacts 目錄（預設 mktemp）
#
# Verdict：$TMPDIR/kg_review_probe_verdict（KEY=value 一行）+ stdout JSON。
# exit：0=pass 1=fail 2=invalid（run 殘缺，不可下效能結論）64=usage error。

set -euo pipefail

usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# 等待原語 / lockState 判讀 / verdict 行格式（ops/tests/test_review_probe.sh 單測）
source "$SCRIPT_DIR/lib/review_probe_lib.sh"
# shellcheck source=lib/fixture_dataset_env.sh
source "$SCRIPT_DIR/lib/fixture_dataset_env.sh"
BUNDLE_ID="com.Max0228.BooksBrowser"
APP_NAME="BooksAndVocab.app"
JSONL_NAME="kg_review_probe.jsonl"

MODE="" UDID="" FLIPS=30 MIN_FLIPS="" TIMEOUT="" SKIP_BUILD=0 OUT=""
CONFIG="Debug" INSTRUMENTS=0
DATASET_NAME="" DATASET_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --simulator) MODE="simulator"; shift ;;
    --device) MODE="device"; UDID="$2"; shift 2 ;;
    --dataset) DATASET_NAME="${2:?--dataset needs value}"; shift 2 ;;
    --dataset-file) DATASET_FILE="${2:?--dataset-file needs value}"; shift 2 ;;
    --flips) FLIPS="$2"; shift 2 ;;
    --min-flips) MIN_FLIPS="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --release) CONFIG="Release"; shift ;;
    --instruments) INSTRUMENTS=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --out) OUT="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1（--help 看用法）" >&2; exit 64 ;;
  esac
done

# usage error 用 64（EX_USAGE），與 invalid run 的 2 嚴格分流。
[[ -n "$MODE" ]] || { echo "error: --simulator 或 --device <udid> 必選其一" >&2; exit 64; }
if [[ -n "$DATASET_NAME" && -n "$DATASET_FILE" ]]; then
  echo "error: choose either --dataset or --dataset-file" >&2
  exit 64
fi
if [[ -n "$DATASET_NAME" ]]; then
  DATASET_FILE="$ROOT/ops/fixtures/ui_worlds/$DATASET_NAME.json"
fi
[[ -n "$DATASET_FILE" ]] || { echo "error: --dataset <name> or --dataset-file <path> is required (UI World SoT)" >&2; exit 64; }
if [[ "$INSTRUMENTS" -eq 1 && "$MODE" != "device" ]]; then
  echo "error: --instruments 只支援 --device（render-server hitch 量測無 simulator 意義）" >&2
  exit 64
fi
MIN_FLIPS="${MIN_FLIPS:-$FLIPS}"
TIMEOUT="${TIMEOUT:-$((60 + FLIPS * 4))}"
OUT="${OUT:-$(mktemp -d "${TMPDIR:-/tmp}/kg_review_probe_run.XXXXXX")}"
mkdir -p "$OUT"
CONSOLE="$OUT/console.log"
JSONL="$OUT/$JSONL_NAME"
TMP_BASE="${TMPDIR:-/tmp}"
VERDICT_FILE="${TMP_BASE%/}/kg_review_probe_verdict"
# set -e 早退路徑（install 失敗等）寫不到 verdict — 先清 stale，
# 下游永遠不會讀到上一輪殘留。
rm -f "$VERDICT_FILE"
[[ -f "$DATASET_FILE" ]] || { echo "error: UI World dataset missing: $DATASET_FILE" >&2; exit 64; }
UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    UV_BIN="$HOME/.local/bin/uv"
  else
    UV_BIN="uv"
  fi
fi
DATASET_ID="$("$UV_BIN" run --python 3.13 python "$SCRIPT_DIR/ui_world_manifest.py" validate "$DATASET_FILE" --label "UI World dataset")" || exit 64
# deflate+base64：plaintext base64 的大 world 會撐爆 spawn env block（app 端
# 靜默看不到 dataset），見 ops/lib/fixture_dataset_env.sh。
FIXTURE_DATASET_DEFLATE_B64="$(kg_fixture_dataset_deflate_b64 "$DATASET_FILE")" || exit 64
[[ -n "$FIXTURE_DATASET_DEFLATE_B64" ]] || { echo "[probe] error: deflate compression produced empty payload for $DATASET_FILE" >&2; exit 64; }

LAUNCH_ARGS=(
  -ui-testing
  "-seedFixture:todayReview:deck"
  -reviewProbe "$FLIPS"
  -appLaunchProfile ui-smoke
  -skipWelcome
)

log() { echo "[review_flip_probe] $*"; }

write_verdict() {
  local result="$1" detail="$2"
  kg_probe_write_verdict "$VERDICT_FILE" "$result" \
    "$detail" "console=$CONSOLE" "jsonl=$JSONL" "out=$OUT"
}

# reason 必須無空白（verdict KEY=value 行經空白切分解析；路徑另以
# console=/jsonl= 欄位傳，人類訊息走 log）。
fail_invalid() {
  log "✗ $1"
  write_verdict invalid "reason=$1"
  exit 2
}

# ---------- build ----------

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  if [[ "$MODE" == "simulator" ]]; then
    log "building ($CONFIG, simulator)…"
    "$SCRIPT_DIR/ios_build.sh" --configuration "$CONFIG" >/dev/null
  else
    log "building ($CONFIG, generic iOS device)…"
    "$SCRIPT_DIR/ios_build.sh" --configuration "$CONFIG" --destination "generic/platform=iOS" >/dev/null
  fi
fi

# DerivedData 解析鏡像 ios_build.sh 的 git-common-dir 錨定政策。
if [[ -n "${KG_IOS_BUILD_DERIVED_DATA_ROOT:-}" ]]; then
  DD_ROOT="$KG_IOS_BUILD_DERIVED_DATA_ROOT"
else
  GIT_COMMON_DIR="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -n "$GIT_COMMON_DIR" && -d "$GIT_COMMON_DIR" ]]; then
    DD_ROOT="$(dirname "$GIT_COMMON_DIR")/.cache/ios-build-derived-data"
  else
    DD_ROOT="$ROOT/.cache/ios-build-derived-data"
  fi
fi
if [[ "$MODE" == "simulator" ]]; then
  APP="$DD_ROOT/Build/Products/$CONFIG-iphonesimulator/$APP_NAME"
else
  APP="$DD_ROOT/Build/Products/$CONFIG-iphoneos/$APP_NAME"
fi
[[ -d "$APP" ]] || { log "hint: 先跑 build 或檢查 --release/destination 組合：$APP"; fail_invalid "app_not_found"; }

# ---------- run ----------

# 等 console marker。kg_probe_wait_pid 統一原語：rc=0 marker 到、
# rc=2 launch process 早死、rc=3 逾時（pid 已被 kill）。收斂留在 caller
# （sim 失敗路徑還要 terminate app）。heartbeat 內建。
wait_for_marker() {
  # early_cmd 用單引號字面值：$CONSOLE 延後到 eval 時才展開（lib 內可見
  # 同名 global），路徑含引號/空白不會把 grep 弄啞或注入。
  KG_PROBE_POLL_SECS="${KG_PROBE_POLL_SECS:-2}" kg_probe_wait_pid \
    "$LAUNCH_PID" "$TIMEOUT" "review_flip_probe.marker" \
    'grep -q "KG_REVIEW_PROBE \(done\|abort\)" "$CONSOLE" 2>/dev/null'
}

# rc → 精準 reason（launch 早死 ≠ 逾時，除錯方向完全不同）。
fail_invalid_for_wait_rc() {
  local rc="$1"
  if [[ "$rc" -eq 2 ]]; then
    log "launch process 已退出（app crash / 啟動失敗？）— 看 $CONSOLE"
    fail_invalid "launch_process_died"
  fi
  log "hint: 翻卡是否真的在跑？裝置是否解鎖？console: $CONSOLE"
  fail_invalid "probe_timeout:${TIMEOUT}s"
}

LAUNCH_PID=""
XCTRACE_PID=""
cleanup() {
  [[ -n "$LAUNCH_PID" ]] && kill "$LAUNCH_PID" 2>/dev/null || true
  [[ -n "$XCTRACE_PID" ]] && kill "$XCTRACE_PID" 2>/dev/null || true
}
trap cleanup EXIT
# infra 失敗（install/cp 等 set -e 早退）不可帶原始 rc 退出 —— rc=1 會與
# 「fail=門檻未過、數據有效」撞號。一律收斂成 invalid + exit 2。
on_unexpected_error() {
  local rc=$?
  [[ -f "$VERDICT_FILE" ]] || write_verdict invalid "reason=unexpected_infra_error_rc=$rc"
  exit 2
}
trap on_unexpected_error ERR

if [[ "$MODE" == "simulator" ]]; then
  log "ensuring simulator booted…"
  # 用 ensure-booted 自己回報的 udid——lease pool 允許多台 sim 同時 Booted，
  # 從 simctl list 撈 booted[0] 會撞到別的 agent 租用中的 pool sim。
  UDID="$("$SCRIPT_DIR/ios_ops.sh" simulator ensure-booted --json | jq -r '.device.udid // empty')"
  [[ -n "$UDID" ]] || fail_invalid "ensure_booted_no_udid"
  log "installing on simulator ${UDID}…"
  "$SCRIPT_DIR/ios_install.sh" --simulator "$UDID" --app "$APP"
  log "launching probe (flips=$FLIPS world=$DATASET_ID reviewDeck=probe timeout=${TIMEOUT}s)…"
  # KG_UI_TEST_SERVER_URL=啞端點：第三層防線，fixture 世界永不打真後端。
  # 注意 override 是 #if DEBUG（Release 編譯掉）——Release run 的防線是
  # ephemeral 容器 + ReviewProbeScene 不掛 sync handler；此 env 蓋 Debug。
  SIMCTL_CHILD_KG_FIXTURE_DATASET_DEFLATE_B64="$FIXTURE_DATASET_DEFLATE_B64" \
    SIMCTL_CHILD_KG_UI_TEST_SERVER_URL="http://127.0.0.1:9" \
    xcrun simctl launch --console-pty --terminate-running-process \
    "$UDID" "$BUNDLE_ID" "${LAUNCH_ARGS[@]}" \
    >"$CONSOLE" 2>&1 &
  LAUNCH_PID=$!

  wait_rc=0
  wait_for_marker || wait_rc=$?
  xcrun simctl terminate "$UDID" "$BUNDLE_ID" 2>/dev/null || true
  if [[ "$wait_rc" -ne 0 ]]; then
    LAUNCH_PID=""
    fail_invalid_for_wait_rc "$wait_rc"
  fi

  CONTAINER="$(xcrun simctl get_app_container "$UDID" "$BUNDLE_ID" data)"
  [[ -f "$CONTAINER/Documents/$JSONL_NAME" ]] || fail_invalid "jsonl_missing_in_container"
  cp "$CONTAINER/Documents/$JSONL_NAME" "$JSONL"
else
  # 鎖屏 preflight：xctrace 對鎖機不報錯而是無限懸掛、devicectl 行為也不一。
  # 秒級先驗，鎖著直接精準拒絕；查詢失敗（unknown）不擋——靠 watchdog 兜底，
  # 不可因 preflight 自身故障誤殺好機。
  rm -f "$OUT/lock_state.json"
  xcrun devicectl device info lockState --device "$UDID" \
    --json-output "$OUT/lock_state.json" >/dev/null 2>&1 || true
  case "$(kg_probe_passcode_required "$OUT/lock_state.json")" in
    true)
      log "hint: 裝置鎖屏中 — 解鎖（建議暫設自動鎖定=永不）後重跑"
      fail_invalid "device_locked"
      ;;
    unknown) log "warn: lockState 查詢失敗（繼續跑，watchdog 兜底）" ;;
  esac
  log "installing on device ${UDID}…"
  "$SCRIPT_DIR/ios_install.sh" --device "$UDID" --app "$APP"
  if [[ "$INSTRUMENTS" -eq 1 ]]; then
    # xctrace 包住整個 run：render-server 側 hitch 真相。無 console 串流，
    # 完成判定 = time-limit 跑滿 + JSONL summary（verdict 一律以 JSONL 為準）。
    TRACE="$OUT/review_flip_probe.trace"
    # xctrace 對既存 trace bundle 直接 abort（要求 --append-run）；--out 重用
    # 或前輪中斷殘影都會觸發 → 錄前一律清（per-run scratch，無保留價值）。
    rm -rf "$TRACE"
    log "recording 'Animation Hitches'+'Time Profiler' trace（time-limit ${TIMEOUT}s，flips=$FLIPS world=$DATASET_ID reviewDeck=probe）…"
    # xctrace 只認硬體 UDID（00008120-…），不認 devicectl 的 CoreDevice UUID；
    # 兩者經 devicectl info 對映，解析不到一律 invalid（不可拿原值矇跑）。
    # 下行 rm 的對象是 device_info.json（非上方 trace）：防 --out 重用時
    # 讀到上一輪殘留（與 verdict 檔同款 stale 防護）。
    rm -f "$OUT/device_info.json"
    xcrun devicectl device info details --device "$UDID" \
      --json-output "$OUT/device_info.json" >/dev/null 2>&1 || true
    HW_UDID="$(jq -r '.result.hardwareProperties.udid // empty' "$OUT/device_info.json" 2>/dev/null || true)"
    [[ -n "$HW_UDID" ]] || fail_invalid "hardware_udid_unresolved:$UDID"
    # xctrace 對鎖屏裝置不報錯而是無限懸掛（實測 13 分鐘無輸出），
    # --time-limit 只管「錄製開始後」——前置等待必須自己 watchdog。
    # 寬限 = time-limit + 600s：錄製結束後 xctrace 要把 raw .atrc 蒸餾成
    # trace DB，時長隨錄製長度放大（實測 180s 錄製 → raw 11G、蒸餾 >120s；
    # +120s 餘裕曾在此處砍掉收尾，產出無 template 的死 bundle，export 直接
    # Document Missing Template Error，整輪作廢）。heartbeat 內建。
    # 刻意不在錄製中輪詢 devicectl processes 提早偵測 launch 失敗：
    # 量測期間對裝置發查詢會污染被量測系統，preflight + watchdog 已足。
    # --env：xctrace 對 launched process 原生支援；UI World 與啞端點下發
    # 必須與 devicectl 路徑語意對齊。
    # --instrument 'Time Profiler' 疊在 Hitches template 上：同一 trace 內
    # hitch 區間 + 區間內主執行緒堆疊互相對時，一次 run 榨乾兩層證據。
    xcrun xctrace record --template 'Animation Hitches' --device "$HW_UDID" \
      --instrument 'Time Profiler' \
      --env KG_FIXTURE_DATASET_DEFLATE_B64="$FIXTURE_DATASET_DEFLATE_B64" \
      --env KG_UI_TEST_SERVER_URL="http://127.0.0.1:9" \
      --output "$TRACE" --time-limit "${TIMEOUT}s" \
      --launch -- "$BUNDLE_ID" "${LAUNCH_ARGS[@]}" >"$CONSOLE" 2>&1 &
    XCTRACE_PID=$!
    xctrace_rc=0
    # 餘裕涵蓋 time-limit 錄滿後的 distill（11G trace 曾蒸餾 >120s 被砍成
    # 無 template 死 bundle）。watchdog 與 verdict reason 共用同一常數，
    # 改值不會讓 reason 說謊。
    XCTRACE_GRACE=$((TIMEOUT + 600))
    kg_probe_wait_pid "$XCTRACE_PID" "$XCTRACE_GRACE" "review_flip_probe.xctrace" || xctrace_rc=$?
    XCTRACE_PID=""
    case "$xctrace_rc" in
      0) ;;
      3)
        log "hint: xctrace 逾時未結（裝置是否解鎖插線？）console: $CONSOLE"
        fail_invalid "xctrace_watchdog_timeout:${XCTRACE_GRACE}s"
        ;;
      *)
        log "hint: console: $CONSOLE"
        fail_invalid "xctrace_record_failed"
        ;;
    esac
    # TOC 先存檔：hitch 表的 export schema 待首個真機 trace 後固化解析。
    xcrun xctrace export --input "$TRACE" --toc >"$OUT/trace_toc.xml" 2>/dev/null || true
    log "trace saved: $TRACE"
  else
    log "launching probe (flips=$FLIPS world=$DATASET_ID reviewDeck=probe timeout=${TIMEOUT}s)…"
    # server URL 啞端點防線同 sim 路徑（#if DEBUG 語意見上）。
    DEVICECTL_CHILD_KG_FIXTURE_DATASET_DEFLATE_B64="$FIXTURE_DATASET_DEFLATE_B64" \
      DEVICECTL_CHILD_KG_UI_TEST_SERVER_URL="http://127.0.0.1:9" \
      xcrun devicectl device process launch --console --terminate-existing \
      --device "$UDID" -- "$BUNDLE_ID" "${LAUNCH_ARGS[@]}" >"$CONSOLE" 2>&1 &
    LAUNCH_PID=$!

    wait_rc=0
    wait_for_marker || wait_rc=$?
    if [[ "$wait_rc" -ne 0 ]]; then
      LAUNCH_PID=""
      fail_invalid_for_wait_rc "$wait_rc"
    fi
    kill "$LAUNCH_PID" 2>/dev/null || true
    LAUNCH_PID=""
  fi

  log "pulling JSONL from device container…"
  xcrun devicectl device copy from --device "$UDID" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "Documents/$JSONL_NAME" --destination "$JSONL" \
    || fail_invalid "jsonl_pull_failed"
fi

# ---------- verdict ----------

log "parsing → verdict…"
# ERR trap 在 set +e 下仍會對 pipeline 失敗觸發（bash 語意），parser 以
# rc=1 報 fail 會被搶答成 invalid+exit 2 —— 此後全是顯式 rc 處理，卸掉。
trap - ERR
set +e
"$SCRIPT_DIR/review_flip_probe_report.py" --jsonl "$JSONL" --min-flips "$MIN_FLIPS" \
  | tee "$OUT/verdict.json"
RC=${PIPESTATUS[0]}
set -e

# verdict.json 必須可解析；parser crash（stdout 非 JSON / exit 127 等）
# 一律 invalid —— 殘缺 run 絕不可流成 fail（假效能結論），也不殘留 stale verdict。
if ! jq -e . "$OUT/verdict.json" >/dev/null 2>&1; then
  fail_invalid "verdict_unparseable_rc=$RC"
fi
SUMMARY_DETAIL="$(jq -r '"result=\(.result) n=\(.summary.n // 0) p95=\(.summary.max_gap_p95_ms // 0) max=\(.summary.max_gap_max_ms // 0) stalls=\(.summary.stalls_total // 0) hitch_ms_per_s=\(.summary.hitch_ms_per_s // 0) build=\(.header.build_config // "?") thermal=\(.summary.thermal_end // "?")"' "$OUT/verdict.json")"
case "$RC" in
  0) write_verdict pass "$SUMMARY_DETAIL"; log "✓ PASS — $SUMMARY_DETAIL" ;;
  1) write_verdict fail "$SUMMARY_DETAIL"; log "✗ FAIL（門檻未過，數據有效）— $SUMMARY_DETAIL" ;;
  *) write_verdict invalid "$SUMMARY_DETAIL"; log "✗ INVALID（run 殘缺）— $SUMMARY_DETAIL" ;;
esac
exit "$RC"
