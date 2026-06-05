#!/usr/bin/env bash
# test_asc.sh — asc.sh 結構與行為驗證（不打 live API；對齊 test_devops.sh 慣例）
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
ASC="$WORKSPACE/ops/asc.sh"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }

# pipefail-safe 子字串檢查：用 here-string 餵入，杜絕 `echo "$x" | grep -q` 的早退 SIGPIPE 競態
# —— grep -q 命中即關 pipe，上游 echo 收 SIGPIPE，在 set -o pipefail 下整條 pipeline 回非零，
# 被誤判成「不匹配」（body 越大、命中越早越容易中，致 flaky）。here-string 無 pipe → 無此問題。
hasm()  { grep -q  -- "$2" <<<"$1"; }   # 固定 / BRE pattern
hasme() { grep -qE -- "$2" <<<"$1"; }   # ERE pattern
hasmi() { grep -qi -- "$2" <<<"$1"; }   # 大小寫不敏感

# ── 1. Syntax ───────────────────────────────────────────────────────────────
section "Syntax"
[[ -f "$ASC" ]]   && ok "asc.sh exists"   || fail_t "asc.sh missing"
bash -n "$ASC"    && ok "asc.sh syntax"   || fail_t "asc.sh syntax error"

# ── 2. 子命令 dispatch 分支齊全 ─────────────────────────────────────────────
section "Subcommand dispatch"
for sub in versions builds metadata info review-status set set-review; do
  grep -qE "^[[:space:]]*$sub\)" "$ASC" \
    && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
done

# ── 3. 複用 codemagic wrapper，不在主檔重造 JWT（review 核心） ───────────────
section "codemagic wrapper (no hand-rolled JWT)"
grep -q 'uvx --from codemagic-cli-tools app-store-connect' "$ASC" \
  && ok "uses codemagic CLI wrapper"     || fail_t "missing codemagic wrapper"
grep -q 'asc()' "$ASC" \
  && ok "has asc() wrapper fn"           || fail_t "missing asc() wrapper"
! grep -qiE 'jwt\.encode|import jwt|pyjwt|ES256' "$ASC" \
  && ok "no hand-rolled JWT in main"     || fail_t "hand-rolled JWT found (should reuse codemagic)"

# ── 4. .p8 路徑參數化（部署機 / CI 可覆寫） ─────────────────────────────────
section "Key dir parameterised"
grep -q 'ASC_KEY_DIR' "$ASC" \
  && ok "ASC_KEY_DIR overridable"        || fail_t "ASC_KEY_DIR not parameterised"

# ── 5. set 寫入 gate：預設 dry-run，--yes 才送 modify（對外副作用明示） ──────
section "Write gate (set defaults to dry-run)"
grep -q -- '--yes' "$ASC" \
  && ok "has --yes confirm flag"         || fail_t "missing --yes flag"
grep -q 'app-store-version-localizations modify' "$ASC" \
  && ok "set uses localizations modify"  || fail_t "set missing modify call"
# 真正的 modify 呼叫必須位於 YES gate 之內：擷取 cmd_set() body，
# 確認 modify 行只在 confirm 分支出現（dry-run 分支只印 payload，不呼叫）。
set_body="$(awk '/^cmd_set\(\)/,/^}/' "$ASC")"
hasm "$set_body" 'app-store-version-localizations modify' \
  && ok "modify lives inside cmd_set"    || fail_t "modify not in cmd_set"
# dry-run 預設：YES 變數預設為 0/空
grep -qE 'YES=(0|"")|YES=$' "$ASC" \
  && ok "YES defaults to off (dry-run)"  || fail_t "YES not defaulting to dry-run"
# 負控（鎖不變量）：modify 不可洩進 dry-run（else…fi）分支 —— 否則無 --yes 也會寫
hasm "$(awk '/else/,/fi/' <<<"$set_body")" 'localizations modify' \
  && fail_t "modify leaked into dry-run branch (would write without --yes)" \
  || ok "dry-run branch contains no modify call"
