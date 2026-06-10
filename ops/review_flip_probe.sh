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
#   --deck-size N   fixture 卡組大小（預設 40；device 模式僅支援預設，env 無法下發）
#   --min-flips N   verdict 有效性下限（預設 = --flips）
#   --timeout SECS  等 done/abort marker 的上限（預設 60 + 4×flips）
#   --skip-build    跳過 build，直接用上次產物
#   --out DIR       artifacts 目錄（預設 mktemp）
#
# Verdict：$TMPDIR/kg_review_probe_verdict（KEY=value 一行）+ stdout JSON。
# exit：0=pass 1=fail 2=invalid（run 殘缺，不可下效能結論）。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUNDLE_ID="com.Max0228.BooksBrowser"
APP_NAME="BooksAndVocab.app"
JSONL_NAME="kg_review_probe.jsonl"

MODE="" UDID="" FLIPS=30 DECK=40 MIN_FLIPS="" TIMEOUT="" SKIP_BUILD=0 OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --simulator) MODE="simulator"; shift ;;
    --device) MODE="device"; UDID="$2"; shift 2 ;;
    --flips) FLIPS="$2"; shift 2 ;;
    --deck-size) DECK="$2"; shift 2 ;;
    --min-flips) MIN_FLIPS="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --out) OUT="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$MODE" ]] || { echo "error: --simulator 或 --device <udid> 必選其一" >&2; exit 2; }
MIN_FLIPS="${MIN_FLIPS:-$FLIPS}"
TIMEOUT="${TIMEOUT:-$((60 + FLIPS * 4))}"
OUT="${OUT:-$(mktemp -d "${TMPDIR:-/tmp}/kg_review_probe_run.XXXXXX")}"
mkdir -p "$OUT"
CONSOLE="$OUT/console.log"
JSONL="$OUT/$JSONL_NAME"
VERDICT_FILE="${TMPDIR:-/tmp}/kg_review_probe_verdict"

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

fail_invalid() {
  log "✗ $1"
  write_verdict invalid "reason=$1"
  exit 2
}

# ---------- build ----------

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  if [[ "$MODE" == "simulator" ]]; then
    log "building (Debug, simulator)…"
    "$SCRIPT_DIR/ios_build.sh" >/dev/null
  else
    log "building (Debug, generic iOS device)…"
    "$SCRIPT_DIR/ios_build.sh" --destination "generic/platform=iOS" >/dev/null
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
  APP="$DD_ROOT/Build/Products/Debug-iphonesimulator/$APP_NAME"
else
  APP="$DD_ROOT/Build/Products/Debug-iphoneos/$APP_NAME"
fi
[[ -d "$APP" ]] || fail_invalid "app_not_found:$APP（先跑 build 或檢查 destination）"

# ---------- run ----------

wait_for_marker() {
  local deadline=$((SECONDS + TIMEOUT))
  while ((SECONDS < deadline)); do
    if grep -q 'KG_REVIEW_PROBE \(done\|abort\)' "$CONSOLE" 2>/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}

LAUNCH_PID=""
cleanup() { [[ -n "$LAUNCH_PID" ]] && kill "$LAUNCH_PID" 2>/dev/null || true; }
trap cleanup EXIT

if [[ "$MODE" == "simulator" ]]; then
  log "ensuring simulator booted…"
  "$SCRIPT_DIR/ios_ops.sh" simulator ensure-booted >/dev/null
  UDID="$(xcrun simctl list devices booted -j | python3 -c '
import json, sys
data = json.load(sys.stdin)
booted = [d["udid"] for devs in data["devices"].values() for d in devs if d["state"] == "Booted"]
print(booted[0])
')"
  log "installing on simulator $UDID…"
  xcrun simctl install "$UDID" "$APP"
  log "launching probe (flips=$FLIPS deck=$DECK timeout=${TIMEOUT}s)…"
  SIMCTL_CHILD_KG_UI_TEST_REVIEW_DECK_SIZE="$DECK" \
    xcrun simctl launch --console-pty "$UDID" "$BUNDLE_ID" "${LAUNCH_ARGS[@]}" \
    >"$CONSOLE" 2>&1 &
  LAUNCH_PID=$!

  if ! wait_for_marker; then
    xcrun simctl terminate "$UDID" "$BUNDLE_ID" 2>/dev/null || true
    fail_invalid "timeout:${TIMEOUT}s（console: $CONSOLE）"
  fi
  xcrun simctl terminate "$UDID" "$BUNDLE_ID" 2>/dev/null || true

  CONTAINER="$(xcrun simctl get_app_container "$UDID" "$BUNDLE_ID" data)"
  [[ -f "$CONTAINER/Documents/$JSONL_NAME" ]] || fail_invalid "jsonl_missing_in_container"
  cp "$CONTAINER/Documents/$JSONL_NAME" "$JSONL"
else
  if [[ "$DECK" != "40" ]]; then
    log "warn: device 模式無法下發 KG_UI_TEST_REVIEW_DECK_SIZE，deck 固定 40"
  fi
  log "installing on device $UDID…"
  xcrun devicectl device install app --device "$UDID" "$APP"
  log "launching probe (flips=$FLIPS timeout=${TIMEOUT}s)…"
  xcrun devicectl device process launch --console --device "$UDID" \
    "$BUNDLE_ID" "${LAUNCH_ARGS[@]}" >"$CONSOLE" 2>&1 &
  LAUNCH_PID=$!

  if ! wait_for_marker; then
    fail_invalid "timeout:${TIMEOUT}s（裝置是否解鎖插線？console: $CONSOLE）"
  fi
  kill "$LAUNCH_PID" 2>/dev/null || true
  LAUNCH_PID=""

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

SUMMARY_DETAIL="$(python3 - "$OUT/verdict.json" <<'PY'
import json, sys
v = json.load(open(sys.argv[1]))
s = v.get("summary", {})
print(
    f'result={v.get("result")} n={s.get("n", 0)} '
    f'p95={s.get("max_gap_p95_ms", 0)} max={s.get("max_gap_max_ms", 0)} '
    f'stalls={s.get("stalls_total", 0)} hitch_ms_per_s={s.get("hitch_ms_per_s", 0)} '
    f'build={v.get("header", {}).get("build_config", "?")} '
    f'thermal={s.get("thermal_end", "?")}'
)
PY
)"
case "$RC" in
  0) write_verdict pass "$SUMMARY_DETAIL"; log "✓ PASS — $SUMMARY_DETAIL" ;;
  1) write_verdict fail "$SUMMARY_DETAIL"; log "✗ FAIL（門檻未過，數據有效）— $SUMMARY_DETAIL" ;;
  *) write_verdict invalid "$SUMMARY_DETAIL"; log "✗ INVALID（run 殘缺）— $SUMMARY_DETAIL" ;;
esac
exit "$RC"
