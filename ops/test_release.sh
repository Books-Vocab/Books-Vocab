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

# ── 結果 ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
