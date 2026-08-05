#!/usr/bin/env bash
# test_script_help.sh — 守住常用 ops 腳本的 help surface。
#
# 目前覆蓋：
#   1. catalyst_lint.sh --help → exit 0 + 印出 Modes
#   2. release_bump.sh --help → exit 0 + 印出 用法
#   3. release_changelog.sh --help → exit 0 + 印出 用法
#   4. podcast_upload.sh --help → exit 0 + 印出 Usage
#   5. worktree_registry.py --help → exit 0 + 印出 orphan sentinel
#   6. worktree_orchestrate.py --help → exit 0 + 列出 preflight/gate/cutover 子指令
#   7. worktree_registry.py sweep --help → exit 0 + 揭示 --exclude-current 旗標

set -o pipefail

WORKTREE="$(cd "$(dirname "$0")/../.." && pwd)"
TMPDIR="$(mktemp -d -t kg_script_help_XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }

run_help() {
  local script="$1"
  local logfile="$TMPDIR/log_$RANDOM.txt"
  "$WORKTREE/$script" --help >"$logfile" 2>&1
  local rc=$?
  echo "$rc|$logfile"
}

assert_rc() {
  local name="$1" expected="$2" got="$3" logfile="$4"
  if [[ "$got" == "$expected" ]]; then
    ok "$name (rc=$got)"
  else
    fail_t "$name expect rc=$expected got rc=$got"
    sed 's/^/      /' "$logfile" >&2
  fi
}

assert_log_contains() {
  local name="$1" needle="$2" logfile="$3"
  if grep -q -- "$needle" "$logfile"; then
    ok "$name contains \"$needle\""
  else
    fail_t "$name missing \"$needle\""
    sed 's/^/      /' "$logfile" >&2
  fi
}

section "Syntax"
bash -n "$WORKTREE/ops/catalyst_lint.sh" && ok "catalyst_lint.sh syntax" || fail_t "catalyst_lint.sh syntax"
bash -n "$WORKTREE/ops/release_bump.sh" && ok "release_bump.sh syntax" || fail_t "release_bump.sh syntax"
bash -n "$WORKTREE/ops/release_changelog.sh" && ok "release_changelog.sh syntax" || fail_t "release_changelog.sh syntax"
bash -n "$WORKTREE/ops/podcast_upload.sh" && ok "podcast_upload.sh syntax" || fail_t "podcast_upload.sh syntax"

