#!/usr/bin/env bash
# ios_release.sh — App Store / TestFlight 發版（archive → export → 選擇性上傳）
#
# 用 App Store Connect API key 自動管理 distribution 簽章（-allowProvisioningUpdates），
# 無需在本機 keychain 手動匯入 Apple Distribution 憑證。
# 與 ios_build.sh 共用同一把 build lock（多 worktree / 並行安全）。
#
# Usage:
#   ./ops/ios_release.sh                    # archive + export 出 .ipa（無對外副作用，預設）
#   ./ops/ios_release.sh --upload           # 額外上傳到 App Store Connect（→ TestFlight）
#   ./ops/ios_release.sh --key 6Y7DC88RUY   # 指定 API key（預設 TCXVHFRXMS / App Manager）
#   ./ops/ios_release.sh --timeout 900      # 自訂 lock 等待秒數（預設 600）
#
# 前置：~/.secrets/apple/AuthKey_<KEY_ID>.p8 存在（金鑰清單見該目錄 README.md）。
# 上傳前會擋「build number 已存在於 TestFlight」——需先 bump CURRENT_PROJECT_VERSION。

set -euo pipefail

# ---- config ----
SCHEME="BooksBrowser"
CONFIGURATION="Release"
TEAM_ID="XNSH5U9FNV"
ISSUER_ID="d7f86188-7c56-46f7-bc99-f889421025fa"
APP_ID="6759816274"                 # com.Max0228.BooksBrowser
KEY_ID="TCXVHFRXMS"                 # App Manager（可送審）；只上 TestFlight 可改 6Y7DC88RUY（Developer）
DO_UPLOAD=0
TIMEOUT=600
POLL_INTERVAL=3
LOCK_FILE="/tmp/kg-ios-build.lock"  # 與 ios_build.sh 共用
VERDICT_FILE="${TMPDIR:-/tmp}/kg_ios_archive_verdict"
VERDICT_JSON_FILE="$VERDICT_FILE.json"
LOCK_WAIT_MS=0
ARCHIVE_MS=0
EXPORT_MS=0
UPLOAD_MS=0
TOTAL_MS=0

# 只印開頭連續註解區（停在第一個非 # 行）作為 help。
usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "$0"; }
# 取值型選項守衛：$2 缺失/為空/是另一個 flag 時給友善訊息，而非 set -u 的 unbound variable。
need_val() { [[ -n "${2:-}" && "${2:-}" != -* ]] || { echo "✗ $1 需要一個值（不可為空或接另一個選項）" >&2; exit 1; }; }
now_ms() { perl -MTime::HiRes=time -e 'printf("%.0f\n", time()*1000)'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --upload)   DO_UPLOAD=1; shift ;;
    --key)      need_val --key "${2:-}";     KEY_ID="$2"; shift 2 ;;
    --timeout)  need_val --timeout "${2:-}"; TIMEOUT="$2"; shift 2 ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "✗ 未知選項: $1（-h 看用法）" >&2; exit 1 ;;
  esac
done

