#!/usr/bin/env bash
# asc.sh — App Store Connect 查詢 / metadata 編輯
#
# codemagic CLI 包裝（uvx，免 fastlane/ruby，對齊 ios_release.sh 的 asc() 慣例）。
# 補 ios_release.sh 之外的「文案 / 版本狀態 / 審查狀態」讀寫缺口。
# 送審（submit-for-review）刻意不做：review-status 只唯讀。
#
# Usage:
#   ./ops/asc.sh versions                      # 列 App Store 版本 + 審查 state
#   ./ops/asc.sh builds                        # TestFlight 最新 build number
#   ./ops/asc.sh metadata [--locale zh-Hant]   # 讀某版本某語系的文案欄位
#   ./ops/asc.sh info                          # app 層級唯讀資訊（name/bundle/sku/語言）
#   ./ops/asc.sh review-status                 # 審查提交 state（被拒原因須 GUI 解決中心看）
#   ./ops/asc.sh set <field> <value> [--locale zh-Hant]   # 改文案（預設 dry-run，--yes 才真寫）
#
# set 可寫 field：description / keywords / whats-new / marketing-url / support-url / promotional-text
# 全域 flag：--key <KEY_ID>（預設 TCXVHFRXMS）  --locale <L>  --version-id <id>  --yes
# 前置：$ASC_KEY_DIR/AuthKey_<KEY_ID>.p8 存在（預設 ~/.secrets/apple，CI/部署機可覆寫 ASC_KEY_DIR）。

set -euo pipefail

# ---- config（對齊 ios_release.sh）----
ISSUER_ID="d7f86188-7c56-46f7-bc99-f889421025fa"
KEY_ID="TCXVHFRXMS"                 # App Manager（讀 + 寫 metadata）
APP_ID="6759816274"                 # com.Max0228.BooksBrowser
BUNDLE_ID="com.Max0228.BooksBrowser"
ASC_KEY_DIR="${ASC_KEY_DIR:-$HOME/.secrets/apple}"   # 部署機 / CI 可覆寫
LOCALE="zh-Hant"
VERSION_ID=""
YES=0

err() { echo "✗ $*" >&2; exit 1; }

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
}

# ---- 全域 flag 解析（subcommand 前後皆可）----
SUB=""; ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --key)        KEY_ID="$2"; shift 2 ;;
    --locale)     LOCALE="$2"; shift 2 ;;
    --version-id) VERSION_ID="$2"; shift 2 ;;
    --yes)        YES=1; shift ;;
    -h|--help)    usage; exit 0 ;;
    -*)           err "unknown option: $1" ;;
    *)            if [[ -z "$SUB" ]]; then SUB="$1"; else ARGS+=("$1"); fi; shift ;;
  esac
done

KEY_PATH="$ASC_KEY_DIR/AuthKey_${KEY_ID}.p8"

asc() {  # codemagic CLI wrapper（auth flag 放在 subcommand 之後）
  uvx --from codemagic-cli-tools app-store-connect "$@" \
    --issuer-id "$ISSUER_ID" --key-id "$KEY_ID" --private-key "@file:$KEY_PATH"
}

require_key() { [[ -f "$KEY_PATH" ]] || err "API key not found: $KEY_PATH（見 ~/.secrets/apple/README.md）"; }

# ---- ID 解析鏈（純 codemagic）----
resolve_version() {  # 印出 version id（--version-id 優先，否則取最新一筆）
  [[ -n "$VERSION_ID" ]] && { echo "$VERSION_ID"; return; }
  asc apps app-store-versions "$APP_ID" --json 2>/dev/null | jq -r '.[0].id // empty'
}
resolve_loc() {  # $1=version_id → 印出該 locale 的 localization id
  asc app-store-versions localizations "$1" --json 2>/dev/null \
    | jq -r --arg L "$LOCALE" '.[] | select(.attributes.locale==$L) | .id' | head -1
}

# ---- 讀指令 ----
cmd_versions() {
  require_key
  asc apps app-store-versions "$APP_ID" --json 2>/dev/null \
    | jq -r '.[] | "\(.attributes.versionString)\t\(.attributes.platform)\t\(.attributes.appStoreState)\t\(.id)"' \
    | column -t -s $'\t'
}

