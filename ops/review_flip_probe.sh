#!/usr/bin/env bash
# review_flip_probe.sh — review-flip 自主量測 run（simulator / 真機）
#
# 一鍵跑完：build → install → launch（fixture 卡組 + autopilot 翻卡）→
# 收 console marker → 拉 JSONL → 預登門檻 verdict。人只需要保證裝置插著解鎖。
#
# Usage:
#   ./ops/review_flip_probe.sh --simulator [opts]
#   ./ops/review_flip_probe.sh --device <udid> [opts]
# Options:
#   --flips N       翻卡次數（預設 30）
#   --deck-size N   fixture 卡組大小（預設 40；sim 走 SIMCTL_CHILD_、device 走
#                   DEVICECTL_CHILD_ 下發；--instruments 模式無 env 通道，固定 40）
#   --min-flips N   verdict 有效性下限（預設 = --flips）
#   --timeout SECS  等 done/abort marker 的上限（預設 60 + 4×flips）
#   --release       Release configuration（Debug 量測有 observation/最佳化噪音；
#                   Release 才是使用者真相）
#   --instruments   （device only）xctrace 'Animation Hitches' 包住整個 run —
#                   render-server 側的 hitch 真相，trace 存 artifacts 目錄。
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
BUNDLE_ID="com.Max0228.BooksBrowser"
APP_NAME="BooksAndVocab.app"
JSONL_NAME="kg_review_probe.jsonl"

MODE="" UDID="" FLIPS=30 DECK=40 MIN_FLIPS="" TIMEOUT="" SKIP_BUILD=0 OUT=""
CONFIG="Debug" INSTRUMENTS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --simulator) MODE="simulator"; shift ;;
    --device) MODE="device"; UDID="$2"; shift 2 ;;
    --flips) FLIPS="$2"; shift 2 ;;
    --deck-size) DECK="$2"; shift 2 ;;
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
  printf 'RESULT=%s %s console=%s jsonl=%s out=%s\n' \
    "$result" "$detail" "$CONSOLE" "$JSONL" "$OUT" >"$VERDICT_FILE"
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

wait_for_marker() {
  local deadline=$((SECONDS + TIMEOUT))
  while ((SECONDS < deadline)); do
    if grep -q 'KG_REVIEW_PROBE \(done\|abort\)' "$CONSOLE" 2>/dev/null; then
      return 0
    fi
    # launch process 早死（app 秒 crash / 啟動失敗）→ 立刻報，
    # 不空轉滿 timeout 誤導操作者去查逾時。
    if [[ -n "$LAUNCH_PID" ]] && ! kill -0 "$LAUNCH_PID" 2>/dev/null; then
      log "launch process 已退出（app crash / 啟動失敗？）— 看 $CONSOLE"
      return 1
    fi
    sleep 2
  done
  return 1
}

LAUNCH_PID=""
cleanup() { [[ -n "$LAUNCH_PID" ]] && kill "$LAUNCH_PID" 2>/dev/null || true; }
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
  log "installing on simulator $UDID…"
  xcrun simctl install "$UDID" "$APP"
  log "launching probe (flips=$FLIPS deck=$DECK timeout=${TIMEOUT}s)…"
  SIMCTL_CHILD_KG_UI_TEST_REVIEW_DECK_SIZE="$DECK" \
    xcrun simctl launch --console-pty --terminate-running-process \
    "$UDID" "$BUNDLE_ID" "${LAUNCH_ARGS[@]}" \
    >"$CONSOLE" 2>&1 &
  LAUNCH_PID=$!

  if ! wait_for_marker; then
    xcrun simctl terminate "$UDID" "$BUNDLE_ID" 2>/dev/null || true
    log "hint: console: $CONSOLE"
    fail_invalid "timeout_or_launch_death:${TIMEOUT}s"
  fi
  xcrun simctl terminate "$UDID" "$BUNDLE_ID" 2>/dev/null || true

  CONTAINER="$(xcrun simctl get_app_container "$UDID" "$BUNDLE_ID" data)"
  [[ -f "$CONTAINER/Documents/$JSONL_NAME" ]] || fail_invalid "jsonl_missing_in_container"
  cp "$CONTAINER/Documents/$JSONL_NAME" "$JSONL"
else
  log "installing on device $UDID…"
  xcrun devicectl device install app --device "$UDID" "$APP"
  if [[ "$INSTRUMENTS" -eq 1 ]]; then
    # xctrace 包住整個 run：render-server 側 hitch 真相。無 console 串流，
    # 完成判定 = time-limit 跑滿 + JSONL summary（verdict 一律以 JSONL 為準）。
    TRACE="$OUT/review_flip_probe.trace"
    log "recording 'Animation Hitches' trace（time-limit ${TIMEOUT}s，flips=$FLIPS）…"
    if [[ "$DECK" != "40" ]]; then
      log "warn: --instruments 模式不支援 --deck-size 下發（xctrace 無 env 通道），deck 固定 40"
    fi
    xcrun xctrace record --template 'Animation Hitches' --device "$UDID" \
      --output "$TRACE" --time-limit "${TIMEOUT}s" \
      --launch -- "$BUNDLE_ID" "${LAUNCH_ARGS[@]}" >"$CONSOLE" 2>&1 \
      || { log "hint: console: $CONSOLE"; fail_invalid "xctrace_record_failed"; }
    # TOC 先存檔：hitch 表的 export schema 待首個真機 trace 後固化解析。
    xcrun xctrace export --input "$TRACE" --toc >"$OUT/trace_toc.xml" 2>/dev/null || true
    log "trace saved: $TRACE"
  else
    log "launching probe (flips=$FLIPS deck=$DECK timeout=${TIMEOUT}s)…"
    DEVICECTL_CHILD_KG_UI_TEST_REVIEW_DECK_SIZE="$DECK" \
      xcrun devicectl device process launch --console --terminate-existing \
      --device "$UDID" "$BUNDLE_ID" "${LAUNCH_ARGS[@]}" >"$CONSOLE" 2>&1 &
    LAUNCH_PID=$!

    if ! wait_for_marker; then
      log "hint: 裝置是否解鎖插線？console: $CONSOLE"
      fail_invalid "timeout_or_launch_death:${TIMEOUT}s"
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