# value 空值守衛（C1 回歸）：cmd_set 必須同時檢 field 與 value 非空
hasme "$set_body" '\-n "\$field" && -n "\$value"' \
  && ok "set guards against empty value"  || fail_t "set missing empty-value guard (can wipe metadata)"

# ── 6. 不含 submit-for-review 寫入（scope：使用者明確排除） ──────────────────
section "No submit-for-review (read-only review-status)"
! grep -qE 'review-submissions[[:space:]]+(create|confirm|cancel)' "$ASC" \
  && ok "no review-submissions create/confirm/cancel" \
  || fail_t "found submit-for-review write path (out of scope)"
# review-status 只能唯讀
grep -qE 'list-review-submissions|review-submissions[[:space:]]+(get|items)' "$ASC" \
  && ok "review-status uses read-only endpoints" \
  || fail_t "review-status read endpoint missing"

# ── 7. config 常數對齊 ios_release.sh ───────────────────────────────────────
section "Config constants"
grep -q 'APP_ID="6759816274"' "$ASC" \
  && ok "APP_ID set"                     || fail_t "APP_ID missing/wrong"
grep -q 'ISSUER_ID="d7f86188' "$ASC" \
  && ok "ISSUER_ID set"                  || fail_t "ISSUER_ID missing"
grep -q 'KEY_ID="TCXVHFRXMS"' "$ASC" \
  && ok "KEY_ID default TCXVHFRXMS"      || fail_t "KEY_ID default wrong"

# ── 8. raw-API 讀指令（codemagic 未暴露的 review-detail / screenshots） ───────
section "Raw-API reads (codemagic gap fillers)"
GET="$WORKSPACE/ops/asc_get.py"
[[ -f "$GET" ]] && ok "asc_get.py companion exists" || fail_t "asc_get.py missing"
# 新增的兩個 raw-read 子命令必須在 dispatch
for sub in review-detail screenshots; do
  grep -qE "^[[:space:]]*$sub\)" "$ASC" \
    && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
done
# asc.sh 透過 helper 取 raw，而非在主檔鑄 JWT（維持 test 3 不變量）
grep -q 'asc_get.py' "$ASC" \
  && ok "raw reads shell out to asc_get.py" || fail_t "asc.sh not delegating raw reads"
# helper 仍不可出現在 asc.sh 主檔的 JWT（test 3 已守，這裡確認 helper 才是 JWT 所在）
grep -qiE 'jwt\.encode|ES256' "$GET" \
  && ok "asc_get.py is where JWT lives"   || fail_t "asc_get.py missing JWT mint"
# helper 唯讀：只能 GET（urlopen），不得有 POST/PATCH/DELETE/method=
! grep -qiE 'method[[:space:]]*=[[:space:]]*["'\'']?(POST|PATCH|DELETE|PUT)|data=' "$GET" \
  && ok "asc_get.py is GET-only (read-only)" || fail_t "asc_get.py has write method (must stay read-only)"
# helper HTTP 錯誤須優雅處理（不可裸 crash 隱藏 4xx/5xx）
grep -q 'HTTPError' "$GET" \
  && ok "asc_get.py handles HTTPError"    || fail_t "asc_get.py lacks graceful HTTP error handling"
# 非 HTTP 的 URLError（斷網/DNS/TLS）也須接住（review BLOCK 回歸）
grep -q 'URLError' "$GET" \
  && ok "asc_get.py handles URLError (offline)" || fail_t "asc_get.py crashes on network-down (URLError uncaught)"
# helper 由 env 參數化 key（與 asc.sh config 單一真相對齊，不雙寫死）
grep -qE 'environ|getenv' "$GET" \
  && ok "asc_get.py key params from env"  || fail_t "asc_get.py hardcodes key (should read env)"

