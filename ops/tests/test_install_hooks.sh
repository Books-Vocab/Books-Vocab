#!/usr/bin/env bash
# test_install_hooks.sh — ops/install_hooks.sh 與 .githooks/pre-commit 的接線回歸。
#
# 守兩件事：
#   1. install_hooks.sh 的 help / check / install / uninstall 語意。
#   2. 裝上之後，違規的 staged 改動**真的會被 pre-commit 擋下**（不是只證它會綠）。
#      做法：mktemp 造拋棄式 git repo，把本 repo 真正那份 .githooks/pre-commit 複製進去，
#      用 exit 1 的 stub ops/verify_design_system.sh 當被觸發的 guard。
#      反控是「未安裝時同一筆改動 commit 得過」——沒有反控就分不出「hook 擋的」與
#      「這個 fixture 本來就 commit 不了」。
set -o pipefail

WORKTREE="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/kg_install_hooks_XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

export GIT_CONFIG_GLOBAL="$TMP/gitconfig-global"
export GIT_CONFIG_SYSTEM="$TMP/gitconfig-system"
: >"$GIT_CONFIG_GLOBAL"
: >"$GIT_CONFIG_SYSTEM"

mkdir -p "$TMP/bin"
for b in uv node rg; do
  printf '#!/bin/sh\nexit 0\n' >"$TMP/bin/$b"
  chmod +x "$TMP/bin/$b"
done
STUB_PATH="$TMP/bin:$PATH"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*" >&2; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }

make_fixture() {   # $1 = 目錄
  local d="$1"
  mkdir -p "$d/.githooks" "$d/ops" "$d/design-system"
  cp "$WORKTREE/.githooks/pre-commit" "$d/.githooks/pre-commit"
  chmod +x "$d/.githooks/pre-commit"
  printf '#!/bin/sh\necho "STUB_DS_GUARD_FIRED" >&2\nexit 1\n' >"$d/ops/verify_design_system.sh"
  chmod +x "$d/ops/verify_design_system.sh"
  git init -q "$d"
  git -C "$d" symbolic-ref HEAD refs/heads/main
  git -C "$d" config user.email kg-test@example.com
  git -C "$d" config user.name kg-test
  printf 'seed\n' >"$d/design-system/tokens.json"
  git -C "$d" add -A
  git -C "$d" commit -qm seed
}

commit_count() { git -C "$1" rev-list --count HEAD; }

try_violating_commit() {   # $1 = 目錄, $2 = log 檔；回傳 git commit 的 rc
  local d="$1" log="$2" rc=0
  printf 'change %s\n' "$RANDOM" >>"$d/design-system/tokens.json"
  git -C "$d" add design-system/tokens.json
  PATH="$STUB_PATH" git -C "$d" commit -m "ds change" >"$log" 2>&1 || rc=$?
  return "$rc"
}

section "syntax + help"
bash -n "$WORKTREE/ops/install_hooks.sh" && ok "install_hooks.sh syntax" || fail_t "install_hooks.sh syntax"
"$WORKTREE/ops/install_hooks.sh" --help >"$TMP/help.txt" 2>&1; rc=$?
[[ $rc -eq 0 ]] && ok "--help exits 0" || fail_t "--help expect rc=0 got rc=$rc"
grep -q 'core.hooksPath' "$TMP/help.txt" \
  && ok "--help 說明 core.hooksPath" \
  || { fail_t "--help 未提 core.hooksPath"; sed 's/^/      /' "$TMP/help.txt" >&2; }

section "反控：未安裝時，違規改動 commit 得過"
A="$TMP/repo_a"; make_fixture "$A"
before="$(commit_count "$A")"
if try_violating_commit "$A" "$TMP/a.log"; then
  after="$(commit_count "$A")"
  [[ "$after" -eq $((before + 1)) ]] \
    && ok "未安裝時 commit 成立（反控有效）" \
    || fail_t "未安裝時 rc=0 但 commit 數沒增加（${before} → ${after}）"
else
  fail_t "未安裝時 commit 就被擋 — fixture 不乾淨，後面的斷言會是假綠"
  sed 's/^/      /' "$TMP/a.log" >&2
fi

section "安裝後：--check 綠，且違規 commit 被擋"
B="$TMP/repo_b"; make_fixture "$B"
( cd "$B" && "$WORKTREE/ops/install_hooks.sh" --yes ) >"$TMP/b_install.log" 2>&1; rc=$?
[[ $rc -eq 0 ]] && ok "--yes 安裝 rc=0" \
  || { fail_t "--yes 安裝 rc=$rc"; sed 's/^/      /' "$TMP/b_install.log" >&2; }
val="$(git -C "$B" config --get core.hooksPath || true)"
[[ "$val" == ".githooks" ]] && ok "fixture core.hooksPath = .githooks" \
  || fail_t "fixture core.hooksPath = ${val:-<未設定>}"
( cd "$B" && "$WORKTREE/ops/install_hooks.sh" --check ) >"$TMP/b_check.log" 2>&1; rc=$?
[[ $rc -eq 0 ]] && ok "--check 安裝後 rc=0" \
  || { fail_t "--check 安裝後 rc=$rc"; sed 's/^/      /' "$TMP/b_check.log" >&2; }
before="$(commit_count "$B")"
if try_violating_commit "$B" "$TMP/b.log"; then
  fail_t "安裝後違規 commit 仍然成立 — hook 沒有被執行"
  sed 's/^/      /' "$TMP/b.log" >&2
else
  ok "安裝後違規 commit 被擋下"
fi
grep -q 'STUB_DS_GUARD_FIRED' "$TMP/b.log" \
  && ok "擋下的原因是 design-system guard 被觸發" \
  || { fail_t "commit 失敗了，但輸出沒有 STUB_DS_GUARD_FIRED — 擋它的是別的原因"; sed 's/^/      /' "$TMP/b.log" >&2; }
after="$(commit_count "$B")"
[[ "$after" -eq "$before" ]] && ok "被擋下時 commit 數未增加" \
  || fail_t "被擋下卻多了一個 commit（${before} → ${after}）"

section "--check 未安裝時 rc=1；--uninstall 是有效逃生口"
C="$TMP/repo_c"; make_fixture "$C"
( cd "$C" && "$WORKTREE/ops/install_hooks.sh" --check ) >"$TMP/c_check0.log" 2>&1; rc=$?
[[ $rc -eq 1 ]] && ok "--check 未安裝時 rc=1" || fail_t "--check 未安裝時 rc=${rc}（期望 1）"
( cd "$C" && "$WORKTREE/ops/install_hooks.sh" --yes ) >/dev/null 2>&1
( cd "$C" && "$WORKTREE/ops/install_hooks.sh" --uninstall ) >"$TMP/c_uninstall.log" 2>&1; rc=$?
[[ $rc -eq 0 ]] && ok "--uninstall rc=0" \
  || { fail_t "--uninstall rc=$rc"; sed 's/^/      /' "$TMP/c_uninstall.log" >&2; }
val="$(git -C "$C" config --get core.hooksPath || true)"
[[ -z "$val" ]] && ok "--uninstall 後 core.hooksPath 已清空" \
  || fail_t "--uninstall 後 core.hooksPath = $val"
if try_violating_commit "$C" "$TMP/c.log"; then
  ok "--uninstall 後違規 commit 又能成立（逃生口有效）"
else
  fail_t "--uninstall 後 commit 仍被擋"
  sed 's/^/      /' "$TMP/c.log"
fi

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