section "catalyst_lint help"
out=$(run_help "ops/catalyst_lint.sh"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "catalyst_lint help exits 0" 0 "$rc" "$log"
assert_log_contains "catalyst_lint help" "Modes:" "$log"

section "release_bump help"
out=$(run_help "ops/release_bump.sh"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "release_bump help exits 0" 0 "$rc" "$log"
assert_log_contains "release_bump help" "用法:" "$log"

section "release_changelog help"
out=$(run_help "ops/release_changelog.sh"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "release_changelog help exits 0" 0 "$rc" "$log"
assert_log_contains "release_changelog help" "用法:" "$log"

section "podcast_upload help"
out=$(run_help "ops/podcast_upload.sh"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "podcast_upload help exits 0" 0 "$rc" "$log"
assert_log_contains "podcast_upload help" "Usage:" "$log"

section "worktree_registry help"
out=$(run_help "ops/worktree_registry.py"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "worktree_registry help exits 0" 0 "$rc" "$log"
assert_log_contains "worktree_registry help" "orphan sentinel" "$log"

section "worktree_registry sweep --exclude-current surface"
log="$TMPDIR/log_sweep_$RANDOM.txt"
"$WORKTREE/ops/worktree_registry.py" sweep --help >"$log" 2>&1; rc=$?
assert_rc "worktree_registry sweep help exits 0" 0 "$rc" "$log"
assert_log_contains "worktree_registry sweep help" "--exclude-current" "$log"

section "worktree_orchestrate help"
out=$(run_help "ops/worktree_orchestrate.py"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "worktree_orchestrate help exits 0" 0 "$rc" "$log"
assert_log_contains "worktree_orchestrate help" "preflight" "$log"
assert_log_contains "worktree_orchestrate help" "cutover" "$log"

# ── $VAR 緊接全形標點 = 定時炸彈 ────────────────────────────────────────────
# bash 在 **UTF-8 LC_CTYPE** 下會把全形標點的首個 byte 吃進變數名：
#   echo "已回到 $sha，但…"   →   `sha\xEF: unbound variable`  →  set -u 當場殺掉腳本
# C locale 下同一行完全正常，所以**開發機測不出來、跑起來才炸**。實測矩陣：
#   我的 Bash tool（LC_CTYPE unset）→ 過；gate runner（LC_CTYPE=C.UTF-8）→ 死；
#   felix launchd（未設 locale）→ 過；人在 Terminal.app（UTF-8）→ **死**。
# 這個 repo 的字串大量是中文，而命中的 9 處**全部落在錯誤路徑**——也就是它只在
# 「已經出事了、正要印出原因」的那一刻引爆，把診斷訊息換成一行 unbound variable。
# 2026-08-04 它讓 kg_reconcile.sh 的回滾告警整個吞掉 verdict（IMP-0062）。
# 修法一律是 `${VAR}`。frozen/ 具名排除：刻意冷凍、不執行。
section "no \$VAR abuts full-width punctuation (UTF-8 locale time bomb)"
# 不用 `grep -P`：macOS 的 BSD grep 沒有這個旗標，而本檔第一版正是 `-P` + `2>/dev/null`
# ——每個檔案都 "invalid option" 失敗、輸出全空、掃描器報 ✓。**沉默被當成沒有違規**，
# 這正是它要防的那類假綠。改用 ERE 交替（多位元組字面值在 C locale 下也是逐 byte 比對）。
FW_PUNCT='(，|。|、|：|；|！|？|「|」|（|）)'
FW_RE="\"[^\"]*[$][a-zA-Z_][a-zA-Z0-9_]*$FW_PUNCT"

# 正控：先證明掃描器抓得到已知的違規，否則下面的「沒有命中」與「掃描器壞了」無法區分。
fw_fixture="$TMPDIR/fw_fixture.sh"
printf 'echo "已回到 $sha，但…"\necho "safe ${sha}，braced"\n' > "$fw_fixture"  # fw-allow: 這是正控 fixture 本身，單引號內不展開
fw_probe="$(grep -nE "$FW_RE" "$fw_fixture" 2>&1 || true)"
if [[ "$fw_probe" != *'已回到'* ]]; then
  fail_t "full-width scanner cannot flag a known violation — probe broken, not the tree: ${fw_probe:-<no output>}"
elif [[ "$fw_probe" == *braced* ]]; then
  fail_t "full-width scanner also flags the braced (safe) form — pattern too broad"
else
  ok "full-width scanner flags the bad form and spares \${VAR} (positive control)"
fi

fw_hits="$(
  git -C "$WORKTREE" ls-files '*.sh' \
    | grep -v '^frozen/' \
    | while read -r f; do
        # 註解行 shell 不展開 → 真的無害；`# fw-allow: <理由>` 是具名豁免（需寫理由）。
        grep -nE "$FW_RE" "$WORKTREE/$f" 2>/dev/null \
          | grep -v '^[0-9][0-9]*: *#' | grep -v 'fw-allow' | sed "s|^|$f:|"
      done
)"
scanned="$(git -C "$WORKTREE" ls-files '*.sh' | grep -cv '^frozen/')"
if (( scanned < 10 )); then
  fail_t "only scanned $scanned shell script(s) — the probe is broken, not the tree"
elif [[ -n "$fw_hits" ]]; then
  fail_t "\$VAR abuts full-width punctuation (use \${VAR}); dies under UTF-8 LC_CTYPE:"
  printf '%s\n' "$fw_hits" | sed 's/^/      /'
else
  ok "no \$VAR abuts full-width punctuation across $scanned tracked shell script(s)"
fi

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