KEY_PATH="$HOME/.secrets/apple/AuthKey_${KEY_ID}.p8"
[[ -f "$KEY_PATH" ]] || { echo "✗ API key not found: $KEY_PATH（見 ~/.secrets/apple/README.md）" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XCODEPROJ="$ROOT/ios/BooksBrowser.xcodeproj"
EXPORT_OPTS="$ROOT/ios/ExportOptions.plist"
# Pin archive DerivedData to one shared cache anchored at the main repo (see
# docs/reference/ios_deriveddata_policy.md). Without -derivedDataPath, archive
# intermediates leak to ~/Library/.../DerivedData/BooksBrowser-<pathHash>, one
# orphan per worktree. Separate from the Debug build cache so Release and Debug
# configurations don't invalidate each other's incremental state.
if [[ -n "${KG_IOS_RELEASE_DERIVED_DATA_ROOT:-}" ]]; then
  DERIVED_DATA_ROOT="$KG_IOS_RELEASE_DERIVED_DATA_ROOT"
else
  GIT_COMMON_DIR="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -n "$GIT_COMMON_DIR" && -d "$GIT_COMMON_DIR" ]]; then
    DERIVED_DATA_ROOT="$(dirname "$GIT_COMMON_DIR")/.cache/ios-release-derived-data"
  else
    DERIVED_DATA_ROOT="$ROOT/.cache/ios-release-derived-data"
  fi
fi
BUILD_DIR="$ROOT/ios/build"
ARCHIVE="$BUILD_DIR/BooksBrowser.xcarchive"
EXPORT_DIR="$BUILD_DIR/export"

[[ -d "$XCODEPROJ" ]] || { echo "✗ not found: $XCODEPROJ" >&2; exit 1; }
[[ -f "$EXPORT_OPTS" ]] || { echo "✗ not found: $EXPORT_OPTS" >&2; exit 1; }

auth=(-allowProvisioningUpdates
      -authenticationKeyPath "$KEY_PATH"
      -authenticationKeyID "$KEY_ID"
      -authenticationKeyIssuerID "$ISSUER_ID")

asc() {  # codemagic CLI wrapper（uvx，免 fastlane/ruby）
  uvx --from codemagic-cli-tools app-store-connect "$@" \
    --issuer-id "$ISSUER_ID" --key-id "$KEY_ID"
}

write_json_verdict() {
  local status="$1" exit_code="$2" archive_status="$3" export_status="$4" upload_status="$5"
  jq -nc \
    --arg schema "kg.ios.archive.v1" \
    --arg status "$status" \
    --arg exit "$exit_code" \
    --arg caller "$CALLER" \
    --arg keyId "$KEY_ID" \
    --arg archivePath "$ARCHIVE" \
    --arg archiveLog "$ARCHIVE_LOG" \
    --arg archiveXcresult "$RESULT_BUNDLE" \
    --arg archiveStatus "$archive_status" \
    --arg archiveElapsed "${ARCHIVE_ELAPSED:-}" \
    --arg exportDir "$EXPORT_DIR" \
    --arg ipa "${IPA:-}" \
    --arg exportStatus "$export_status" \
    --arg uploadStatus "$upload_status" \
    --argjson uploadRequested "$DO_UPLOAD" \
    --argjson lockWaitMs "$LOCK_WAIT_MS" \
    --argjson archiveMs "$ARCHIVE_MS" \
    --argjson exportMs "$EXPORT_MS" \
    --argjson uploadMs "$UPLOAD_MS" \
    --argjson totalMs "$TOTAL_MS" \
    '{
      schema:$schema,
      status:$status,
      exit:$exit,
      caller:$caller,
      options:{
        keyId:$keyId,
        uploadRequested:($uploadRequested == 1)
      },
      archive:{
        status:$archiveStatus,
        elapsed:(if $archiveElapsed == "" then null else ($archiveElapsed + "s") end),
        path:(if $archivePath == "" then null else $archivePath end),
        log:(if $archiveLog == "" then null else $archiveLog end),
        xcresult:(if $archiveXcresult == "" then null else $archiveXcresult end)
      },
      export:{
        status:$exportStatus,
        directory:(if $exportDir == "" then null else $exportDir end),
        ipa:(if $ipa == "" then null else $ipa end)
      },
      upload:{
        status:$uploadStatus,
        requested:($uploadRequested == 1),
        completed:($uploadStatus == "ok")
      },
      timings:{
        lockWaitMs:$lockWaitMs,
        archiveMs:$archiveMs,
        exportMs:$exportMs,
        uploadMs:$uploadMs,
        totalMs:$totalMs
      },
      artifacts:{
        log:(if $archiveLog == "" then null else $archiveLog end),
        xcresult:(if $archiveXcresult == "" then null else $archiveXcresult end),
        archive:(if $archivePath == "" then null else $archivePath end),
        exportDirectory:(if $exportDir == "" then null else $exportDir end),
        ipa:(if $ipa == "" then null else $ipa end)
      }
    }' >"$VERDICT_JSON_FILE" || true
}

