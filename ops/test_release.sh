#!/usr/bin/env bash
# test_release.sh — release.sh 結構與行為驗證（不打 git 遠端；對齊 test_asc.sh 慣例）
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
REL="$WORKSPACE/ops/release.sh"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }

# ── 1. Syntax ───────────────────────────────────────────────────────────────
section "Syntax"
[[ -f "$REL" ]] && ok "release.sh exists" || fail_t "release.sh missing"
bash -n "$REL"   && ok "release.sh syntax" || fail_t "release.sh syntax error"

# ── 2. 子命令 dispatch 齊全 ─────────────────────────────────────────────────
section "Subcommand dispatch"
for sub in status changelog bump bump-build tag publish release; do
  grep -qE "^[[:space:]]*$sub\)" "$REL" \
    && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
done

# ── 3. release 家族集中 ops/（primitives 已 git mv 進來，scripts/ 舊路徑消失） ─
section "Primitives consolidated into ops/"
[[ -f "$WORKSPACE/ops/release_bump.sh" ]] \
  && ok "ops/release_bump.sh exists"        || fail_t "ops/release_bump.sh missing"
[[ -f "$WORKSPACE/ops/release_changelog.sh" ]] \
  && ok "ops/release_changelog.sh exists"   || fail_t "ops/release_changelog.sh missing"
[[ ! -e "$WORKSPACE/scripts/bump-version.sh" ]] \
  && ok "old scripts/bump-version.sh gone"  || fail_t "scripts/bump-version.sh still present (move incomplete)"
[[ ! -e "$WORKSPACE/scripts/generate-changelog.sh" ]] \
  && ok "old scripts/generate-changelog.sh gone" || fail_t "scripts/generate-changelog.sh still present"

# ── 3b. non-ASC ops test runner exists and keeps help comment-only ───────────
section "Non-ASC ops test runner"
OPS_TEST="$WORKSPACE/ops/test_ops.sh"
[[ -x "$OPS_TEST" ]] \
  && ok "ops/test_ops.sh executable" || fail_t "ops/test_ops.sh missing or not executable"
ops_help="$(bash "$OPS_TEST" --help 2>&1)"
echo "$ops_help" | grep -qE 'set -euo pipefail|^ROOT=|^UV_BIN=' \
  && fail_t "test_ops help leaks shell code" \
  || ok "test_ops help is comment-only"
ops_list="$(bash "$OPS_TEST" --list 2>&1)"
echo "$ops_list" | grep -q '^release$' \
  && ok "test_ops lists release group" || fail_t "test_ops --list missing release"
echo "$ops_list" | grep -q '^podcast-ops$' \
  && ok "test_ops lists podcast-ops group" || fail_t "test_ops --list missing podcast-ops"

# ── 4. release.sh 委派 primitives（不重造 bump/changelog 邏輯） ───────────────
section "Delegates to primitives"
grep -q 'release_bump.sh' "$REL" \
  && ok "bump delegates to release_bump.sh"      || fail_t "release.sh not calling release_bump.sh"
grep -q 'release_changelog.sh' "$REL" \
  && ok "changelog delegates to release_changelog.sh" || fail_t "release.sh not calling release_changelog.sh"

# ── 5. tag 寫入 gate：dry-run 預設，--yes 才 push（對外副作用明示） ───────────
section "Tag gate (dry-run by default)"
grep -q -- '--yes' "$REL" \
  && ok "has --yes confirm flag"            || fail_t "missing --yes flag"
grep -qE 'YES=(0|"")|YES=$' "$REL" \
  && ok "YES defaults to off (dry-run)"     || fail_t "YES not defaulting to dry-run"
tag_body="$(awk '/^cmd_tag\(\)/,/^}/' "$REL")"
# 真正的 push 標的＝`push origin`（script 用 git -C "$ROOT" push origin，dry-run 用中文「推送 origin」不撞）
echo "$tag_body" | grep -q 'push origin' \
  && ok "tag has real push origin"          || fail_t "tag missing push origin"
# 真正的 push/commit/tag 必須在 YES gate 之內
echo "$tag_body" | grep -qE 'if \[\[ \$YES -eq 1 \]\]|if \[ "\$YES"' \
  && ok "tag guards side-effects behind --yes" || fail_t "tag missing --yes guard"
