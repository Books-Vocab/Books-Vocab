#!/usr/bin/env bash
# asc.sh — App Store Connect 查詢 / metadata 編輯
#
# codemagic CLI 包裝（uvx，免 fastlane/ruby，對齊 ios_release.sh 的 asc() 慣例）。
# 補 ios_release.sh 之外的「文案 / 版本狀態 / 審查狀態」讀寫缺口。
# 送審（submit-for-review）刻意不做：review-status 只唯讀。
#
# Usage:
#   ./ops/asc.sh status                        # 綜合盤點：info + versions + review-status + subscriptions
#   ./ops/asc.sh versions                      # 列 App Store 版本 + 審查 state
#   ./ops/asc.sh builds                        # TestFlight 最新 build number
#   ./ops/asc.sh metadata [--locale zh-Hant]   # 讀某版本某語系的文案欄位
#   ./ops/asc.sh info                          # app 層級唯讀資訊（name/bundle/sku/語言）
#   ./ops/asc.sh review-status                 # 審查提交 state（被拒原因須 GUI 解決中心看）
#   ./ops/asc.sh review-detail                 # 審查聯絡 / demo 帳號 / 送審備註（raw API；查備註是否過期）
#   ./ops/asc.sh submissions [N]               # 送審佇列 reviewSubmissions + 每筆打包項目數/state（唯讀）
#   ./ops/asc.sh screenshots [--locale zh-Hant]# 截圖集逐張 state（raw API；重送前查 Mochi 殘留 / 缺圖）
#   ./ops/asc.sh categories                    # 列 iOS 可用主分類 ID（set-category 用）
#   ./ops/asc.sh reviews [N]                    # 列最新 N 則用戶評論 + 是否已回覆（預設 20）
#   ./ops/asc.sh accessibility                  # 列無障礙宣告（唯讀；建立/發布走 GUI）
#   ./ops/asc.sh reply-review <reviewId> <text> # 回覆/更新某則評論（dry-run，--yes 才送）
#   ./ops/asc.sh subscriptions                 # 列訂閱群組→方案（productId/state/週期/代表價/在地化）
#   ./ops/asc.sh iap                            # 列一次性 App 內購買（inAppPurchasesV2）
#   ./ops/asc.sh sub-offers <subId>             # 訂閱優惠：介紹性/促銷/兌換碼（唯讀；建立走 GUI）
#   ./ops/asc.sh pricing                        # App 基礎定價（各地區 customerPrice）+ 供應地區
#   ./ops/asc.sh release-plan                   # 發布方式（releaseType）+ 分階段發布狀態（唯讀）
#   ./ops/asc.sh set-sub-name <subId> <value>   # 改訂閱顯示名（subscriptionLocalization；dry-run）
#   ./ops/asc.sh set-sub-desc <subId> <value>   # 改訂閱描述（subscriptionLocalization；dry-run）
#   ./ops/asc.sh set-sub-review-note <subId> <text>     # 改訂閱送審備註（dry-run）
#   ./ops/asc.sh set-sub-price <subId> <territory> <customerPrice>  # ⚠ 改訂閱正式價（動計費；dry-run，--yes 才送）
#   ./ops/asc.sh set <field> <value> [--locale zh-Hant]   # 改版本文案（預設 dry-run，--yes 才真寫）
#   ./ops/asc.sh set-review <field> <value>               # 改審查資訊：備註/demo帳號/聯絡人（dry-run，--yes 才寫）
#   ./ops/asc.sh set-appinfo <field> <value> [--locale L] # 改 App 層本地化：名稱/副標/隱私URL（dry-run，--yes 才寫）
#   ./ops/asc.sh set-eula <text>                          # 改自訂 EULA 全文（dry-run，--yes 才寫）
#   ./ops/asc.sh set-content-rights <uses|none>           # 改第三方內容版權宣告（dry-run，--yes 才寫）
#   ./ops/asc.sh set-category <primary|secondary> <ID>    # 改分類（ID 見 categories；dry-run，--yes 才寫）
#   ./ops/asc.sh set-rating <attr> <value>                # 改年齡分級宣告屬性（dry-run，--yes 才寫）
#   ./ops/asc.sh set-release-type <manual|auto|scheduled> [ISO8601]  # 改發布方式（auto=審核過自動上架；dry-run）
#   ./ops/asc.sh phased <start|pause|resume|complete|cancel>  # 分階段發布7天ramp控制（dry-run，--yes 才送）
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