# ---- build number guard（僅上傳前；archive 不受限但傳會被 Apple 拒重）----
guard_build_number() {
  local local_build latest_tf
  # -target（非 -scheme）只回 app target 的 build settings；-scheme 會混入 Tests target 的 1
  local_build="$(xcodebuild -project "$XCODEPROJ" -target "$SCHEME" \
      -configuration "$CONFIGURATION" -showBuildSettings 2>/dev/null \
      | awk -F' = ' '/ CURRENT_PROJECT_VERSION /{print $2; exit}' | tr -d '[:space:]')"
  latest_tf="$(asc get-latest-testflight-build-number "$APP_ID" --platform IOS 2>/dev/null | tail -1 | tr -d '[:space:]')"
  echo "[release] local build=$local_build  TestFlight latest=$latest_tf"
  if [[ -n "$local_build" && -n "$latest_tf" && "$local_build" =~ ^[0-9]+$ && "$latest_tf" =~ ^[0-9]+$ ]]; then
    if (( local_build <= latest_tf )); then
      echo "✗ build $local_build 已存在於 TestFlight（latest=$latest_tf）。先 bump CURRENT_PROJECT_VERSION 再 --upload。" >&2
      exit 1
    fi
  fi
}

# ---- lock acquire（shlock spin-wait，對齊 ios_build.sh）----
CALLER="${WORKTREE_BRANCH:-$(git -C "$ROOT" branch --show-current 2>/dev/null || echo 'unknown')}"
cleanup() { rm -f "$LOCK_FILE"; }
START_TOTAL_MS="$(now_ms)"
echo "[release] caller=$CALLER waiting for lock..."
WAITED=0
while ! shlock -f "$LOCK_FILE" -p $$; do
  HOLDER_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
  if [[ -n "$HOLDER_PID" ]] && ! kill -0 "$HOLDER_PID" 2>/dev/null; then
    if [[ "$(cat "$LOCK_FILE" 2>/dev/null || echo "")" == "$HOLDER_PID" ]]; then
      echo "[release] stale lock (pid=$HOLDER_PID dead), stealing"
      rm -f "$LOCK_FILE"
    fi
    continue
  fi
  if (( WAITED >= TIMEOUT )); then
    echo "[release] error: timed out after ${TIMEOUT}s waiting for lock (holder=$HOLDER_PID)" >&2
    exit 1
  fi
  sleep "$POLL_INTERVAL"
  WAITED=$(( WAITED + POLL_INTERVAL ))
done
trap cleanup EXIT
LOCK_WAIT_MS="$(( $(now_ms) - START_TOTAL_MS ))"
echo "[release] lock acquired by $CALLER (pid=$$)"

[[ $DO_UPLOAD -eq 1 ]] && guard_build_number

# ---- archive ----
echo "[release] ▶ archive ($CONFIGURATION) — key=$KEY_ID …"
rm -rf "$ARCHIVE"
mkdir -p "$BUILD_DIR"
START_ARCHIVE=$(date +%s)
START_ARCHIVE_MS="$(now_ms)"
ARCHIVE_LOG="$(mktemp "${TMPDIR:-/tmp}/kg_ios_release_archive.XXXXXX").log"
RESULT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kg_ios_release_result.XXXXXX")"
RESULT_BUNDLE="$RESULT_DIR/Archive.xcresult"
set +e
xcodebuild archive \
  -project "$XCODEPROJ" -scheme "$SCHEME" -configuration "$CONFIGURATION" \
  -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE" \
  -derivedDataPath "$DERIVED_DATA_ROOT" \
  -resultBundlePath "$RESULT_BUNDLE" \
  "${auth[@]}" \
  >"$ARCHIVE_LOG" 2>&1
