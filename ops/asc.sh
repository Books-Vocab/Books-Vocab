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
#   ./ops/asc.sh categories                    # 列 iOS 可用主分類 ID（set-category 用）
#   ./ops/asc.sh set <field> <value> [--locale zh-Hant]   # 改版本文案（預設 dry-run，--yes 才真寫）
#   ./ops/asc.sh set-review <field> <value>               # 改審查資訊：備註/demo帳號/聯絡人（dry-run，--yes 才寫）
#   ./ops/asc.sh set-appinfo <field> <value> [--locale L] # 改 App 層本地化：名稱/副標/隱私URL（dry-run，--yes 才寫）
#   ./ops/asc.sh set-eula <text>                          # 改自訂 EULA 全文（dry-run，--yes 才寫）
#   ./ops/asc.sh set-content-rights <uses|none>           # 改第三方內容版權宣告（dry-run，--yes 才寫）
#   ./ops/asc.sh set-category <primary|secondary> <ID>    # 改分類（ID 見 categories；dry-run，--yes 才寫）
#   ./ops/asc.sh set-rating <attr> <value>                # 改年齡分級宣告屬性（dry-run，--yes 才寫）
#
# 三組「物件邊界」（用錯子命令會互相指路）：
#   set         → appStoreVersionLocalization（逐語系版本文案，codemagic modify）：
#                 description / keywords / whats-new / marketing-url / support-url / promotional-text
#   set-review  → appStoreReviewDetail（整版一份，codemagic 未暴露 → raw PATCH）：
#                 notes / demo-name / demo-password / demo-required(true|false) / contact-first / contact-last / contact-phone / contact-email
#   set-appinfo → appInfoLocalization（App 層逐語系，raw PATCH）：
#                 name / subtitle / privacy-url / privacy-choices-url / privacy-policy-text
# 另有 App 層結構寫入（raw PATCH）：set-eula(EULA 全文) / set-content-rights(內容版權) / set-category(分類) / set-rating(年齡分級)。
# 註：App 隱私權（nutrition labels）Apple 無公開 API，只能 GUI 編輯（本工具不涵蓋）。
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

