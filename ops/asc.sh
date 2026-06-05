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
#   ./ops/asc.sh review-detail                 # 審查聯絡 / demo 帳號 / 送審備註（raw API；查備註是否過期）
#   ./ops/asc.sh screenshots [--locale zh-Hant]# 截圖集逐張 state（raw API；重送前查 Mochi 殘留 / 缺圖）
#   ./ops/asc.sh set <field> <value> [--locale zh-Hant]   # 改版本文案（預設 dry-run，--yes 才真寫）
#   ./ops/asc.sh set-review <field> <value>               # 改審查資訊：備註/demo帳號/聯絡人（dry-run，--yes 才寫）
#
# set 可寫 field（appStoreVersionLocalization，逐語系）：
#   description / keywords / whats-new / marketing-url / support-url / promotional-text
# set-review 可寫 field（appStoreReviewDetail，整個版本一份，codemagic 未暴露 → 走 raw PATCH）：
#   notes / demo-name / demo-password / demo-required(true|false) / contact-first / contact-last / contact-phone / contact-email
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
# 取值型選項的守衛：$2 缺失/為空/是另一個 flag 時，給友善訊息而非 set -u 的 unbound variable。
need_val() { [[ -n "${2:-}" && "${2:-}" != -* ]] || err "$1 需要一個值（不可為空或接另一個選項）"; }

usage() {
  # 只印開頭連續註解區（停在第一個非 # 行），避免把 set -euo pipefail 等程式碼洩進 help。
  awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "$0"
}

# ---- 全域 flag 解析（subcommand 前後皆可）----
SUB=""; ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --key)        need_val --key "${2:-}";        KEY_ID="$2"; shift 2 ;;
    --locale)     need_val --locale "${2:-}";     LOCALE="$2"; shift 2 ;;
    --version-id) need_val --version-id "${2:-}"; VERSION_ID="$2"; shift 2 ;;
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

raw() {  # codemagic 暴露不到的唯讀 raw GET；JWT + 依賴宣告都在 asc_get.py（uv shebang），不污染本檔
  ASC_KEY_ID="$KEY_ID" ASC_ISSUER_ID="$ISSUER_ID" ASC_KEY_DIR="$ASC_KEY_DIR" \
    "$(dirname "$0")/asc_get.py" "$1"
}

patch_raw() {  # codemagic 暴露不到的 raw PATCH 寫入；body 由 stdin。JWT 同樣只在 asc_patch.py（本檔仍零 JWT）
  ASC_KEY_ID="$KEY_ID" ASC_ISSUER_ID="$ISSUER_ID" ASC_KEY_DIR="$ASC_KEY_DIR" \
    "$(dirname "$0")/asc_patch.py" "$1"
}