# ── 7. 解析鏈不靜默失敗（dogfood B-F1：--version-id 無效時須走 || err，非 set -e 中止） ──
section "ID resolvers don't silently abort"
# resolve_version / resolve_loc 的 codemagic pipeline 必須以 `|| true` 收尾，
# 否則非零 exit 在 set -e+pipefail 下會讓賦值中止，呼叫端友善 err 永遠跑不到。
# grep 前先剔除註解行（grep -v '^[[:space:]]*#'），避免誤匹配解釋 || true 的中文註解（軟造假）。
rv_body="$(awk '/^resolve_version\(\)/,/^}/' "$ASC" | grep -v '^[[:space:]]*#')"
hasm "$rv_body" '|| true' \
  && ok "resolve_version pipeline guarded (|| true)" || fail_t "resolve_version may abort silently (no || true)"
rl_body="$(awk '/^resolve_loc\(\)/,/^}/' "$ASC" | grep -v '^[[:space:]]*#')"
hasm "$rl_body" '|| true' \
  && ok "resolve_loc pipeline guarded (|| true)"     || fail_t "resolve_loc may abort silently (no || true)"

# ── 8. 取值型選項守衛（dogfood C：--key/--version-id 後無值不該噴 unbound variable） ──
section "Value-taking options guarded"
grep -q 'need_val' "$ASC" \
  && ok "has need_val guard"               || fail_t "missing need_val guard for value options"
# 行為驗證：--key 後無值 → 友善訊息 + exit 1，而非 set -u 的 unbound variable
kv_out="$(bash "$ASC" --key 2>&1 || true)"
hasm "$kv_out" '需要一個值' \
  && ok "--key with no value → friendly error" || fail_t "--key no-value not friendly (got: $kv_out)"
hasmi "$kv_out" 'unbound variable' \
  && fail_t "--key no-value still hits set -u unbound variable" \
  || ok "no set -u unbound crash on missing value"

# ── 9. --help 不洩漏 shell 程式碼（與 release.sh 同步的 usage awk 修正） ──────
section "Help output stays comment-only"
help_out="$(bash "$ASC" --help 2>&1)"
hasme "$help_out" 'set -euo pipefail|^KEY_ID=|^ISSUER_ID=' \
  && fail_t "help leaks shell code" || ok "help is comment-only (no shell code leak)"

# ── 10. raw 寫入 helper（一般化 PATCH/POST/DELETE）+ set-review 經集中 gate ──
section "Raw write helper + set-review (gated)"
WRITE="$WORKSPACE/ops/asc_write.py"
[[ -f "$WRITE" ]] && ok "asc_write.py companion exists" || fail_t "asc_write.py missing"
# 一般化：支援 PATCH/POST/DELETE（method 由 argv 傳入並原樣帶進 request）
grep -q 'ALLOWED' "$WRITE" && grep -q '"PATCH"' "$WRITE" && grep -q '"POST"' "$WRITE" && grep -q '"DELETE"' "$WRITE" \
  && ok "asc_write.py supports PATCH/POST/DELETE" || fail_t "asc_write.py missing method support"
grep -qE 'method[[:space:]]*=[[:space:]]*method' "$WRITE" \
  && ok "asc_write.py honors method arg"   || fail_t "asc_write.py not passing method through"
grep -q 'jwt.encode' "$WRITE" \
  && ok "asc_write.py is where write-JWT lives" || fail_t "asc_write.py missing JWT mint"
grep -q 'HTTPError' "$WRITE" && grep -q 'URLError' "$WRITE" \
  && ok "asc_write.py handles HTTP+network errors" || fail_t "asc_write.py lacks graceful error handling"
grep -q 'asc_write.py' "$ASC" \
  && ok "asc.sh delegates writes to asc_write.py" || fail_t "asc.sh not delegating raw writes"
# asc.sh 主檔仍零 JWT（test 3 不變量延伸到寫入路徑）
! grep -qiE 'jwt\.encode|ES256' "$ASC" \
  && ok "asc.sh stays zero-JWT (writes via helper)" || fail_t "asc.sh hand-rolls JWT in write path"