# 共用 raw-PATCH 收尾：印 old/new → dry-run gate → --yes 才送 → 錯誤判讀。所有 raw 寫指令共用，
# 確保「dry-run 預設 + patch_raw 只活在 --yes 分支」這個不變量只實作一次（負控 test 鎖此函式）。
# $1 標頭  $2 舊值  $3 新值  $4 PATCH path  $5 body(JSON)  $6 dry-run 重現指令
emit_patch() {
  local header="$1" old="$2" new="$3" path="$4" body="$5" hint="$6" resp
  echo "$header"
  echo "  舊值：$old"
  echo "  新值：$new"
  if [[ $YES -eq 1 ]]; then
    resp="$(printf '%s' "$body" | patch_raw "$path")"
    printf '%s' "$resp" | jq -e 'has("_httpError")' >/dev/null 2>&1 \
      && err "寫入失敗：HTTP $(printf '%s' "$resp" | jq -c '._httpError')  $(printf '%s' "$resp" | jq -c '._detail.errors // ._detail')"
    echo "✓ 已寫入（$path）。"
  else
    echo "[dry-run] 未送出。確認無誤後加 --yes 才會真寫（下行可直接 copy-paste）："
    echo "  $hint"
  fi
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

# App 層解析鏈（raw API；App 資訊 / EULA / 分類 / 年齡分級 寫入用）。
# raw()=asc_get.py 恆 exit 0，但 HTTP 失敗時回 {_httpError,…}（無 .data 陣列）。
# jq 必須先 `if has("_httpError") then empty`，否則 `first(.data[]…)` 對 null 迭代會 exit 5，
# 在 set -euo pipefail 下讓 `id="$(...)"` 賦值中止整個 script，呼叫端 || err 永遠跑不到（P1 review block）。
resolve_appinfo() {  # 印可編輯的 appInfo id（非 READY_FOR_SALE 優先，否則第一筆）
  raw "/v1/apps/$APP_ID/appInfos" \
    | jq -r 'if has("_httpError") then empty else (first(.data[] | select(.attributes.state != "READY_FOR_SALE") | .id) // (.data[0].id // empty)) end'
}
resolve_appinfo_loc() {  # $1=appInfo id → 印該 locale 的 appInfoLocalization id
  raw "/v1/appInfos/$1/appInfoLocalizations" \
    | jq -r --arg L "$LOCALE" 'if has("_httpError") then empty else (first(.data[] | select(.attributes.locale==$L) | .id) // empty) end'
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

cmd_info() {  # App 層完整讀面（codemagic 基本欄位 + raw 補 App 資訊全貌）
  require_key
  asc apps get "$APP_ID" --json 2>/dev/null \
    | jq -r '.attributes | "name: \(.name)\nbundleId: \(.bundleId)\nsku: \(.sku)\nprimaryLocale: \(.primaryLocale)\ncontentRights: \(.contentRightsDeclaration // "（未設）")"'
  local aid loc aistate
  aid="$(resolve_appinfo)"
  if [[ -n "$aid" ]]; then
    # 顯示實際 state（非一律標「可編輯態」）：READY_FOR_SALE 表示無可編輯草稿，寫入會被 API 擋
    aistate="$(raw "/v1/appInfos/$aid" | jq -r '.data.attributes.state // "?"')"
    echo "# appInfo=$aid  state=$aistate$( [[ "$aistate" == "READY_FOR_SALE" ]] && echo "（無可編輯草稿，寫入須先在 GUI 建新版本）" )"
    loc="$(resolve_appinfo_loc "$aid")"
    if [[ -n "$loc" ]]; then
      echo "## App 層本地化（$LOCALE）："
      raw "/v1/appInfoLocalizations/$loc" \
        | jq -r '.data.attributes | "  name: \(.name // "（空）")\n  subtitle: \(.subtitle // "（空）")\n  privacyPolicyUrl: \(.privacyPolicyUrl // "（空）")\n  privacyChoicesUrl: \(.privacyChoicesUrl // "（空）")"'
    fi
    echo "## 分類："
    echo "  primary:   $(raw "/v1/appInfos/$aid/primaryCategory"   | jq -r '.data.id // "（未設）"')"
    echo "  secondary: $(raw "/v1/appInfos/$aid/secondaryCategory" | jq -r '.data.id // "（未設）"')"
    echo "## 年齡分級宣告 id：$(raw "/v1/appInfos/$aid/ageRatingDeclaration" | jq -r '.data.id // "（無）"')（屬性用 set-rating <attr> <value> 改）"
  fi
  echo "## EULA：$(raw "/v1/apps/$APP_ID/endUserLicenseAgreement" | jq -r 'if .data then "自訂（\(.data.attributes.agreementText | length) 字）" else "（無，套用 Apple 標準 EULA）" end' 2>/dev/null || echo "（讀取失敗）")"
  echo "註：App 隱私權（nutrition labels）Apple 無公開 API，只能 GUI 編輯（本工具不涵蓋）。"
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
    name|subtitle|privacy-url|privacy-choices-url|privacy-policy-text)
      err "「$field」屬 App 層本地化（appInfoLocalization），請用：asc.sh set-appinfo $field <value>" ;;
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

# ---- App 資訊讀：分類清單（set-category 用） ----
cmd_categories() {
  require_key
  echo "# iOS 主分類 ID（set-category <primary|secondary> <ID>）："
  raw "/v1/appCategories?filter%5Bplatforms%5D=IOS&exists%5Bparent%5D=false&limit=200" \
    | jq -r 'if ._httpError then "（讀取失敗：HTTP \(._httpError)）" else (.data[].id) end' | sort
}

# ---- App 資訊寫：App 層本地化（name/subtitle/privacy URL；appInfoLocalization，raw PATCH） ----
cmd_set_appinfo() {
  local field="${1:-}" value="${2:-}"
  [[ -n "$field" && -n "$value" ]] || err "用法：asc.sh set-appinfo <field> <value> [--locale L] [--yes]（value 不可為空）"
  local jkey
  case "$field" in
    name)                jkey="name" ;;
    subtitle)            jkey="subtitle" ;;
    privacy-url)         jkey="privacyPolicyUrl" ;;
    privacy-choices-url) jkey="privacyChoicesUrl" ;;
    privacy-policy-text) jkey="privacyPolicyText" ;;
    description|keywords|whats-new|whatsnew|marketing-url|support-url|promotional-text)
      err "「$field」屬版本文案（appStoreVersionLocalization），請用：asc.sh set $field <value>" ;;
    *) err "不支援的 app-info field：$field（name/subtitle/privacy-url/privacy-choices-url/privacy-policy-text）" ;;
  esac
  require_key
  local aid loc data old body
  aid="$(resolve_appinfo)"; [[ -n "$aid" ]] || err "找不到可編輯的 appInfo"
  loc="$(resolve_appinfo_loc "$aid")"; [[ -n "$loc" ]] || err "appInfo $aid 無 $LOCALE 本地化"
  data="$(raw "/v1/appInfoLocalizations/$loc")"
  old="$(printf '%s' "$data" | jq -r --arg k "$jkey" '.data.attributes[$k] // "（空）"')"
  body="$(jq -nc --arg id "$loc" --arg k "$jkey" --arg v "$value" \
    '{data:{type:"appInfoLocalizations",id:$id,attributes:{($k):$v}}}')"
  emit_patch "appInfoLocalization=$loc  locale=$LOCALE  field=$field" "$old" "$value" \
    "/v1/appInfoLocalizations/$loc" "$body" \
    "$(printf './ops/asc.sh set-appinfo %s %q --locale %s --yes' "$field" "$value" "$LOCALE")"
}

