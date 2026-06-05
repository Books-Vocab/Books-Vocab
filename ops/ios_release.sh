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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --upload)  DO_UPLOAD=1; shift ;;
    --key)     KEY_ID="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

KEY_PATH="$HOME/.secrets/apple/AuthKey_${KEY_ID}.p8"
[[ -f "$KEY_PATH" ]] || { echo "✗ API key not found: $KEY_PATH（見 ~/.secrets/apple/README.md）" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XCODEPROJ="$ROOT/ios/BooksBrowser.xcodeproj"
EXPORT_OPTS="$ROOT/ios/ExportOptions.plist"
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
echo "[release] lock acquired by $CALLER (pid=$$)"

[[ $DO_UPLOAD -eq 1 ]] && guard_build_number

# ---- archive ----
echo "[release] ▶ archive ($CONFIGURATION) — key=$KEY_ID …"
rm -rf "$ARCHIVE"
mkdir -p "$BUILD_DIR"
xcodebuild archive \
  -project "$XCODEPROJ" -scheme "$SCHEME" -configuration "$CONFIGURATION" \
  -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE" \
  "${auth[@]}"

# ---- export ipa ----
# manual signing（ExportOptions 指定 Apple Distribution + "KG App Store" profile，均已本機就緒）。
# 不帶 -allowProvisioningUpdates／auth：避免觸發 cloud-signing（現用 App Manager key 權限不足）。
echo "[release] ▶ export ipa …"
rm -rf "$EXPORT_DIR"
xcodebuild -exportArchive \
  -archivePath "$ARCHIVE" -exportPath "$EXPORT_DIR" \
  -exportOptionsPlist "$EXPORT_OPTS"
shopt -s nullglob; ipas=("$EXPORT_DIR"/*.ipa); shopt -u nullglob
IPA="${ipas[0]:-}"
[[ -n "$IPA" ]] || { echo "✗ export 未產出 .ipa" >&2; exit 1; }
echo "[release] ✓ ipa: $IPA"

# ---- upload（對外副作用，需 --upload 明示）----
if [[ $DO_UPLOAD -eq 1 ]]; then
  echo "[release] ▶ upload → App Store Connect (TestFlight) …"
  xcrun altool --upload-app -f "$IPA" --type ios \
    --apiKey "$KEY_ID" --apiIssuer "$ISSUER_ID"
  echo "[release] ✓ uploaded — 數分鐘後於 TestFlight 顯示，processing 完才可送審"
else
  echo "[release] 完成 archive+export（未上傳）。要上 TestFlight 加 --upload。"
fi