# set-review 經 emit_write 收尾（不自行 write_raw 繞過集中 gate），並驗 demo-required boolean
sr_body="$(awk '/^cmd_set_review\(\)/,/^}/' "$ASC")"
hasm "$sr_body" 'emit_write' \
  && ok "set-review routes through emit_write" || fail_t "set-review not using emit_write"
hasm "$sr_body" 'write_raw' \
  && fail_t "set-review calls write_raw directly (bypasses central gate)" \
  || ok "set-review delegates write (no direct write_raw)"
hasm "$sr_body" 'true.*false\|false.*true' \
  && ok "demo-required validates true/false" || fail_t "demo-required boolean not validated"
# 行為：跨物件欄位互相指路（set notes → set-review；set-review description → set）
hasm "$(bash "$ASC" set notes x 2>&1)" 'set-review' \
  && ok "set <review-field> routes to set-review" || fail_t "set doesn't route review fields"
hasme "$(bash "$ASC" set-review description x 2>&1)" 'asc.sh set ' \
  && ok "set-review <text-field> routes to set" || fail_t "set-review doesn't route text fields"

# ── 11. App 資訊讀寫面（P1：appInfoLocalization / EULA / 分類 / 年齡分級 / 內容版權）──
section "App-info read/write surface (P1)"
# 11a. 新子命令全在 dispatch
for sub in categories set-appinfo set-eula set-content-rights set-category set-rating; do
  grep -qE "^[[:space:]]*$sub\)" "$ASC" \
    && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
done
# 11b. App 層 ID 解析鏈存在（raw API）
grep -q 'resolve_appinfo()' "$ASC"     && ok "resolve_appinfo present"     || fail_t "resolve_appinfo missing"
grep -q 'resolve_appinfo_loc()' "$ASC" && ok "resolve_appinfo_loc present" || fail_t "resolve_appinfo_loc missing"
# 11b'. 解析鏈對 _httpError 防護（P1 review block 回歸）：raw 失敗回 {_httpError} 時，
#       jq 必須先 `if has("_httpError") then empty`，否則 first(.data[]…) 迭代 null → exit 5 →
#       set -e+pipefail 下賦值中止整個 script，呼叫端 || err 跑不到。
for fn in resolve_appinfo resolve_appinfo_loc; do
  body="$(awk "/^$fn\\(\\)/,/^}/" "$ASC")"
  hasm "$body" 'has("_httpError")' \
    && ok "$fn guards _httpError before iterating .data" \
    || fail_t "$fn iterates .data without _httpError guard (aborts script on auth/network fail)"
done
# 11c. 共用 emit_write：gate 不變量集中一處 —— write_raw（真寫）只在 --yes 分支，dry-run(else) 分支零 write_raw
ep_body="$(awk '/^emit_write\(\)/,/^}/' "$ASC")"
hasm "$ep_body" 'write_raw' \
  && ok "emit_write performs real write_raw" || fail_t "emit_write missing write_raw"
hasme "$ep_body" 'if \[\[ \$YES -eq 1 \]\]' \
  && ok "emit_write guards write behind --yes"      || fail_t "emit_write missing --yes guard"
hasm "$(awk '/else/,/fi/' <<<"$ep_body")" 'write_raw' \
  && fail_t "write_raw leaked into emit_write dry-run branch (would write without --yes)" \
  || ok "emit_write dry-run branch contains no write_raw"
# 11d. 每個寫指令都「透過 emit_write」收尾，且不自行 write_raw（否則繞過集中 gate）
for fn in cmd_set_appinfo cmd_set_eula cmd_set_content_rights cmd_set_category cmd_set_rating; do
  body="$(awk "/^$fn\\(\\)/,/^}/" "$ASC")"
  hasm "$body" 'emit_write' \
    && ok "$fn routes through emit_write"        || fail_t "$fn doesn't use emit_write"
  hasm "$body" 'write_raw' \
    && fail_t "$fn calls write_raw directly (bypasses central gate)" \
    || ok "$fn delegates write (no direct write_raw)"