# ---- App 資訊寫：自訂 EULA 全文（endUserLicenseAgreement，raw PATCH） ----
cmd_set_eula() {
  local value="${1:-}"
  [[ -n "$value" ]] || err "用法：asc.sh set-eula <text> [--yes]（不可為空；長文用 \"\$(cat eula.txt)\"）"
  require_key
  local eu eid old body
  eu="$(raw "/v1/apps/$APP_ID/endUserLicenseAgreement")"
  eid="$(printf '%s' "$eu" | jq -r '.data.id // empty')"
  [[ -n "$eid" ]] || err "此 app 尚無自訂 EULA（須先在 GUI 建立一次，本工具只更新既有）"
  old="$(printf '%s' "$eu" | jq -r '(.data.attributes.agreementText // "") | "（\(length) 字）前 60：" + .[0:60]')"
  body="$(jq -nc --arg id "$eid" --arg v "$value" \
    '{data:{type:"endUserLicenseAgreements",id:$id,attributes:{agreementText:$v}}}')"
  emit_patch "EULA=$eid" "$old" "（新文字 ${#value} 字，前 60：${value:0:60}）" \
    "/v1/endUserLicenseAgreements/$eid" "$body" \
    "$(printf './ops/asc.sh set-eula %q --yes' "$value")"
}

# ---- App 資訊寫：第三方內容版權宣告（apps attribute，raw PATCH） ----
cmd_set_content_rights() {
  local value="${1:-}"
  case "$value" in
    uses|USES_THIRD_PARTY_CONTENT)         value="USES_THIRD_PARTY_CONTENT" ;;
    none|DOES_NOT_USE_THIRD_PARTY_CONTENT) value="DOES_NOT_USE_THIRD_PARTY_CONTENT" ;;
    *) err "用法：asc.sh set-content-rights <uses|none> [--yes]" ;;
  esac
  require_key
  local old body
  old="$(raw "/v1/apps/$APP_ID" | jq -r '.data.attributes.contentRightsDeclaration // "（未設）"')"
  body="$(jq -nc --arg id "$APP_ID" --arg v "$value" \
    '{data:{type:"apps",id:$id,attributes:{contentRightsDeclaration:$v}}}')"
  emit_patch "app=$APP_ID  contentRightsDeclaration" "$old" "$value" \
    "/v1/apps/$APP_ID" "$body" \
    "./ops/asc.sh set-content-rights $value --yes"
}