ARCHIVE_EXIT=$?
set -e
ARCHIVE_ELAPSED=$(( $(date +%s) - START_ARCHIVE ))
ARCHIVE_MS="$(( $(now_ms) - START_ARCHIVE_MS ))"
DIAGNOSTICS="$SCRIPT_DIR/ios_diagnostics.py"
if [[ -x "$DIAGNOSTICS" ]]; then
  diag_result="fail"; [[ $ARCHIVE_EXIT -eq 0 ]] && diag_result="pass"
  "$DIAGNOSTICS" --xcresult "$RESULT_BUNDLE" --log "$ARCHIVE_LOG" --result "$diag_result" --limit 40 || true
else
  echo "[release] diagnostics unavailable: $DIAGNOSTICS" >&2
fi
if [[ $ARCHIVE_EXIT -ne 0 ]]; then
  echo "RESULT=fail EXIT=$ARCHIVE_EXIT caller=$CALLER archive=$ARCHIVE log=$ARCHIVE_LOG xcresult=$RESULT_BUNDLE" > "$VERDICT_FILE"
  write_json_verdict "fail" "$ARCHIVE_EXIT" "fail" "skipped" "skipped"
  echo "[release] ✗ archive failed (exit $ARCHIVE_EXIT, ${ARCHIVE_ELAPSED}s) log=$ARCHIVE_LOG xcresult=$RESULT_BUNDLE" >&2
  exit "$ARCHIVE_EXIT"
fi
echo "RESULT=ok EXIT=0 caller=$CALLER archive=$ARCHIVE log=$ARCHIVE_LOG xcresult=$RESULT_BUNDLE" > "$VERDICT_FILE"
echo "[release] ✓ archive succeeded (${ARCHIVE_ELAPSED}s) log=$ARCHIVE_LOG xcresult=$RESULT_BUNDLE"

# ---- export ipa ----
# manual signing（ExportOptions 指定 Apple Distribution + "KG App Store" profile，均已本機就緒）。
# 不帶 -allowProvisioningUpdates／auth：避免觸發 cloud-signing（現用 App Manager key 權限不足）。
echo "[release] ▶ export ipa …"
START_EXPORT_MS="$(now_ms)"
rm -rf "$EXPORT_DIR"
xcodebuild -exportArchive \
  -archivePath "$ARCHIVE" -exportPath "$EXPORT_DIR" \
  -exportOptionsPlist "$EXPORT_OPTS"
shopt -s nullglob; ipas=("$EXPORT_DIR"/*.ipa); shopt -u nullglob
IPA="${ipas[0]:-}"
EXPORT_MS="$(( $(now_ms) - START_EXPORT_MS ))"
if [[ -z "$IPA" ]]; then
  TOTAL_MS="$(( $(now_ms) - START_TOTAL_MS ))"
  write_json_verdict "fail" "1" "ok" "fail" "skipped"
  echo "✗ export 未產出 .ipa" >&2
  exit 1
fi
echo "[release] ✓ ipa: $IPA"

# ---- upload（對外副作用，需 --upload 明示）----
if [[ $DO_UPLOAD -eq 1 ]]; then
  echo "[release] ▶ upload → App Store Connect (TestFlight) …"
  START_UPLOAD_MS="$(now_ms)"
  xcrun altool --upload-app -f "$IPA" --type ios \
    --apiKey "$KEY_ID" --apiIssuer "$ISSUER_ID"
  UPLOAD_MS="$(( $(now_ms) - START_UPLOAD_MS ))"
  TOTAL_MS="$(( $(now_ms) - START_TOTAL_MS ))"
  write_json_verdict "ok" "0" "ok" "ok" "ok"
  echo "[release] ✓ uploaded — 數分鐘後於 TestFlight 顯示，processing 完才可送審"
else
  TOTAL_MS="$(( $(now_ms) - START_TOTAL_MS ))"
  write_json_verdict "ok" "0" "ok" "ok" "skipped"
  echo "[release] 完成 archive+export（未上傳）。要上 TestFlight 加 --upload。"
fi