# 負控（鎖不變量）：push origin 不可洩進 dry-run/else 分支 —— 否則無 --yes 也會推
echo "$tag_body" | awk '/else/,/fi/' | grep -q 'push origin' \
  && fail_t "push origin leaked into dry-run branch (would push without --yes)" \
  || ok "dry-run branch contains no push origin"

# ── 5b. detached HEAD 守衛（避免 push origin HEAD；review footgun 回歸） ──────
echo "$tag_body" | grep -q 'detached HEAD' \
  && ok "tag guards detached HEAD"          || fail_t "tag missing detached-HEAD guard (would push origin HEAD)"

# ── 5c. release 統一入口 gate：dry-run 預設、須在 main、委派 deploy/upload ────
section "Release verb gate (unified backend/ios)"
rel_body="$(awk '/^cmd_release\(\)/,/^}/' "$REL")"
echo "$rel_body" | grep -q 'deploy --commit' \
  && ok "release backend delegates to orchestrate deploy" || fail_t "release missing deploy delegation"
echo "$rel_body" | grep -q 'ios_release.sh' \
  && ok "release ios delegates to ios_release.sh --upload" || fail_t "release missing ios_release delegation"
echo "$rel_body" | grep -qE 'branch.*== main|== main.*branch|"\$branch" == main' \
  && ok "release guards on-main"            || fail_t "release missing on-main guard"
# 負控：生產觸點（deploy/upload）不可洩進 dry-run 分支（--yes 前 return）
echo "$rel_body" | awk '/YES -ne 1/,/return 0/' | grep -qE 'deploy --commit|--upload' \
  && fail_t "production touch leaked into release dry-run branch" \
  || ok "release dry-run branch contains no production touch"

# ── 6. 版號格式守衛（x.y.z） ────────────────────────────────────────────────
section "Version format guard"
grep -qE '\[0-9\]\+\\?\.\[0-9\]|[0-9]+\.[0-9]+\.[0-9]+' "$REL" \
  && ok "validates semver x.y.z"            || fail_t "no semver format guard"

# ── 6b. Bash set -u + non-ASCII boundary regression guard ───────────────────
section "Bash variable braces before non-ASCII"
bad_boundary="$(
  rg -n '\$[A-Za-z_][A-Za-z0-9_]*[^[:ascii:]]' "$WORKSPACE/ops" "$WORKSPACE/devops.sh" \
    -g '*.sh' \
    -g '!asc.sh' \
    -g '!test_asc.sh' \
    -g '!ios_release.sh' \
    -g '!test_ios_release.sh' \
    || true
)"
[[ -z "$bad_boundary" ]] \
  && ok "no unbraced shell vars before non-ASCII in non-ASC ops" \
  || fail_t "unbraced shell vars before non-ASCII:\n$bad_boundary"

# ── 7. status / changelog 唯讀（不得碰遠端 / 不寫檔） ────────────────────────
section "Read-only commands stay read-only"
status_body="$(awk '/^cmd_status\(\)/,/^}/' "$REL")"
echo "$status_body" | grep -qE 'git push|git commit|git tag ' \
  && fail_t "status has a write/remote op (must be read-only)" \
  || ok "status is read-only"

# ── 8. 不謊稱 CI 自動發版（無 tag-triggered workflow，驗證先於宣稱） ─────────
section "No false CI claim"
! grep -qE 'GitHub Actions 正在執行|CI 正在發版|自動建立 GitHub Release' "$REL" \
  && ok "no aspirational CI-runs claim"     || fail_t "claims CI auto-releases (no such workflow exists)"

# ── 9. --help 不洩漏 shell 程式碼（dogfood A-F6/C：usage sed 範圍越界回歸） ──
section "Help output stays comment-only"
help_out="$(bash "$REL" --help 2>&1)"
echo "$help_out" | grep -qE 'set -euo pipefail|^ROOT=|^YES=' \
  && fail_t "help leaks shell code (set/ROOT/YES bled into usage)" \
  || ok "help is comment-only (no shell code leak)"

