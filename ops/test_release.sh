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
for sub in status changelog bump publish; do
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

# ── 5. publish 寫入 gate：dry-run 預設，--yes 才 push（對外副作用明示） ───────
section "Publish gate (dry-run by default)"
grep -q -- '--yes' "$REL" \
  && ok "has --yes confirm flag"            || fail_t "missing --yes flag"
grep -qE 'YES=(0|"")|YES=$' "$REL" \
  && ok "YES defaults to off (dry-run)"     || fail_t "YES not defaulting to dry-run"
pub_body="$(awk '/^cmd_publish\(\)/,/^}/' "$REL")"
# 真正的 push 標的＝`push origin`（script 用 git -C "$ROOT" push origin，dry-run 用中文「推送 origin」不撞）
echo "$pub_body" | grep -q 'push origin' \
  && ok "publish has real push origin"      || fail_t "publish missing push origin"
# 真正的 push/commit/tag 必須在 YES gate 之內
echo "$pub_body" | grep -qE 'if \[\[ \$YES -eq 1 \]\]|if \[ "\$YES"' \
  && ok "publish guards side-effects behind --yes" || fail_t "publish missing --yes guard"
# 負控（鎖不變量）：push origin 不可洩進 dry-run/else 分支 —— 否則無 --yes 也會推
echo "$pub_body" | awk '/else/,/fi/' | grep -q 'push origin' \
  && fail_t "push origin leaked into dry-run branch (would push without --yes)" \
  || ok "dry-run branch contains no push origin"

# ── 5b. detached HEAD 守衛（避免 push origin HEAD；review footgun 回歸） ──────
echo "$pub_body" | grep -q 'detached HEAD' \
  && ok "publish guards detached HEAD"      || fail_t "publish missing detached-HEAD guard (would push origin HEAD)"

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
KG_ROOT="$TMP" bash "$BUMP" ios 9.9.1 >/dev/null 2>&1 || fail_t "bump ios fixture run failed"
got_app="$(grep -c 'MARKETING_VERSION = 9.9.1;' "$TMP/ios/BooksAndVocab.xcodeproj/project.pbxproj" || true)"
got_test="$(grep -c 'MARKETING_VERSION = 1.2.0;' "$TMP/ios/BooksAndVocab.xcodeproj/project.pbxproj" || true)"
got_build="$(grep -c 'CURRENT_PROJECT_VERSION = 8;' "$TMP/ios/BooksAndVocab.xcodeproj/project.pbxproj" || true)"
[[ "$got_app" -eq 2 ]]  && ok "app MARKETING_VERSION → 9.9.1 (2 處)"      || fail_t "app bump wrong count: $got_app"
[[ "$got_test" -eq 2 ]] && ok "test bundle MARKETING_VERSION 不動 (still 1.2.0 ×2)" || fail_t "test bundle was clobbered: 1.2.0 count=$got_test"
[[ "$got_build" -eq 2 ]] && ok "app CURRENT_PROJECT_VERSION → 8 (2 處)"   || fail_t "app build bump wrong count: $got_build"

# ── 結果 ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
