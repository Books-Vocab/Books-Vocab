#!/usr/bin/env bash
# test_script_help.sh — 守住常用 ops 腳本的 help surface。
#
# 目前覆蓋：
#   1. catalyst_lint.sh --help → exit 0 + 印出 Modes
#   2. release_bump.sh --help → exit 0 + 印出 用法
#   3. release_changelog.sh --help → exit 0 + 印出 用法
#   4. podcast_upload.sh --help → exit 0 + 印出 Usage
#   5. worktree_registry.py --help → exit 0 + 印出 orphan sentinel

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

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