# ── 10. status 漂移警示（dogfood A-F2/C：tag↔檔內版號不一致須警告） ──────────
section "Status drift warning"
echo "$status_body" | grep -q '版號漂移' \
  && ok "status warns on tag↔file version drift" || fail_t "status missing drift warning"

# ── 11. status 長清單截斷（dogfood A-F3：234 筆 commit 不該吐成 688 行牆） ────
section "Status truncates long commit list"
echo "$status_body" | grep -q 'head -15' \
  && ok "status caps commit list (head -15)" || fail_t "status dumps full commit wall (no truncation)"

# ── 12. release_bump.sh ios 只改主 app target（dogfood A-F1：全域 sed 波及測試 bundle） ──
section "bump ios scopes to app target only"
BUMP="$WORKSPACE/ops/release_bump.sh"
# 結構：不得殘留無錨點的全域 sed（[^;]* 不綁當前值＝會掃中所有 target）
grep -q 'MARKETING_VERSION = \[\^;\]\*/MARKETING_VERSION' "$BUMP" \
  && fail_t "release_bump still has unanchored global MARKETING_VERSION sed" \
  || ok "no unanchored global MARKETING_VERSION sed"
# 行為：fixture pbxproj（app=9.9 在前、測試 bundle=1.2.0 在後），bump 後只有 app 變、測試 bundle 不動
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/ios/BooksAndVocab.xcodeproj"
cat > "$TMP/ios/BooksAndVocab.xcodeproj/project.pbxproj" <<'PBX'
/* app Debug */    MARKETING_VERSION = 9.9; CURRENT_PROJECT_VERSION = 7;
/* app Release */  MARKETING_VERSION = 9.9; CURRENT_PROJECT_VERSION = 7;
/* tests Debug */  MARKETING_VERSION = 1.2.0; CURRENT_PROJECT_VERSION = 1;
/* tests Release */MARKETING_VERSION = 1.2.0; CURRENT_PROJECT_VERSION = 1;
PBX
KG_ROOT="$TMP" bash "$BUMP" ios 9.9.1 --yes >/dev/null 2>&1 || fail_t "bump ios fixture run failed"
got_app="$(grep -c 'MARKETING_VERSION = 9.9.1;' "$TMP/ios/BooksAndVocab.xcodeproj/project.pbxproj" || true)"
got_test="$(grep -c 'MARKETING_VERSION = 1.2.0;' "$TMP/ios/BooksAndVocab.xcodeproj/project.pbxproj" || true)"
got_build="$(grep -c 'CURRENT_PROJECT_VERSION = 8;' "$TMP/ios/BooksAndVocab.xcodeproj/project.pbxproj" || true)"
[[ "$got_app" -eq 2 ]]  && ok "app MARKETING_VERSION → 9.9.1 (2 處)"      || fail_t "app bump wrong count: $got_app"
[[ "$got_test" -eq 2 ]] && ok "test bundle MARKETING_VERSION 不動 (still 1.2.0 ×2)" || fail_t "test bundle was clobbered: 1.2.0 count=$got_test"
[[ "$got_build" -eq 2 ]] && ok "app CURRENT_PROJECT_VERSION → 8 (2 處)"   || fail_t "app build bump wrong count: $got_build"

# ── 13. bump 寫入 gate：dry-run 預設、--yes 才寫（對齊 publish / asc.sh set 慣例） ──
section "Bump gate (dry-run by default)"
TMP2="$(mktemp -d)"; trap 'rm -rf "$TMP" "$TMP2"' EXIT
mkdir -p "$TMP2/ios/BooksAndVocab.xcodeproj" "$TMP2/backend/src/kg"
cat > "$TMP2/ios/BooksAndVocab.xcodeproj/project.pbxproj" <<'PBX'
/* app Debug */    MARKETING_VERSION = 9.9; CURRENT_PROJECT_VERSION = 7;
/* app Release */  MARKETING_VERSION = 9.9; CURRENT_PROJECT_VERSION = 7;
PBX
cat > "$TMP2/backend/pyproject.toml" <<'TOML'
[project]
version = "0.1.0"
TOML
cat > "$TMP2/backend/src/kg/api.py" <<'PY'
app = FastAPI(title="kg", version="0.1.0")
PY