done
# 11e. body 形狀正確：set-appinfo 用 appInfoLocalizations attributes；set-category 用 relationships（非 attributes）
hasm "$(awk '/^cmd_set_appinfo\(\)/,/^}/' "$ASC")" 'type:"appInfoLocalizations"' \
  && ok "set-appinfo body targets appInfoLocalizations" || fail_t "set-appinfo body wrong type"
cat_body="$(awk '/^cmd_set_category\(\)/,/^}/' "$ASC")"
hasm "$cat_body" 'relationships' \
  && ok "set-category uses relationship body"   || fail_t "set-category not using relationships"
hasm "$cat_body" 'type:"appCategories"' \
  && ok "set-category references appCategories"  || fail_t "set-category missing appCategories ref"
# 11f. set-content-rights 只收 uses|none（防亂值）
cr_out="$(bash "$ASC" set-content-rights bogus 2>&1 || true)"
hasm "$cr_out" 'uses|none' \
  && ok "set-content-rights validates uses|none" || fail_t "set-content-rights accepts invalid value"
# 11g. 跨物件指路：set name → set-appinfo；set-appinfo description → set
hasm "$(bash "$ASC" set name x 2>&1)" 'set-appinfo' \
  && ok "set <appinfo-field> routes to set-appinfo" || fail_t "set doesn't route appinfo fields"
hasme "$(bash "$ASC" set-appinfo description x 2>&1)" 'asc.sh set ' \
  && ok "set-appinfo <version-field> routes to set" || fail_t "set-appinfo doesn't route version fields"
# 11h. EULA 寫入解析 endUserLicenseAgreement
hasm "$(awk '/^cmd_set_eula\(\)/,/^}/' "$ASC")" 'endUserLicenseAgreement' \
  && ok "set-eula resolves endUserLicenseAgreement" || fail_t "set-eula missing EULA resolution"

# ── 12. 評論讀/回覆 + 無障礙讀（P2：customerReviews / customerReviewResponses / accessibility）──
section "Reviews + accessibility surface (P2)"
# 12a. dispatch
for sub in reviews accessibility reply-review; do
  grep -qE "^[[:space:]]*$sub\)" "$ASC" \
    && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
done
# 12b. asc_write.py method 驗證：未知 method 即報（在讀 stdin / 鑄 JWT 前就退，不打 API）
bogus_out="$(printf '{}' | "$WRITE" /v1/x BOGUS 2>&1 || true)"
hasm "$bogus_out" '不支援的 method' \
  && ok "asc_write.py rejects unknown method" || fail_t "asc_write.py doesn't validate method (got: $(echo "$bogus_out" | head -1))"
# 12c. reply-review 經 emit_write（集中 gate），不自行 write_raw
rr_body="$(awk '/^cmd_reply_review\(\)/,/^}/' "$ASC")"
hasm "$rr_body" 'emit_write' \
  && ok "reply-review routes through emit_write" || fail_t "reply-review not using emit_write"
hasm "$rr_body" 'write_raw' \
  && fail_t "reply-review calls write_raw directly (bypasses gate)" \
  || ok "reply-review delegates write (no direct write_raw)"
# 12d. reply-review upsert：無回覆→POST 建（帶 review 關係）、有→PATCH 改
hasm "$rr_body" 'method=POST' && hasm "$rr_body" 'method=PATCH' \
  && ok "reply-review upserts (POST new / PATCH existing)" || fail_t "reply-review missing POST/PATCH upsert"
hasm "$rr_body" 'customerReviewResponses' \
  && ok "reply-review targets customerReviewResponses" || fail_t "reply-review wrong target type"
hasm "$rr_body" 'relationships:{review' \
  && ok "reply-review POST carries review relationship" || fail_t "reply-review POST missing review relationship"