# ---- App 資訊寫：主/次分類（appInfo relationship，raw PATCH） ----
cmd_set_category() {
  local slot="${1:-}" cat="${2:-}"
  case "$slot" in primary|secondary) ;; *) err "用法：asc.sh set-category <primary|secondary> <CATEGORY_ID> [--yes]（ID 見 asc.sh categories）" ;; esac
  [[ -n "$cat" ]] || err "缺 CATEGORY_ID（見 asc.sh categories 列可用值）"
  require_key
  local aid rel old body
  aid="$(resolve_appinfo)"; [[ -n "$aid" ]] || err "找不到可編輯的 appInfo"
  rel="${slot}Category"   # primaryCategory / secondaryCategory
  old="$(raw "/v1/appInfos/$aid/$rel" | jq -r '.data.id // "（未設）"')"
  # 分類走 relationship（非 attributes）：body 形狀與其他寫指令不同
  body="$(jq -nc --arg id "$aid" --arg rel "$rel" --arg cat "$cat" \
    '{data:{type:"appInfos",id:$id,relationships:{($rel):{data:{type:"appCategories",id:$cat}}}}}')"
  emit_patch "appInfo=$aid  $rel" "$old" "$cat" \
    "/v1/appInfos/$aid" "$body" \
    "./ops/asc.sh set-category $slot $cat --yes"
}

# ---- App 資訊寫：年齡分級宣告屬性（ageRatingDeclaration，raw PATCH；generic passthrough） ----
cmd_set_rating() {
  local field="${1:-}" value="${2:-}"
  [[ -n "$field" && -n "$value" ]] || err "用法：asc.sh set-rating <attr> <value> [--yes]（attr 為 camelCase 屬性，如 gambling=false、violenceCartoonOrFantasy=NONE；現值見 asc.sh info / GUI 問卷較安全）"
  require_key
  local aid data rid old body
  aid="$(resolve_appinfo)"; [[ -n "$aid" ]] || err "找不到可編輯的 appInfo"
  data="$(raw "/v1/appInfos/$aid/ageRatingDeclaration")"
  rid="$(printf '%s' "$data" | jq -r '.data.id // empty')"
  [[ -n "$rid" ]] || err "找不到 ageRatingDeclaration"
  old="$(printf '%s' "$data" | jq -r --arg k "$field" 'if .data.attributes | has($k) then (.data.attributes[$k] | tostring) else "（無此屬性）" end')"
  # bool 字面走 boolean，其餘走 string（enum 如 NONE / INFREQUENT_OR_MILD）；非法值交給 API 退回（emit_patch 會報）
  if [[ "$value" == "true" || "$value" == "false" ]]; then
    body="$(jq -nc --arg id "$rid" --arg k "$field" --argjson v "$value" \
      '{data:{type:"ageRatingDeclarations",id:$id,attributes:{($k):$v}}}')"
  else
    body="$(jq -nc --arg id "$rid" --arg k "$field" --arg v "$value" \
      '{data:{type:"ageRatingDeclarations",id:$id,attributes:{($k):$v}}}')"
  fi
  emit_patch "ageRatingDeclaration=$rid  attr=$field" "$old" "$value" \
    "/v1/ageRatingDeclarations/$rid" "$body" \
    "$(printf './ops/asc.sh set-rating %s %q --yes' "$field" "$value")"
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
  categories)    cmd_categories ;;
  set)           cmd_set "${ARGS[@]:-}" ;;
  set-review)    cmd_set_review "${ARGS[@]:-}" ;;
  set-appinfo)   cmd_set_appinfo "${ARGS[@]:-}" ;;
  set-eula)      cmd_set_eula "${ARGS[@]:-}" ;;
  set-content-rights) cmd_set_content_rights "${ARGS[@]:-}" ;;
  set-category)  cmd_set_category "${ARGS[@]:-}" ;;
  set-rating)    cmd_set_rating "${ARGS[@]:-}" ;;
  ""|help)       usage ;;
  *)             err "unknown subcommand: $SUB（asc.sh help 看用法）" ;;
esac