# 13a. dry-run（無 --yes）：exit 0、不改任何檔
dry_out="$(KG_ROOT="$TMP2" bash "$BUMP" ios 9.9.1 2>&1)" \
  && ok "bump ios dry-run exits 0" || fail_t "bump ios dry-run exited non-zero"
grep -q 'MARKETING_VERSION = 9.9;' "$TMP2/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && ! grep -q '9\.9\.1' "$TMP2/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && ok "dry-run leaves pbxproj untouched" || fail_t "dry-run modified pbxproj (must not write without --yes)"
# 13b. dry-run 輸出：舊→新 + 指引 --yes
echo "$dry_out" | grep -q '9.9 → 9.9.1' \
  && ok "dry-run prints old→new version" || fail_t "dry-run missing old→new preview: $dry_out"
echo "$dry_out" | grep -q -- '--yes' \
  && ok "dry-run points to --yes" || fail_t "dry-run does not mention --yes"
# 13c. api dry-run：兩檔皆不動、輸出含舊→新
api_dry="$(KG_ROOT="$TMP2" bash "$BUMP" api 0.2.0 2>&1)" \
  && ok "bump api dry-run exits 0" || fail_t "bump api dry-run exited non-zero"
grep -q 'version = "0.1.0"' "$TMP2/backend/pyproject.toml" \
  && grep -q 'version="0.1.0"' "$TMP2/backend/src/kg/api.py" \
  && ok "api dry-run leaves pyproject+api.py untouched" || fail_t "api dry-run modified version files"
echo "$api_dry" | grep -q '0.1.0 → 0.2.0' \
  && ok "api dry-run prints old→new" || fail_t "api dry-run missing old→new preview: $api_dry"
# 13d0. wrapper 無 --yes：dry-run 不寫檔（wrapper 路徑，非只測 primitive）
KG_ROOT="$TMP2" bash "$REL" bump api 0.2.0 >/dev/null 2>&1 \
  && ok "release.sh bump（無 --yes）exits 0" || fail_t "release.sh bump dry-run exited non-zero"
grep -q 'version = "0.1.0"' "$TMP2/backend/pyproject.toml" \
  && ok "release.sh bump（無 --yes）不寫檔" || fail_t "release.sh bump without --yes wrote files"
# 13d1. 多餘 positional 拒絕（不得靜默忽略）
KG_ROOT="$TMP2" bash "$BUMP" ios 9.9.1 extra >/dev/null 2>&1 \
  && fail_t "extra positional silently accepted" || ok "bump 拒絕多餘 positional"
# 13d. --yes 經 release.sh wrapper 傳遞到 primitive（全域 --yes flag 生效）
KG_ROOT="$TMP2" bash "$REL" bump api 0.2.0 --yes >/dev/null 2>&1 \
  || fail_t "release.sh bump api --yes failed"
grep -q 'version = "0.2.0"' "$TMP2/backend/pyproject.toml" \
  && grep -q 'version="0.2.0"' "$TMP2/backend/src/kg/api.py" \
  && ok "release.sh bump --yes writes both api version files" || fail_t "release.sh bump --yes did not write api files"
KG_ROOT="$TMP2" bash "$REL" bump ios 9.9.1 --yes >/dev/null 2>&1 \
  || fail_t "release.sh bump ios --yes failed"
grep -q 'MARKETING_VERSION = 9.9.1;' "$TMP2/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && ok "release.sh bump --yes writes pbxproj" || fail_t "release.sh bump ios --yes did not write pbxproj"

# ── 14. bump-build：同 MARKETING_VERSION 重送、只 bump CURRENT_PROJECT_VERSION ──
section "Bump-build gate (build number only; App Review resubmit)"
TMP3="$(mktemp -d)"; trap 'rm -rf "$TMP" "$TMP2" "$TMP3"' EXIT
mkdir -p "$TMP3/ios/BooksAndVocab.xcodeproj"
cat > "$TMP3/ios/BooksAndVocab.xcodeproj/project.pbxproj" <<'PBX'
/* app Debug */    MARKETING_VERSION = 9.9; CURRENT_PROJECT_VERSION = 7;
/* app Release */  MARKETING_VERSION = 9.9; CURRENT_PROJECT_VERSION = 7;
/* tests Debug */  MARKETING_VERSION = 1.2.0; CURRENT_PROJECT_VERSION = 1;
/* tests Release */MARKETING_VERSION = 1.2.0; CURRENT_PROJECT_VERSION = 1;
PBX
# 14a. dry-run（無 --yes）：exit 0、印舊→新 build、不寫檔
bb_dry="$(KG_ROOT="$TMP3" bash "$REL" bump-build ios 2>&1)" \
  && ok "bump-build ios dry-run exits 0" || fail_t "bump-build ios dry-run exited non-zero: $bb_dry"