# 12e. reviews：N 須數字（防注入）
rev_out="$(bash "$ASC" reviews abc 2>&1 || true)"
hasm "$rev_out" '需為數字' \
  && ok "reviews validates numeric N" || fail_t "reviews doesn't validate N (got: $rev_out)"
# 12f. accessibility 唯讀（讀 accessibilityDeclarations，無寫入；有 GUI 提示）
acc_body="$(awk '/^cmd_accessibility\(\)/,/^}/' "$ASC")"
hasm "$acc_body" 'accessibilityDeclarations' \
  && ok "accessibility reads accessibilityDeclarations" || fail_t "accessibility wrong endpoint"
hasm "$acc_body" 'write_raw' \
  && fail_t "accessibility has write path (should be read-only)" \
  || ok "accessibility is read-only (no write_raw)"
# 12g. cmd_reviews null/空-stream 防護（P2 review 2 blocks 回歸）
rv2_body="$(awk '/^cmd_reviews\(\)/,/^}/' "$ASC")"
hasm "$rv2_body" 'first($resp' \
  && ok "reviews uses first() (無回覆評論不被空 stream 吞掉)" || fail_t "reviews binds raw stream → drops review with no response"
hasme "$rv2_body" 'rating // 0' \
  && ok "reviews null-guards rating" || fail_t "reviews rating not null-guarded (★*null aborts jq)"
hasme "$rv2_body" 'body // ""' \
  && ok "reviews null-guards body" || fail_t "reviews body not null-guarded (gsub null aborts jq)"

# ── 13. 營利讀面（P3：subscriptions / iap / pricing，全唯讀）──
section "Monetization reads (P3, read-only)"
for sub in subscriptions iap pricing; do
  grep -qE "^[[:space:]]*$sub\)" "$ASC" \
    && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
done
# 13a. 三者皆唯讀：函式 body 不得含 write_raw / emit_write（營利寫入是 P4，gated）
for fn in cmd_subscriptions cmd_iap cmd_pricing; do
  body="$(awk "/^$fn\\(\\)/,/^}/" "$ASC")"
  if hasme "$body" 'write_raw|emit_write'; then
    fail_t "$fn has a write path (P3 must stay read-only; writes belong to P4)"
  else
    ok "$fn is read-only"
  fi
done
# 13b. 端點正確
hasm "$(awk '/^cmd_subscriptions\(\)/,/^}/' "$ASC")" 'subscriptionGroups' \
  && ok "subscriptions reads subscriptionGroups" || fail_t "subscriptions wrong endpoint"
hasm "$(awk '/^cmd_iap\(\)/,/^}/' "$ASC")" 'inAppPurchasesV2' \
  && ok "iap reads inAppPurchasesV2" || fail_t "iap wrong endpoint"
hasm "$(awk '/^cmd_pricing\(\)/,/^}/' "$ASC")" 'appPriceSchedules' \
  && ok "pricing reads appPriceSchedules" || fail_t "pricing wrong endpoint"
# 13c. 迭代 .data 前一律 (.data // []) 或 has("_httpError") 守衛（靜默中止回歸，同 P1 block 類）
for fn in cmd_subscriptions cmd_iap cmd_pricing; do
  body="$(awk "/^$fn\\(\\)/,/^}/" "$ASC")"
  if hasme "$body" '\.data\[\]' && ! hasm "$body" '(.data // \[\])'; then
    fail_t "$fn iterates .data[] without // [] guard (may abort on _httpError)"
  else
    ok "$fn guards .data iteration"
  fi
done
# 13d. pricing 供應地區優雅降級（v2 端點失敗時不中止、給 GUI 提示）
hasm "$(awk '/^cmd_pricing\(\)/,/^}/' "$ASC")" 'appAvailabilityV2' \
  && ok "pricing attempts availability (graceful)" || fail_t "pricing missing availability read"

# ── 結果 ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