write_raw() {  # codemagic 暴露不到的 raw 寫入；$1=METHOD(PATCH/POST/DELETE) $2=path，body 由 stdin。
  ASC_KEY_ID="$KEY_ID" ASC_ISSUER_ID="$ISSUER_ID" ASC_KEY_DIR="$ASC_KEY_DIR" \
    "$(dirname "$0")/asc_write.py" "$2" "$1"  # JWT 只在 asc_write.py（本檔仍零 JWT）
}

# 共用 raw 寫入收尾：印 old/new → dry-run gate → --yes 才送 → 錯誤判讀。所有 raw 寫指令共用，
# 確保「dry-run 預設 + write_raw（真寫）只活在 --yes 分支」這個不變量只實作一次（負控 test 鎖此函式）。
# $1 method(PATCH/POST/DELETE)  $2 標頭  $3 舊值  $4 新值  $5 path  $6 body(JSON)  $7 dry-run 重現指令
emit_write() {
  local method="$1" header="$2" old="$3" new="$4" path="$5" body="$6" hint="$7" resp
  echo "$header"
  echo "  舊值：$old"
  echo "  新值：$new"
  if [[ $YES -eq 1 ]]; then
    resp="$(printf '%s' "$body" | write_raw "$method" "$path")"
    printf '%s' "$resp" | jq -e 'has("_httpError")' >/dev/null 2>&1 \
      && err "寫入失敗：HTTP $(printf '%s' "$resp" | jq -c '._httpError')  $(printf '%s' "$resp" | jq -c '._detail.errors // ._detail')"
    echo "✓ 已寫入（${method} ${path}）。"
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
      echo "## App 層本地化（${LOCALE}）："
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

cmd_status() {
  require_key
  echo "== ASC Info =="
  cmd_info
  echo
  echo "== Versions =="
  cmd_versions
  echo
  echo "== Review Status =="
  cmd_review_status
  echo
  echo "== Subscriptions =="
  cmd_subscriptions
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
      err "「${field}」屬審查資訊（appStoreReviewDetail），請用：asc.sh set-review ${field} <value>" ;;
    name|subtitle|privacy-url|privacy-choices-url|privacy-policy-text)
      err "「${field}」屬 App 層本地化（appInfoLocalization），請用：asc.sh set-appinfo ${field} <value>" ;;
    *) err "不支援的 field：${field}（可用 description/keywords/whats-new/marketing-url/support-url/promotional-text）" ;;
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
    echo "✓ 已寫入正式 App Store 版本（${LOCALE}）。"
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
      err "「${field}」屬版本文案（appStoreVersionLocalization），請用：asc.sh set ${field} <value>" ;;
    *) err "不支援的 review field：${field}（notes/demo-name/demo-password/demo-required/contact-first/contact-last/contact-phone/contact-email）" ;;
  esac
  require_key   # 金鑰只在「確定要打 API」前才需要

  local ver vlabel rd rid old body
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
    [[ "$value" == "true" || "$value" == "false" ]] || err "demo-required 只能 true 或 false（給的是：${value}）"
    body="$(jq -nc --arg id "$rid" --argjson v "$value" \
      '{data:{type:"appStoreReviewDetails",id:$id,attributes:{demoAccountRequired:$v}}}')"
  else
    body="$(jq -nc --arg id "$rid" --arg k "$jkey" --arg v "$value" \
      '{data:{type:"appStoreReviewDetails",id:$id,attributes:{($k):$v}}}')"
  fi

  emit_write PATCH "version=$vlabel  reviewDetail=$rid  field=$field" "$old" "$value" \
    "/v1/appStoreReviewDetails/$rid" "$body" \
    "$(printf './ops/asc.sh set-review %s %q --yes' "$field" "$value")"
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
      err "「${field}」屬版本文案（appStoreVersionLocalization），請用：asc.sh set ${field} <value>" ;;
    *) err "不支援的 app-info field：${field}（name/subtitle/privacy-url/privacy-choices-url/privacy-policy-text）" ;;
  esac
  require_key
  local aid loc data old body
  aid="$(resolve_appinfo)"; [[ -n "$aid" ]] || err "找不到可編輯的 appInfo"
  loc="$(resolve_appinfo_loc "$aid")"; [[ -n "$loc" ]] || err "appInfo $aid 無 $LOCALE 本地化"
  data="$(raw "/v1/appInfoLocalizations/$loc")"
  old="$(printf '%s' "$data" | jq -r --arg k "$jkey" '.data.attributes[$k] // "（空）"')"
  body="$(jq -nc --arg id "$loc" --arg k "$jkey" --arg v "$value" \
    '{data:{type:"appInfoLocalizations",id:$id,attributes:{($k):$v}}}')"
  emit_write PATCH "appInfoLocalization=$loc  locale=$LOCALE  field=$field" "$old" "$value" \
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
  emit_write PATCH "EULA=$eid" "$old" "（新文字 ${#value} 字，前 60：${value:0:60}）" \
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
  emit_write PATCH "app=$APP_ID  contentRightsDeclaration" "$old" "$value" \
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
  emit_write PATCH "appInfo=$aid  $rel" "$old" "$cat" \
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
  emit_write PATCH "ageRatingDeclaration=$rid  attr=$field" "$old" "$value" \
    "/v1/ageRatingDeclarations/$rid" "$body" \
    "$(printf './ops/asc.sh set-rating %s %q --yes' "$field" "$value")"
}

