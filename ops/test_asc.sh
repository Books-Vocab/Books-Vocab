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
for sub in versions builds metadata info review-status set; do
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
# helper 由 env 參數化 key（與 asc.sh config 單一真相對齊，不雙寫死）
grep -qE 'environ|getenv' "$GET" \
  && ok "asc_get.py key params from env"  || fail_t "asc_get.py hardcodes key (should read env)"

# ── 結果 ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