echo "$bb_dry" | grep -q '7 → 8' \
  && ok "dry-run prints old→new build" || fail_t "dry-run missing old→new build preview: $bb_dry"
echo "$bb_dry" | grep -q -- '--yes' \
  && ok "dry-run points to --yes" || fail_t "dry-run does not mention --yes"
grep -q 'CURRENT_PROJECT_VERSION = 7;' "$TMP3/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && ! grep -q 'CURRENT_PROJECT_VERSION = 8;' "$TMP3/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && ok "dry-run leaves pbxproj untouched" || fail_t "bump-build dry-run modified pbxproj"
# 14b. --yes 經 wrapper：只動 app CURRENT_PROJECT_VERSION，MARKETING_VERSION 與測試 bundle 不動
KG_ROOT="$TMP3" bash "$REL" bump-build ios --yes >/dev/null 2>&1 \
  || fail_t "release.sh bump-build ios --yes failed"
bb_pbx="$TMP3/ios/BooksAndVocab.xcodeproj/project.pbxproj"
[[ "$(grep -c 'CURRENT_PROJECT_VERSION = 8;' "$bb_pbx" || true)" -eq 2 ]] \
  && ok "app CURRENT_PROJECT_VERSION → 8 (2 處)" || fail_t "app build bump wrong count"
[[ "$(grep -c 'MARKETING_VERSION = 9.9;' "$bb_pbx" || true)" -eq 2 ]] \
  && ok "MARKETING_VERSION 不動 (still 9.9 ×2)" || fail_t "MARKETING_VERSION was touched by bump-build"
[[ "$(grep -c 'CURRENT_PROJECT_VERSION = 1;' "$bb_pbx" || true)" -eq 2 ]] \
  && ok "test bundle build 不動 (still 1 ×2)" || fail_t "test bundle build was clobbered"
# 14c. api 拒絕（api 無 build number 概念），錯誤訊息給可行動指引
bb_api="$(KG_ROOT="$TMP3" bash "$REL" bump-build api 2>&1)" \
  && fail_t "bump-build api should be rejected" \
  || { echo "$bb_api" | grep -q 'bump api' \
         && ok "bump-build api 拒絕且指向 bump api" || fail_t "bump-build api error not actionable: $bb_api"; }
# 14d. 多餘 positional 拒絕（不得靜默忽略）
KG_ROOT="$TMP3" bash "$REL" bump-build ios 9.9.1 >/dev/null 2>&1 \
  && fail_t "bump-build extra positional silently accepted" || ok "bump-build 拒絕多餘 positional"
# 14e. primitive 直呼也拒絕 api build-only
KG_ROOT="$TMP3" bash "$BUMP" api --build-only >/dev/null 2>&1 \
  && fail_t "release_bump --build-only api should be rejected" || ok "primitive 拒絕 api --build-only"

# ── 15. iOS 新 marketing version：typed attestation + false-tag transaction guard ──
section "iOS new-version attestation and false-tag guard"
TMP4="$(mktemp -d)"; trap 'rm -rf "$TMP" "$TMP2" "$TMP3" "$TMP4"' EXIT