# ---- 評論讀：最新用戶評論 + 回覆狀態（customerReviews，raw API） ----
cmd_reviews() {
  require_key
  local lim="${1:-20}"
  [[ "$lim" =~ ^[0-9]+$ ]] || err "reviews 的 N 需為數字（給的是：${lim}）"
  echo "# 最新用戶評論（territory · rating · 暱稱 · 日期 · id）；app 未上架時通常為空："
  raw "/v1/apps/$APP_ID/customerReviews?sort=-createdDate&limit=$lim&include=response" \
    | jq -r 'if has("_httpError") then "（讀取失敗：HTTP \(._httpError)）"
             else (.included // []) as $resp
               | (.data // [])[]
               | . as $r
               # 用 first(...) // null：無回覆時 select 為空 stream，直接綁會讓整筆 review 產零輸出被吞掉
               | (first($resp[] | select(.id == ($r.relationships.response.data.id // "x")) | .attributes.responseBody) // null) as $reply
               # null 防護：rating-only 評論的 body/title/rating 可為 null，"★"*null / gsub(null) / null[0:10] 都會 jq exit 5 中止
               | "[\($r.attributes.territory // "?")] \("★" * ($r.attributes.rating // 0))  \($r.attributes.reviewerNickname // "?")  \(($r.attributes.createdDate // "")[0:10])  id=\($r.id)",
                 "  「\($r.attributes.title // "")」 \(($r.attributes.body // "") | gsub("[\\n\\r]";" ") | .[0:120])",
                 (if $reply then "  ↳ 已回覆：\($reply | .[0:80])" else "  ↳ （未回覆 → reply-review \($r.id) <text>）" end)
             end'
  echo "註：評論為消費者唯讀資料；回覆用 reply-review（每則評論只能有一則回覆，再送=更新）。"
}

# ---- 無障礙宣告讀（accessibilityDeclarations，raw API；建立/發布走 GUI 狀態機） ----
cmd_accessibility() {
  require_key
  echo "# 無障礙宣告（accessibilityDeclarations）："
  raw "/v1/apps/$APP_ID/accessibilityDeclarations" \
    | jq -r 'if has("_httpError") then "（讀取失敗：HTTP \(._httpError)）"
             elif ((.data // []) | length) == 0 then "  （尚未建立任何無障礙宣告）"
             else (.data // [])[] | "  deviceFamily=\(.attributes.deviceFamily // "?")  state=\(.attributes.state // "?")  id=\(.id)" end'
  echo "註：無障礙宣告建立/發布有狀態機（DRAFT→PUBLISHED）且綁裝置家族，建議走 GUI；本工具唯讀。"
}

# ---- 評論回覆寫（customerReviewResponses；無回覆→POST 建，有→PATCH 改；dry-run 預設） ----
cmd_reply_review() {
  local rid="${1:-}" text="${2:-}"
  [[ -n "$rid" && -n "$text" ]] || err "用法：asc.sh reply-review <reviewId> <text> [--yes]（reviewId 見 asc.sh reviews）"
  require_key
  local existing eid method path old body
  existing="$(raw "/v1/customerReviews/$rid/response")"
  eid="$(printf '%s' "$existing" | jq -r '.data.id // empty')"
  if [[ -n "$eid" ]]; then   # 已有回覆 → 更新
    method=PATCH; path="/v1/customerReviewResponses/$eid"
    old="$(printf '%s' "$existing" | jq -r '.data.attributes.responseBody // "（空）"')"
    body="$(jq -nc --arg id "$eid" --arg v "$text" \
      '{data:{type:"customerReviewResponses",id:$id,attributes:{responseBody:$v}}}')"
  else                       # 尚無回覆 → 新建（須帶 review 關係）
    method=POST; path="/v1/customerReviewResponses"; old="（尚無回覆）"
    body="$(jq -nc --arg rid "$rid" --arg v "$text" \
      '{data:{type:"customerReviewResponses",attributes:{responseBody:$v},relationships:{review:{data:{type:"customerReviews",id:$rid}}}}}')"
  fi
  emit_write "$method" "review=$rid  回覆（${method}）" "$old" "$text" "$path" "$body" \
    "$(printf './ops/asc.sh reply-review %s %q --yes' "$rid" "$text")"
}

# ---- 營利讀（P3，全唯讀；改價/方案走 P4 gated）----
cmd_subscriptions() {
  require_key
  local groups
  groups="$(raw "/v1/apps/$APP_ID/subscriptionGroups?limit=50")"
  printf '%s' "$groups" | jq -e 'has("_httpError")' >/dev/null 2>&1 \
    && err "讀取訂閱群組失敗：HTTP $(printf '%s' "$groups" | jq -r '._httpError')"
  echo "# 訂閱群組 $(printf '%s' "$groups" | jq -r '(.data // []) | length') 個（方案 · productId · state · 週期 · 代表價 · 在地化）："
  local gid gname
  while IFS=$'\t' read -r gid gname; do
    [[ -z "$gid" ]] && continue
    echo "▸ 群組「${gname}」（${gid}）"
    local subs sid pid sname sstate speriod prices price locs
    subs="$(raw "/v1/subscriptionGroups/$gid/subscriptions?limit=50")"
    while IFS=$'\t' read -r sid pid sname sstate speriod; do
      [[ -z "$sid" ]] && continue
      prices="$(raw "/v1/subscriptions/$sid/prices?include=subscriptionPricePoint,territory&limit=200")"
      # 代表價：取第一筆 price 的 territory + customerPrice（完整各地區見 GUI）
      price="$(printf '%s' "$prices" | jq -r '
        (.included // []) as $inc | (.data // [])[0]
        | (.relationships.subscriptionPricePoint.data.id) as $ppid
        | (.relationships.territory.data.id) as $terr
        | ($inc[] | select(.type=="subscriptionPricePoints" and .id==$ppid) | .attributes.customerPrice) as $cp
        | "\($terr) \($cp)"')"
      locs="$(raw "/v1/subscriptions/$sid/subscriptionLocalizations?limit=20" | jq -r '[(.data // [])[].attributes.locale] | join(",")')"
      echo "  • $sname  [$pid]  state=$sstate  $speriod  代表價=${price:-?}  在地化=${locs:-?}"
    done < <(printf '%s' "$subs" | jq -r '(.data // [])[] | "\(.id)\t\(.attributes.productId)\t\(.attributes.name)\t\(.attributes.state)\t\(.attributes.subscriptionPeriod)"')
  done < <(printf '%s' "$groups" | jq -r '(.data // [])[] | "\(.id)\t\(.attributes.referenceName)"')
  echo "註：訂閱唯讀（P3）；改價/方案/在地化見 P4（gated；動到計費，後端 IAP 驗簽相依）。"
}

cmd_iap() {
  require_key
  echo "# 一次性 App 內購買（inAppPurchasesV2）："
  raw "/v1/apps/$APP_ID/inAppPurchasesV2?limit=200" \
    | jq -r 'if has("_httpError") then "（讀取失敗：HTTP \(._httpError)）"
             elif ((.data // []) | length)==0 then "  （無一次性 IAP；KG 走訂閱，見 asc.sh subscriptions）"
             else (.data // [])[] | "  • \(.attributes.name)  [\(.attributes.productId)]  type=\(.attributes.inAppPurchaseType)  state=\(.attributes.state)" end'
}

cmd_pricing() {
  require_key
  echo "# App 基礎定價（appPriceSchedule · territory → customerPrice；0 = 免費）："
  raw "/v1/appPriceSchedules/$APP_ID/manualPrices?include=appPricePoint,territory&limit=200" \
    | jq -r 'if has("_httpError") then "  （讀取失敗：HTTP \(._httpError)）"
             else (.included // []) as $inc
               | (.data // [])[0:20][]
               | .relationships.appPricePoint.data.id as $ppid
               | .relationships.territory.data.id as $terr
               | ($inc[] | select(.type=="appPricePoints" and .id==$ppid) | .attributes.customerPrice) as $cp
               | "  \($terr): \($cp)" end'
  echo "# 供應地區："
  local av avid
  av="$(raw "/v1/apps/$APP_ID/appAvailabilityV2")"
  if printf '%s' "$av" | jq -e 'has("_httpError")' >/dev/null 2>&1; then
    echo "  （appAvailability v2 API 在本 app 狀態下不開放：HTTP $(printf '%s' "$av" | jq -r '._httpError')；供應地區請見 GUI）"
  else
    avid="$(printf '%s' "$av" | jq -r '.data.id // empty')"
    raw "/v1/appAvailabilities/$avid/territoryAvailabilities?filter%5Bavailable%5D=true&limit=200" \
      | jq -r 'if has("_httpError") then "  （供應地區讀取失敗：HTTP \(._httpError)）" else "  可購地區數：\((.data // []) | length)" end'
  fi
}

# ---- 營利寫（P4，高風險；全 dry-run 預設 + --yes gate）----
resolve_sub_loc() {  # $1=subscription id → 印該 locale 的 subscriptionLocalization id
  raw "/v1/subscriptions/$1/subscriptionLocalizations?limit=50" \
    | jq -r --arg L "$LOCALE" 'if has("_httpError") then empty else (first(.data[] | select(.attributes.locale==$L) | .id) // empty) end'
}

# 改訂閱在地化（name/description；subscriptionLocalization PATCH，逐語系）
_set_sub_loc() {  # $1=cmd 顯示名  $2=jkey(name/description)  $3=subId  $4=value
  local cmd="$1" jkey="$2" subid="${3:-}" value="${4:-}"
  [[ -n "$subid" && -n "$value" ]] || err "用法：asc.sh $cmd <subId> <value> [--locale L] [--yes]（subId 見 asc.sh subscriptions）"
  require_key
  local loc data old body
  loc="$(resolve_sub_loc "$subid")"; [[ -n "$loc" ]] || err "訂閱 $subid 無 $LOCALE 在地化"
  data="$(raw "/v1/subscriptionLocalizations/$loc")"
  old="$(printf '%s' "$data" | jq -r --arg k "$jkey" '.data.attributes[$k] // "（空）"')"
  body="$(jq -nc --arg id "$loc" --arg k "$jkey" --arg v "$value" \
    '{data:{type:"subscriptionLocalizations",id:$id,attributes:{($k):$v}}}')"
  emit_write PATCH "subscriptionLocalization=$loc  locale=$LOCALE  field=$jkey" "$old" "$value" \
    "/v1/subscriptionLocalizations/$loc" "$body" \
    "$(printf './ops/asc.sh %s %s %q --locale %s --yes' "$cmd" "$subid" "$value" "$LOCALE")"
}
cmd_set_sub_name() { _set_sub_loc set-sub-name name "$@"; }
cmd_set_sub_desc() { _set_sub_loc set-sub-desc description "$@"; }

# 改訂閱送審備註（subscription PATCH）
cmd_set_sub_review_note() {
  local subid="${1:-}" value="${2:-}"
  [[ -n "$subid" && -n "$value" ]] || err "用法：asc.sh set-sub-review-note <subId> <text> [--yes]"
  require_key
  local old body
  old="$(raw "/v1/subscriptions/$subid" | jq -r '.data.attributes.reviewNote // "（空）"')"
  body="$(jq -nc --arg id "$subid" --arg v "$value" \
    '{data:{type:"subscriptions",id:$id,attributes:{reviewNote:$v}}}')"
  emit_write PATCH "subscription=$subid  reviewNote" "$old" "$value" \
    "/v1/subscriptions/$subid" "$body" \
    "$(printf './ops/asc.sh set-sub-review-note %s %q --yes' "$subid" "$value")"
}

# ⚠ 改訂閱正式價格（subscriptionPrices POST；動真實計費，最硬警告）
cmd_set_sub_price() {
  local subid="${1:-}" terr="${2:-}" price="${3:-}"
  [[ -n "$subid" && -n "$terr" && -n "$price" ]] \
    || err "用法：asc.sh set-sub-price <subId> <territory> <customerPrice> [--yes]（territory 如 USA/TWN；customerPrice 須對應可選價位）"
  require_key
  local pts ppid old body
  pts="$(raw "/v1/subscriptions/$subid/pricePoints?filter%5Bterritory%5D=$terr&limit=200")"
  printf '%s' "$pts" | jq -e 'has("_httpError")' >/dev/null 2>&1 \
    && err "讀取 $terr 價位失敗：HTTP $(printf '%s' "$pts" | jq -r '._httpError')（territory 代碼錯誤？）"
  ppid="$(printf '%s' "$pts" | jq -r --arg p "$price" 'first(.data[] | select(.attributes.customerPrice==$p) | .id) // empty')"
  if [[ -z "$ppid" ]]; then
    echo "✗ $terr 無 customerPrice=$price 的價位。可選值（須逐字相符）："
    # 顯示 raw customerPrice 字串（依數值排序但不改寫格式）——line 602 是 raw 字串 == 比對，
    # 若這裡 tonumber|tostring 正規化（"2.00"→"2"）會顯示出比對不到的值，誤導使用者
    printf '%s' "$pts" | jq -r '[(.data // [])[].attributes.customerPrice] | sort_by(tonumber? // 0) | join(", ")'
    err "請從上列複製一個精確值"
  fi
  old="$(raw "/v1/subscriptions/$subid/prices?include=subscriptionPricePoint,territory&limit=200" \
    | jq -r --arg t "$terr" '(.included // []) as $inc
        | first((.data // [])[] | select(.relationships.territory.data.id==$t)
          | .relationships.subscriptionPricePoint.data.id as $pp
          | ($inc[] | select(.type=="subscriptionPricePoints" and .id==$pp) | .attributes.customerPrice)) // "（未知）"')"
  # preserveCurrentPrice=true：既有訂戶維持原價（較安全預設），僅新訂戶適用新價
  body="$(jq -nc --arg sub "$subid" --arg pp "$ppid" --arg t "$terr" \
    '{data:{type:"subscriptionPrices",attributes:{preserveCurrentPrice:true},relationships:{subscription:{data:{type:"subscriptions",id:$sub}},subscriptionPricePoint:{data:{type:"subscriptionPricePoints",id:$pp}},territory:{data:{type:"territories",id:$t}}}}}')"
  echo "⚠ 這會改變正式 App Store 訂閱價格（${terr}）—— 動到真實計費。"
  echo "⚠ preserveCurrentPrice=true：既有訂戶維持原價，僅新訂戶適用新價。"
  echo "⚠ KG 後端以 key 6Y7DC88RUY 驗訂閱權益；改價/方案前確認與後端邏輯一致。"
  emit_write POST "subscription=$subid  territory=$terr  pricePoint=$ppid" "$old" "$price" \
    "/v1/subscriptionPrices" "$body" \
    "$(printf './ops/asc.sh set-sub-price %s %s %s --yes' "$subid" "$terr" "$price")"
}

# ---- P5 版本發布控制（releaseType + 分階段發布）----
_resolve_phased() {  # $1=version_id → 印 phasedRelease id（無則空；_httpError 守衛防 set -e 中止）
  raw "/v1/appStoreVersions/$1/appStoreVersionPhasedRelease" \
    | jq -r 'if has("_httpError") then empty else (.data.id // empty) end'
}

cmd_release_plan() {  # 唯讀：發布方式 + 分階段發布狀態
  require_key
  local ver; ver="$(resolve_version)"; [[ -n "$ver" ]] || err "找不到版本"
  echo "# 發布方式（version=${ver}）："
  raw "/v1/appStoreVersions/$ver" \
    | jq -r 'if has("_httpError") then "  （讀取失敗：HTTP \(._httpError)）"
             else .data.attributes as $a
               | "  releaseType: \($a.releaseType // "?")"
                 + (if $a.earliestReleaseDate then "  排程: \($a.earliestReleaseDate)" else "" end)
                 + "  | appStoreState: \($a.appStoreState // "?")" end'
  echo "# 分階段發布（7 天 ramp）："
  raw "/v1/appStoreVersions/$ver/appStoreVersionPhasedRelease" \
    | jq -r 'if has("_httpError") then "  （讀取失敗：HTTP \(._httpError)）"
             elif (.data == null) then "  未啟用（未建立分階段發布）"
             else .data.attributes as $a
               | "  state: \($a.phasedReleaseState // "?")  天數: \($a.currentDayNumber // 0)/7  開始: \($a.startDate // "?")" end'
  echo "註：releaseType=審核通過後何時上架（MANUAL 手動 / AFTER_APPROVAL 自動 / SCHEDULED 排程）；"
  echo "    分階段發布讓「更新」逐日 ramp 給既有用戶（新安裝一律立即全量），可隨時 pause/complete/cancel。"
}

cmd_set_release_type() {  # PATCH appStoreVersions.releaseType（+ SCHEDULED 帶 earliestReleaseDate）
  local mode="${1:-}" date="${2:-}" rt
  case "$mode" in
    manual|MANUAL)        rt="MANUAL" ;;
    auto|AFTER_APPROVAL)  rt="AFTER_APPROVAL" ;;
    scheduled|SCHEDULED)  rt="SCHEDULED"
      [[ -n "$date" ]] || err "scheduled 需 ISO8601 日期：asc.sh set-release-type scheduled 2026-07-01T00:00:00-07:00" ;;
    *) err "用法：asc.sh set-release-type <manual|auto|scheduled> [ISO8601]（auto=AFTER_APPROVAL 審核過自動上架）" ;;
  esac
  require_key
  local ver old body
  ver="$(resolve_version)"; [[ -n "$ver" ]] || err "找不到版本"
  old="$(raw "/v1/appStoreVersions/$ver" | jq -r 'if has("_httpError") then "?" else .data.attributes | "\(.releaseType // "?")\(if .earliestReleaseDate then " @"+.earliestReleaseDate else "" end)" end')"
  if [[ "$rt" == "SCHEDULED" ]]; then
    body="$(jq -nc --arg id "$ver" --arg d "$date" \
      '{data:{type:"appStoreVersions",id:$id,attributes:{releaseType:"SCHEDULED",earliestReleaseDate:$d}}}')"
  else
    # 切回 MANUAL/AFTER_APPROVAL 一併清掉 earliestReleaseDate，避免殘留排程
    body="$(jq -nc --arg id "$ver" --arg rt "$rt" \
      '{data:{type:"appStoreVersions",id:$id,attributes:{releaseType:$rt,earliestReleaseDate:null}}}')"
  fi
  emit_write PATCH "version=$ver  releaseType" "$old" "$rt${date:+ @$date}" \
    "/v1/appStoreVersions/$ver" "$body" \
    "$(printf './ops/asc.sh set-release-type %s%s --yes' "$mode" "${date:+ $date}")"
}

cmd_phased() {  # 分階段發布：start=POST / pause|resume|complete=PATCH state / cancel=DELETE
  local action="${1:-}"
  require_key
  local ver; ver="$(resolve_version)"; [[ -n "$ver" ]] || err "找不到版本"
  local pid state old body
  case "$action" in
    start)
      pid="$(_resolve_phased "$ver")"
      [[ -z "$pid" ]] || err "分階段發布已存在（id=${pid}）；改用 pause/resume/complete/cancel"
      body="$(jq -nc --arg v "$ver" \
        '{data:{type:"appStoreVersionPhasedReleases",attributes:{phasedReleaseState:"ACTIVE"},relationships:{appStoreVersion:{data:{type:"appStoreVersions",id:$v}}}}}')"
      emit_write POST "version=$ver  啟動分階段發布" "（未啟用）" "ACTIVE" \
        "/v1/appStoreVersionPhasedReleases" "$body" \
        './ops/asc.sh phased start --yes'
      ;;
    pause|resume|complete)
      case "$action" in pause) state="PAUSED" ;; resume) state="ACTIVE" ;; complete) state="COMPLETE" ;; esac
      pid="$(_resolve_phased "$ver")"
      [[ -n "$pid" ]] || err "尚未啟用分階段發布（先 asc.sh phased start）"
      old="$(raw "/v1/appStoreVersionPhasedReleases/$pid" | jq -r 'if has("_httpError") then "?" else .data.attributes.phasedReleaseState // "?" end')"
      [[ "$action" == complete ]] && echo "⚠ complete：立即對所有既有用戶全量釋出（跳過剩餘 ramp 天數），不可逆。"
      body="$(jq -nc --arg id "$pid" --arg s "$state" \
        '{data:{type:"appStoreVersionPhasedReleases",id:$id,attributes:{phasedReleaseState:$s}}}')"
      emit_write PATCH "phasedRelease=$pid  state" "$old" "$state" \
        "/v1/appStoreVersionPhasedReleases/$pid" "$body" \
        "$(printf './ops/asc.sh phased %s --yes' "$action")"
      ;;
    cancel)
      pid="$(_resolve_phased "$ver")"
      [[ -n "$pid" ]] || err "尚未啟用分階段發布，無可取消"
      echo "⚠ cancel：刪除分階段發布計畫（回到一般全量發布），不可逆。"
      emit_write DELETE "phasedRelease=$pid  取消分階段發布" "（現有計畫）" "（刪除）" \
        "/v1/appStoreVersionPhasedReleases/$pid" "" \
        './ops/asc.sh phased cancel --yes'
      ;;
    *) err "用法：asc.sh phased <start|pause|resume|complete|cancel>（start=啟動7天ramp；complete=立即全量；cancel=刪除計畫）" ;;
  esac
}

# ---- P6 送審佇列 + 訂閱優惠（讀面補完）----
cmd_submissions() {  # 唯讀：送審佇列 reviewSubmissions + 每筆打包項目數/state
  require_key
  local n="${1:-5}" subs
  echo "# 送審佇列（新→舊，最多 $n 筆）："
  subs="$(raw "/v1/apps/$APP_ID/reviewSubmissions?limit=$n")"
  printf '%s' "$subs" | jq -e 'has("_httpError")' >/dev/null 2>&1 \
    && err "讀取送審佇列失敗：HTTP $(printf '%s' "$subs" | jq -r '._httpError')"
  local sid sstate splat sdate items icount
  while IFS=$'\t' read -r sid sstate splat sdate; do
    [[ -n "$sid" ]] || continue
    items="$(raw "/v1/reviewSubmissions/$sid/items")"
    icount="$(printf '%s' "$items" | jq -r 'if has("_httpError") then "?" else ((.data // []) | length) end')"
    echo "  • $sstate  $splat  送出=$sdate  打包項目=$icount  [$sid]"
  done < <(printf '%s' "$subs" | jq -r '(.data // [])[] | "\(.id)\t\(.attributes.state)\t\(.attributes.platform)\t\(.attributes.submittedDate // "（未送出）")"')
  echo "註：送審（submit）/ 撤回刻意不做（避免誤送 / 誤撤）——走 ASC GUI；被拒原因見解決中心。"
}

cmd_sub_offers() {  # 唯讀：訂閱優惠（介紹性 / 促銷 / 兌換碼）
  local subId="${1:-}"
  [[ -n "$subId" ]] || err "用法：asc.sh sub-offers <subId>（subId 見 asc.sh subscriptions）"
  require_key
  echo "# 介紹性優惠 introductoryOffers（首購試用 / 折扣，逐地區）："
  raw "/v1/subscriptions/$subId/introductoryOffers?limit=200" \
    | jq -r 'if has("_httpError") then "  （讀取失敗：HTTP \(._httpError)）"
             else (.data // []) as $d
               | if ($d | length) == 0 then "  （無）"
                 else ($d | group_by("\(.attributes.offerMode)|\(.attributes.duration // "")|\(.attributes.numberOfPeriods // 1)"))
                   | map("  \(.[0].attributes.offerMode // "?")  \(.[0].attributes.duration // "?") ×\(.[0].attributes.numberOfPeriods // 1)  —— \(length) 個地區")[]
               end end'
  echo "# 促銷優惠 promotionalOffers（給既有 / 流失用戶的回饋價）："
  raw "/v1/subscriptions/$subId/promotionalOffers?limit=200" \
    | jq -r 'if has("_httpError") then "  （讀取失敗：HTTP \(._httpError)）"
             elif ((.data // []) | length) == 0 then "  （無）"
             else (.data // [])[] | "  \(.attributes.name // "?")  [\(.id)]" end'
  echo "# 兌換碼 offerCodes（行銷兌換）："
  raw "/v1/subscriptions/$subId/offerCodes?limit=200" \
    | jq -r 'if has("_httpError") then "  （讀取失敗：HTTP \(._httpError)）"
             elif ((.data // []) | length) == 0 then "  （無）"
             else (.data // [])[] | "  \(.attributes.name // "?")  active=\(.attributes.active // false)  [\(.id)]" end'
  echo "註：優惠的建立 / 刪除（逐地區 price point）罕見且高風險，走 ASC GUI 較安全；本工具只讀。"
}

# ---- dispatch ----
case "${SUB:-}" in
  status)        cmd_status ;;
  versions)      cmd_versions ;;
  builds)        cmd_builds ;;
  metadata)      cmd_metadata ;;
  info)          cmd_info ;;
  review-status) cmd_review_status ;;
  review-detail) cmd_review_detail ;;
  screenshots)   cmd_screenshots ;;
  categories)    cmd_categories ;;
  reviews)       cmd_reviews "${ARGS[@]}" ;;
  accessibility) cmd_accessibility ;;
  reply-review)  cmd_reply_review "${ARGS[@]}" ;;
  subscriptions) cmd_subscriptions ;;
  iap)           cmd_iap ;;
  pricing)       cmd_pricing ;;
  set-sub-name)        cmd_set_sub_name "${ARGS[@]}" ;;
  set-sub-desc)        cmd_set_sub_desc "${ARGS[@]}" ;;
  set-sub-review-note) cmd_set_sub_review_note "${ARGS[@]}" ;;
  set-sub-price)       cmd_set_sub_price "${ARGS[@]}" ;;
  set)           cmd_set "${ARGS[@]}" ;;
  set-review)    cmd_set_review "${ARGS[@]}" ;;
  set-appinfo)   cmd_set_appinfo "${ARGS[@]}" ;;
  set-eula)      cmd_set_eula "${ARGS[@]}" ;;
  set-content-rights) cmd_set_content_rights "${ARGS[@]}" ;;
  set-category)  cmd_set_category "${ARGS[@]}" ;;
  set-rating)    cmd_set_rating "${ARGS[@]}" ;;
  submissions)   cmd_submissions "${ARGS[@]}" ;;
  sub-offers)    cmd_sub_offers "${ARGS[@]}" ;;
  release-plan)  cmd_release_plan ;;
  set-release-type) cmd_set_release_type "${ARGS[@]}" ;;
  phased)        cmd_phased "${ARGS[@]}" ;;
  ""|help)       usage ;;
  *)             err "unknown subcommand: ${SUB}（asc.sh help 看用法）" ;;
esac
