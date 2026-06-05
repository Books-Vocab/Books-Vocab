#!/usr/bin/env bash
# test_asc.sh — asc.sh 結構與行為驗證（不打 live API；對齊 test_devops.sh 慣例）
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
ASC="$WORKSPACE/ops/asc.sh"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }

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
echo "$set_body" | grep -q 'app-store-version-localizations modify' \
  && ok "modify lives inside cmd_set"    || fail_t "modify not in cmd_set"
# dry-run 預設：YES 變數預設為 0/空
grep -qE 'YES=(0|"")|YES=$' "$ASC" \
  && ok "YES defaults to off (dry-run)"  || fail_t "YES not defaulting to dry-run"
# 負控（鎖不變量）：modify 不可洩進 dry-run（else…fi）分支 —— 否則無 --yes 也會寫
echo "$set_body" | awk '/else/,/fi/' | grep -q 'localizations modify' \
  && fail_t "modify leaked into dry-run branch (would write without --yes)" \
  || ok "dry-run branch contains no modify call"
# value 空值守衛（C1 回歸）：cmd_set 必須同時檢 field 與 value 非空
echo "$set_body" | grep -qE '\-n "\$field" && -n "\$value"' \
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
echo "$rv_body" | grep -q '|| true' \
  && ok "resolve_version pipeline guarded (|| true)" || fail_t "resolve_version may abort silently (no || true)"
rl_body="$(awk '/^resolve_loc\(\)/,/^}/' "$ASC" | grep -v '^[[:space:]]*#')"
echo "$rl_body" | grep -q '|| true' \
  && ok "resolve_loc pipeline guarded (|| true)"     || fail_t "resolve_loc may abort silently (no || true)"

# ── 8. 取值型選項守衛（dogfood C：--key/--version-id 後無值不該噴 unbound variable） ──
section "Value-taking options guarded"
grep -q 'need_val' "$ASC" \
  && ok "has need_val guard"               || fail_t "missing need_val guard for value options"
# 行為驗證：--key 後無值 → 友善訊息 + exit 1，而非 set -u 的 unbound variable
kv_out="$(bash "$ASC" --key 2>&1 || true)"
echo "$kv_out" | grep -q '需要一個值' \
  && ok "--key with no value → friendly error" || fail_t "--key no-value not friendly (got: $kv_out)"
echo "$kv_out" | grep -qi 'unbound variable' \
  && fail_t "--key no-value still hits set -u unbound variable" \
  || ok "no set -u unbound crash on missing value"

# ── 9. --help 不洩漏 shell 程式碼（與 release.sh 同步的 usage awk 修正） ──────
section "Help output stays comment-only"
help_out="$(bash "$ASC" --help 2>&1)"
echo "$help_out" | grep -qE 'set -euo pipefail|^KEY_ID=|^ISSUER_ID=' \
  && fail_t "help leaks shell code" || ok "help is comment-only (no shell code leak)"

# ── 10. set-review 寫入路徑（appStoreReviewDetail，codemagic 未暴露 → raw PATCH）──
section "set-review write path (raw PATCH, gated)"
PATCH="$WORKSPACE/ops/asc_patch.py"
[[ -f "$PATCH" ]] && ok "asc_patch.py companion exists" || fail_t "asc_patch.py missing"
# 寫入 helper 必須是 PATCH（而非 GET），且 JWT 在 py、不在 asc.sh（本檔零 JWT 不變量延伸）
grep -qE "method[[:space:]]*=[[:space:]]*[\"']PATCH" "$PATCH" \
  && ok "asc_patch.py uses PATCH method"   || fail_t "asc_patch.py not a PATCH writer"
grep -q 'jwt.encode' "$PATCH" \
  && ok "asc_patch.py is where write-JWT lives" || fail_t "asc_patch.py missing JWT mint"
grep -q 'HTTPError' "$PATCH" && grep -q 'URLError' "$PATCH" \
  && ok "asc_patch.py handles HTTP+network errors" || fail_t "asc_patch.py lacks graceful error handling"
grep -q 'asc_patch.py' "$ASC" \
  && ok "asc.sh delegates writes to asc_patch.py" || fail_t "asc.sh not delegating raw PATCH"
# cmd_set_review 的寫入（patch_raw）必須 gated 在 --yes 內 —— 負控：dry-run/else 分支不得有 patch_raw
sr_body="$(awk '/^cmd_set_review\(\)/,/^}/' "$ASC")"
echo "$sr_body" | grep -q 'patch_raw' \
  && ok "set-review has real patch_raw write" || fail_t "set-review missing patch_raw"