make_ios_release_fixture() {
  local fixture="$1" remote="$2"
  mkdir -p "$fixture/ops" "$fixture/ios/BooksAndVocab.xcodeproj"
  cp "$REL" "$BUMP" "$fixture/ops/"
  cat > "$fixture/ios/BooksAndVocab.xcodeproj/project.pbxproj" <<'PBX'
/* app Debug */    MARKETING_VERSION = 2.0.0; CURRENT_PROJECT_VERSION = 5;
/* app Release */  MARKETING_VERSION = 2.0.0; CURRENT_PROJECT_VERSION = 5;
PBX
  cat > "$fixture/ops/ios_release.sh" <<'STUB'
#!/usr/bin/env bash
root="$(cd "$(dirname "$0")/.." && pwd)"
touch "$root/upload.called"
echo "stub upload invoked" >&2
exit "${STUB_UPLOAD_EXIT:-0}"
STUB
  chmod +x "$fixture/ops/ios_release.sh" "$fixture/ops/release_bump.sh"
  git init -q -b main "$fixture"
  git -C "$fixture" config user.name "Release Test"
  git -C "$fixture" config user.email "release-test@example.invalid"
  git -C "$fixture" add .
  git -C "$fixture" commit -qm "fixture: ios 2.0.0"
  git -C "$fixture" tag ios/2.0.0
  git init -q --bare "$remote"
  git -C "$fixture" remote add origin "$remote"
  git -C "$fixture" push -q origin main ios/2.0.0
}

# 15a. 無明確 attestation：必須在 pbx/commit/tag/upload 之前 hard-stop。
fx_a="$TMP4/no-attestation"; remote_a="$TMP4/no-attestation.git"
make_ios_release_fixture "$fx_a" "$remote_a"
head_a="$(git -C "$fx_a" rev-parse HEAD)"
noatt_rc=0
noatt_out="$(bash "$fx_a/ops/release.sh" release ios 2.0.1 --yes 2>&1)" || noatt_rc=$?
[[ "$noatt_rc" -ne 0 ]] \
  && ok "new marketing version without attestation rejects" \
  || fail_t "new marketing version without attestation unexpectedly succeeded"
[[ "$(git -C "$fx_a" rev-parse HEAD)" == "$head_a" ]] \
  && grep -q 'MARKETING_VERSION = 2.0.0;' "$fx_a/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
  && ! git -C "$fx_a" rev-parse -q --verify refs/tags/ios/2.0.1 >/dev/null \
  && ! git --git-dir="$remote_a" rev-parse -q --verify refs/tags/ios/2.0.1 >/dev/null \
  && [[ ! -e "$fx_a/upload.called" ]] \
  && ok "attestation rejection is pre-mutation (pbx/commit/tag/upload untouched)" \
  || fail_t "attestation rejection happened after a mutation"
echo "$noatt_out" | grep -q 'bump-build ios' \
  && ok "missing-attestation error points rejected resubmits to bump-build" \
  || fail_t "missing-attestation error lacks bump-build guidance: $noatt_out"

# 15b. attested previous version 必須和 latest local tag 一致。
fx_b="$TMP4/mismatch"; remote_b="$TMP4/mismatch.git"
make_ios_release_fixture "$fx_b" "$remote_b"
mismatch_rc=0
mismatch_out="$(bash "$fx_b/ops/release.sh" release ios 2.0.1 --new-version-after-ready 1.9.9 --yes 2>&1)" || mismatch_rc=$?
[[ "$mismatch_rc" -ne 0 ]] \
  && echo "$mismatch_out" | grep -q 'ios/2.0.0' \
  && ok "mismatched previous-ready version rejects with latest-tag evidence" \
  || fail_t "mismatched previous-ready version was not actionably rejected: $mismatch_out"

# 15c. 正確 attestation 後 upload 若失敗，不得留下 false release commit/tag/push。
fx_c="$TMP4/upload-failure"; remote_c="$TMP4/upload-failure.git"
make_ios_release_fixture "$fx_c" "$remote_c"
head_c="$(git -C "$fx_c" rev-parse HEAD)"
upload_rc=0
upload_out="$(STUB_UPLOAD_EXIT=23 bash "$fx_c/ops/release.sh" release ios 2.0.1 --new-version-after-ready 2.0.0 --yes 2>&1)" || upload_rc=$?
[[ "$upload_rc" -ne 0 && -e "$fx_c/upload.called" ]] \
  && ok "attested release reaches upload and propagates upload failure" \
  || fail_t "attested release did not exercise failing upload: $upload_out"