cmd_builds() {
  require_key
  local latest
  latest="$(asc get-latest-testflight-build-number "$APP_ID" --platform IOS 2>/dev/null | tail -1 | tr -d '[:space:]')"
  echo "TestFlight 最新 build number: ${latest:-（無）}"
}

cmd_metadata() {
  require_key
  local ver loc
  ver="$(resolve_version)"; [[ -n "$ver" ]] || err "找不到版本"
  loc="$(resolve_loc "$ver")"; [[ -n "$loc" ]] || err "版本 $ver 無 $LOCALE localization"
  echo "# version=$ver  locale=$LOCALE  loc=$loc"
  asc app-store-version-localizations get "$loc" --json 2>/dev/null \
    | jq -r '.attributes | to_entries[] | "\(.key): \(.value // "（空）")"'
}

cmd_info() {
  require_key
  asc apps get "$APP_ID" --json 2>/dev/null \
    | jq -r '.attributes | "name: \(.name)\nbundleId: \(.bundleId)\nsku: \(.sku)\nprimaryLocale: \(.primaryLocale)"'
  echo "註：category / 內容版權 / 年齡分級 codemagic 未暴露，須 GUI 或 raw API（本工具未實作）。"
}

cmd_review_status() {
  require_key
  echo "# 審查提交（新→舊）："
  asc apps list-review-submissions "$APP_ID" --json 2>/dev/null \
    | jq -r '.[] | "\(.attributes.state)\t\(.attributes.platform)\t\(.id)"' \
    | column -t -s $'\t'
  echo "註：被拒的 Resolution Center 文字 public API 不提供，須在 ASC GUI（解決中心）看。"
}

# ---- 寫指令（metadata，預設 dry-run；--yes 才真送 modify）----
cmd_set() {
  require_key
  local field="${1:-}" value="${2:-}"
  # value 必須非空：避免 `set <field> "" --yes` 把正式文案清空。
  [[ -n "$field" && -n "$value" ]] || err "用法：asc.sh set <field> <value> [--locale L] [--yes]（value 不可為空）"
  local flag jkey
  case "$field" in
    description)       flag="--description";       jkey="description" ;;
    keywords)          flag="--keywords";          jkey="keywords" ;;
    whats-new|whatsnew)flag="--whats-new";         jkey="whatsNew" ;;
    marketing-url)     flag="--marketing-url";     jkey="marketingUrl" ;;
    support-url)       flag="--support-url";       jkey="supportUrl" ;;
    promotional-text)  flag="--promotional-text";  jkey="promotionalText" ;;
    *) err "不支援的 field：$field（可用 description/keywords/whats-new/marketing-url/support-url/promotional-text）" ;;
  esac
  local ver loc old
  ver="$(resolve_version)"; [[ -n "$ver" ]] || err "找不到版本"
  loc="$(resolve_loc "$ver")"; [[ -n "$loc" ]] || err "版本 $ver 無 $LOCALE localization"
  old="$(asc app-store-version-localizations get "$loc" --json 2>/dev/null | jq -r --arg k "$jkey" '.attributes[$k] // "（空）"')" \
    || err "讀取現值失敗（檢查金鑰 / 網路）—— 不顯示誤導性『空』值"
  echo "version=$ver  locale=$LOCALE  loc=$loc  field=$field"
  echo "  舊值：$old"
  echo "  新值：$value"
  if [[ $YES -eq 1 ]]; then
    asc app-store-version-localizations modify "$loc" "$flag" "$value"
    echo "✓ 已寫入正式 App Store 版本（$LOCALE）。"
  else
    echo "[dry-run] 未送出。確認無誤後加 --yes 才會真寫："
    echo "  ./ops/asc.sh set $field <value> --locale $LOCALE --yes"
  fi
}

# ---- dispatch ----
case "${SUB:-}" in
  versions)      cmd_versions ;;
  builds)        cmd_builds ;;
  metadata)      cmd_metadata ;;
  info)          cmd_info ;;
  review-status) cmd_review_status ;;
  set)           cmd_set "${ARGS[@]:-}" ;;
  ""|help)       usage ;;
  *)             err "unknown subcommand: $SUB（asc.sh help 看用法）" ;;
esac