# ---- ID 解析鏈（純 codemagic）----
resolve_version() {  # 印出 version id（--version-id 優先，否則取最新一筆）
  [[ -n "$VERSION_ID" ]] && { echo "$VERSION_ID"; return; }
  # 結尾 || true：codemagic 非零 exit（網路/權限）在 set -e+pipefail 下不得中止賦值，
  # 讓空輸出流到呼叫端的 `|| err "找不到版本"` 友善訊息，而非靜默 exit。
  asc apps app-store-versions "$APP_ID" --json 2>/dev/null | jq -r '.[0].id // empty' || true
}
resolve_loc() {  # $1=version_id → 印出該 locale 的 localization id
  # 結尾 || true：--version-id 給了無效值時 codemagic 會非零退出，這裡吞掉 → 空輸出 →
  # 呼叫端 `[[ -n "$loc" ]] || err "版本 X 無 localization"` 才有機會跑（否則靜默 exit 1）。
  asc app-store-versions localizations "$1" --json 2>/dev/null \
    | jq -r --arg L "$LOCALE" '.[] | select(.attributes.locale==$L) | .id' | head -1 || true
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

cmd_review_detail() {  # raw：審查聯絡 / demo 帳號 / 送審備註（codemagic 未暴露）
  require_key
  local ver; ver="$(resolve_version)"; [[ -n "$ver" ]] || err "找不到版本"
  raw "/v1/appStoreVersions/$ver/appStoreReviewDetail" \
    | jq -r 'if ._httpError then "（無 review detail：HTTP \(._httpError)）"
             else .data.attributes as $a
               | "contact:    \($a.contactFirstName) \($a.contactLastName) <\($a.contactEmail)> \($a.contactPhone)",
                 "demo:       \($a.demoAccountName // "（無）")  required=\($a.demoAccountRequired)",
                 "notes:",
                 ($a.notes // "（空）") end'
  echo "註：送審備註是 app 給審查員的脈絡。重送前確認它對應「本輪」被拒原因，別沿用上一輪的舊文。"
}

cmd_screenshots() {  # raw：截圖集逐張 state（重送前查 Mochi 殘留 / 缺圖）
  require_key
  local ver loc
  ver="$(resolve_version)"; [[ -n "$ver" ]] || err "找不到版本"
  loc="$(resolve_loc "$ver")"; [[ -n "$loc" ]] || err "版本 $ver 無 $LOCALE localization"
  echo "# version=$ver  locale=$LOCALE  loc=$loc"
  raw "/v1/appStoreVersionLocalizations/$loc/appScreenshotSets?include=appScreenshots" \
    | jq -r 'if ._httpError then "（讀取失敗：HTTP \(._httpError)）"
             else (.included // []) as $imgs
               | .data[] as $set
               | "[\($set.attributes.screenshotDisplayType)]",
                 ( $set.relationships.appScreenshots.data[]?
                   | .id as $id
                   | ($imgs[] | select(.id==$id) | .attributes) as $s
                   | "  - \($s.fileName // "?")  \($s.assetDeliveryState.state // "?")" ) end'
  echo "註：state=COMPLETE 才算上架可用；圖檔內容（是否含已移除功能）須 fetch 縮圖目視，API 不判讀。"
}

# ---- 寫指令（metadata，預設 dry-run；--yes 才真送 modify）----
cmd_set() {
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
    notes|demo-name|demo-password|demo-required|contact-first|contact-last|contact-phone|contact-email)
      err "「$field」屬審查資訊（appStoreReviewDetail），請用：asc.sh set-review $field <value>" ;;
    *) err "不支援的 field：$field（可用 description/keywords/whats-new/marketing-url/support-url/promotional-text）" ;;
  esac
  require_key   # 金鑰只在「確定要打 API」前才需要（用錯子命令/欄位先報，不必先要金鑰）
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
    echo "[dry-run] 未送出。確認無誤後加 --yes 才會真寫（下行可直接 copy-paste，含空白/換行已 shell-quote）："
    printf '  ./ops/asc.sh set %s %q --locale %s --yes\n' "$field" "$value" "$LOCALE"
  fi
}

# ---- 寫指令（審查資訊 appStoreReviewDetail，codemagic 未暴露 → raw PATCH；dry-run 預設，--yes 才送）----
cmd_set_review() {
  local field="${1:-}" value="${2:-}"
  # value 必須非空：避免把備註/聯絡人清空。demo-required 例外（true/false 都合法）下面另檢。
  [[ -n "$field" && -n "$value" ]] || err "用法：asc.sh set-review <field> <value> [--yes]（value 不可為空）"
  local jkey
  case "$field" in
    notes)          jkey="notes" ;;
    demo-name)      jkey="demoAccountName" ;;
    demo-password)  jkey="demoAccountPassword" ;;
    demo-required)  jkey="demoAccountRequired" ;;
    contact-first)  jkey="contactFirstName" ;;
    contact-last)   jkey="contactLastName" ;;
    contact-phone)  jkey="contactPhone" ;;
    contact-email)  jkey="contactEmail" ;;
    description|keywords|whats-new|whatsnew|marketing-url|support-url|promotional-text)
      err "「$field」屬版本文案（appStoreVersionLocalization），請用：asc.sh set $field <value>" ;;
    *) err "不支援的 review field：$field（notes/demo-name/demo-password/demo-required/contact-first/contact-last/contact-phone/contact-email）" ;;
  esac
  require_key   # 金鑰只在「確定要打 API」前才需要

  local ver vlabel rd rid old body resp
  ver="$(resolve_version)"; [[ -n "$ver" ]] || err "找不到版本"
  # 顯示目標版本字串+state，避免誤寫到非預期版本（如已上架 / 被拒版本）
  vlabel="$(raw "/v1/appStoreVersions/$ver" | jq -r '(.data.attributes.versionString // "?") + " (" + (.data.attributes.appStoreState // "?") + ")"')"
  # reviewDetail 是整個版本一份；解析其 id（PATCH 標的）
  rd="$(raw "/v1/appStoreVersions/$ver/appStoreReviewDetail")"
  rid="$(printf '%s' "$rd" | jq -r '.data.id // empty')"
  if [[ -z "$rid" ]]; then
    # 把 raw GET 的 _httpError 帶進訊息：401/權限 與「真的沒有 reviewDetail」才分得開（不再同訊息）
    local httperr; httperr="$(printf '%s' "$rd" | jq -r 'if has("_httpError") then "（API HTTP \(._httpError)：\(._detail.errors[0].detail // ._detail.reason // "?")）" else "" end')"
    err "版本 $vlabel 無 appStoreReviewDetail$httperr（版本狀態可能不可編輯，或尚未建立審查資訊）"
  fi
  old="$(printf '%s' "$rd" | jq -r --arg k "$jkey" '.data.attributes[$k] // "（空）"')"

  # 組 PATCH body（jq 負責跳脫；demo-required 走 boolean，其餘 string）
  if [[ "$jkey" == "demoAccountRequired" ]]; then
    [[ "$value" == "true" || "$value" == "false" ]] || err "demo-required 只能 true 或 false（給的是：$value）"
    body="$(jq -nc --arg id "$rid" --argjson v "$value" \
      '{data:{type:"appStoreReviewDetails",id:$id,attributes:{demoAccountRequired:$v}}}')"
  else
    body="$(jq -nc --arg id "$rid" --arg k "$jkey" --arg v "$value" \
      '{data:{type:"appStoreReviewDetails",id:$id,attributes:{($k):$v}}}')"
  fi

  echo "version=$vlabel  reviewDetail=$rid  field=$field"
  echo "  舊值：$old"
  echo "  新值：$value"
  if [[ $YES -eq 1 ]]; then
    resp="$(printf '%s' "$body" | patch_raw "/v1/appStoreReviewDetails/$rid")"
    printf '%s' "$resp" | jq -e 'has("_httpError")' >/dev/null 2>&1 \
      && err "寫入失敗：HTTP $(printf '%s' "$resp" | jq -c '._httpError')  $(printf '%s' "$resp" | jq -c '._detail.errors // ._detail')"
    echo "✓ 已寫入審查資訊（appStoreReviewDetail；版本 $vlabel）。"
  else
    echo "[dry-run] 未送出。確認無誤後加 --yes 才會真寫（下行可直接 copy-paste）："
    printf '  ./ops/asc.sh set-review %s %q --yes\n' "$field" "$value"
  fi
}

# ---- dispatch ----
case "${SUB:-}" in
  versions)      cmd_versions ;;
  builds)        cmd_builds ;;
  metadata)      cmd_metadata ;;
  info)          cmd_info ;;
  review-status) cmd_review_status ;;
  review-detail) cmd_review_detail ;;
  screenshots)   cmd_screenshots ;;
  set)           cmd_set "${ARGS[@]:-}" ;;
  set-review)    cmd_set_review "${ARGS[@]:-}" ;;
  ""|help)       usage ;;
  *)             err "unknown subcommand: $SUB（asc.sh help 看用法）" ;;
esac