[[ "$(git -C "$fx_c" rev-parse HEAD)" == "$head_c" ]] \
  && ! git -C "$fx_c" rev-parse -q --verify refs/tags/ios/2.0.1 >/dev/null \
  && ! git --git-dir="$remote_c" rev-parse -q --verify refs/tags/ios/2.0.1 >/dev/null \
  && [[ "$(git --git-dir="$remote_c" rev-parse refs/heads/main)" == "$head_c" ]] \
  && ok "upload failure leaves no false release commit/tag/push" \
  || fail_t "upload failure left a false release commit/tag/push"

# 15d. direct tag 也是外部 release marker，不得繞過同一 attestation guard。
fx_d="$TMP4/direct-tag"; remote_d="$TMP4/direct-tag.git"
make_ios_release_fixture "$fx_d" "$remote_d"
head_d="$(git -C "$fx_d" rev-parse HEAD)"
direct_rc=0
direct_out="$(bash "$fx_d/ops/release.sh" bump ios 2.0.1 --yes 2>&1 && bash "$fx_d/ops/release.sh" tag ios 2.0.1 --yes 2>&1)" || direct_rc=$?
[[ "$direct_rc" -ne 0 \
   && "$(git -C "$fx_d" rev-parse HEAD)" == "$head_d" \
   && ! -e "$fx_d/upload.called" ]] \
  && ! git -C "$fx_d" rev-parse -q --verify refs/tags/ios/2.0.1 >/dev/null \
  && ! git --git-dir="$remote_d" rev-parse -q --verify refs/tags/ios/2.0.1 >/dev/null \
  && ok "direct iOS tag cannot bypass new-version attestation" \
  || fail_t "direct iOS tag bypassed attestation: $direct_out"

# 15e. 正確 previous attestation 也不能授權 semver 倒退。
fx_e="$TMP4/downgrade"; remote_e="$TMP4/downgrade.git"
make_ios_release_fixture "$fx_e" "$remote_e"
head_e="$(git -C "$fx_e" rev-parse HEAD)"
downgrade_rc=0
downgrade_out="$(bash "$fx_e/ops/release.sh" release ios 1.9.9 --new-version-after-ready 2.0.0 --yes 2>&1)" || downgrade_rc=$?
[[ "$downgrade_rc" -ne 0 \
   && "$(git -C "$fx_e" rev-parse HEAD)" == "$head_e" \
   && ! -e "$fx_e/upload.called" ]] \
  && echo "$downgrade_out" | grep -q '高於.*2.0.0' \
  && ok "iOS new marketing version must increase monotonically" \
  || fail_t "iOS downgrade was not safely rejected: $downgrade_out"

# 15f. 合法恢復：版號已在 HEAD、upload 成功時，跳過空 commit 並 tag/push current HEAD。
fx_f="$TMP4/already-committed"; remote_f="$TMP4/already-committed.git"
make_ios_release_fixture "$fx_f" "$remote_f"
sed -i '' 's/MARKETING_VERSION = 2.0.0;/MARKETING_VERSION = 2.0.1;/g; s/CURRENT_PROJECT_VERSION = 5;/CURRENT_PROJECT_VERSION = 6;/g' \
  "$fx_f/ios/BooksAndVocab.xcodeproj/project.pbxproj"
git -C "$fx_f" add ios/BooksAndVocab.xcodeproj/project.pbxproj
git -C "$fx_f" commit -qm "fixture: version already committed"
committed_head="$(git -C "$fx_f" rev-parse HEAD)"
committed_rc=0
committed_out="$(bash "$fx_f/ops/release.sh" release ios 2.0.1 --new-version-after-ready 2.0.0 --yes 2>&1)" || committed_rc=$?
[[ "$committed_rc" -eq 0 && -e "$fx_f/upload.called" \
   && "$(git -C "$fx_f" rev-parse HEAD)" == "$committed_head" \
   && "$(git -C "$fx_f" rev-parse refs/tags/ios/2.0.1)" == "$committed_head" \
   && "$(git --git-dir="$remote_f" rev-parse refs/tags/ios/2.0.1)" == "$committed_head" \
   && "$(git --git-dir="$remote_f" rev-parse refs/heads/main)" == "$committed_head" ]] \
  && ok "already-committed version uploads then tags/pushes current HEAD" \
  || fail_t "already-committed version left a partial release: $committed_out"

# ── 結果 ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