echo "$sr_body" | grep -qE 'if \[\[ \$YES -eq 1 \]\]' \
  && ok "set-review guards write behind --yes" || fail_t "set-review missing --yes guard"
echo "$sr_body" | awk '/else/,/fi/' | grep -q 'patch_raw' \
  && fail_t "patch_raw leaked into dry-run branch (would write without --yes)" \
  || ok "dry-run branch contains no patch_raw"
# demo-required 必須驗 boolean（避免寫入非法值）
echo "$sr_body" | grep -q 'true.*false\|false.*true' \
  && ok "demo-required validates true/false" || fail_t "demo-required boolean not validated"
# 行為：跨物件欄位互相指路（set notes → set-review；set-review description → set）
echo "$(bash "$ASC" set notes x 2>&1)" | grep -q 'set-review' \
  && ok "set <review-field> routes to set-review" || fail_t "set doesn't route review fields"
echo "$(bash "$ASC" set-review description x 2>&1)" | grep -qE 'asc.sh set ' \
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
# 11c. 共用 emit_patch：gate 不變量集中一處 —— patch_raw 只在 --yes 分支，dry-run(else) 分支零 patch_raw
ep_body="$(awk '/^emit_patch\(\)/,/^}/' "$ASC")"
echo "$ep_body" | grep -q 'patch_raw' \
  && ok "emit_patch performs real patch_raw write" || fail_t "emit_patch missing patch_raw"
echo "$ep_body" | grep -qE 'if \[\[ \$YES -eq 1 \]\]' \
  && ok "emit_patch guards write behind --yes"      || fail_t "emit_patch missing --yes guard"
echo "$ep_body" | awk '/else/,/fi/' | grep -q 'patch_raw' \
  && fail_t "patch_raw leaked into emit_patch dry-run branch (would write without --yes)" \
  || ok "emit_patch dry-run branch contains no patch_raw"
# 11d. 每個寫指令都「透過 emit_patch」收尾，且不自行 patch_raw（否則繞過集中 gate）
for fn in cmd_set_appinfo cmd_set_eula cmd_set_content_rights cmd_set_category cmd_set_rating; do
  body="$(awk "/^$fn\\(\\)/,/^}/" "$ASC")"
  echo "$body" | grep -q 'emit_patch' \
    && ok "$fn routes through emit_patch"        || fail_t "$fn doesn't use emit_patch"
  echo "$body" | grep -q 'patch_raw' \
    && fail_t "$fn calls patch_raw directly (bypasses central gate)" \
    || ok "$fn delegates write (no direct patch_raw)"
done
# 11e. body 形狀正確：set-appinfo 用 appInfoLocalizations attributes；set-category 用 relationships（非 attributes）
echo "$(awk '/^cmd_set_appinfo\(\)/,/^}/' "$ASC")" | grep -q 'type:"appInfoLocalizations"' \
  && ok "set-appinfo body targets appInfoLocalizations" || fail_t "set-appinfo body wrong type"
cat_body="$(awk '/^cmd_set_category\(\)/,/^}/' "$ASC")"
echo "$cat_body" | grep -q 'relationships' \
  && ok "set-category uses relationship body"   || fail_t "set-category not using relationships"
echo "$cat_body" | grep -q 'type:"appCategories"' \
  && ok "set-category references appCategories"  || fail_t "set-category missing appCategories ref"
# 11f. set-content-rights 只收 uses|none（防亂值）
cr_out="$(bash "$ASC" set-content-rights bogus 2>&1 || true)"
echo "$cr_out" | grep -q 'uses|none' \
  && ok "set-content-rights validates uses|none" || fail_t "set-content-rights accepts invalid value"
# 11g. 跨物件指路：set name → set-appinfo；set-appinfo description → set
echo "$(bash "$ASC" set name x 2>&1)" | grep -q 'set-appinfo' \
  && ok "set <appinfo-field> routes to set-appinfo" || fail_t "set doesn't route appinfo fields"
echo "$(bash "$ASC" set-appinfo description x 2>&1)" | grep -qE 'asc.sh set ' \
  && ok "set-appinfo <version-field> routes to set" || fail_t "set-appinfo doesn't route version fields"
# 11h. EULA 寫入解析 endUserLicenseAgreement
echo "$(awk '/^cmd_set_eula\(\)/,/^}/' "$ASC")" | grep -q 'endUserLicenseAgreement' \
  && ok "set-eula resolves endUserLicenseAgreement" || fail_t "set-eula missing EULA resolution"

# ── 結果 ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
