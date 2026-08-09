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
#   8. shell_scan.sh --help → exit 0 + 印出 Usage
#   9. asc_shipped.py --help → exit 0 + 印出 ASC_APP_ID
#
# 另外委派一次跨檔掃描給 ops/shell_scan.sh（實作已搬過去，見檔尾那一段的理由）。

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

section "asc_shipped help"
out=$(run_help "ops/asc_shipped.py"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "asc_shipped help exits 0" 0 "$rc" "$log"
assert_log_contains "asc_shipped help" "ASC_APP_ID" "$log"

section "asc_shipped lazy import"
log="$TMPDIR/log_asc_shipped_lazy_$RANDOM.txt"
uv run --no-project --python 3.13 python -S "$WORKTREE/ops/asc_shipped.py" --help >"$log" 2>&1
rc=$?
assert_rc "asc_shipped help without site packages exits 0" 0 "$rc" "$log"
assert_log_contains "asc_shipped help without site packages" "ASC_APP_ID" "$log"

# ── 跨檔掃描：委派給 ops/shell_scan.sh ──────────────────────────────────────
# 這段的實作 2026-08-08 搬進 `ops/shell_scan.sh`，因為它**沒有任何 gate 會跑**：
# cutover 的 ops/**.sh 路由是 per-file 的（bash -n + 該腳本自己的同名測試），而跨檔
# 掃描器不屬於任何單一腳本。抽成獨立入口後 gate 用 `ops-shell-scan` 路由它，本檔繼續
# 用同一份實作——**共用而非複製**：兩份掃描邏輯就是兩份會各自漂移的判準
# （IMP-20260808-3bbfa2）。正控與 frozen/ 排除都在那支腳本裡。
section "shell_scan help"
out=$(run_help "ops/shell_scan.sh"); rc="${out%%|*}"; log="${out##*|}"
assert_rc "shell_scan help exits 0" 0 "$rc" "$log"
assert_log_contains "shell_scan help" "Usage:" "$log"

section "cross-file shell scan (ops/shell_scan.sh)"
scan_log="$TMPDIR/shell_scan.txt"
"$WORKTREE/ops/shell_scan.sh" "$WORKTREE" >"$scan_log" 2>&1
scan_rc=$?
if [[ $scan_rc -eq 0 ]]; then
  ok "shell_scan.sh clean (rc=0)"
else
  fail_t "shell_scan.sh reported violations (rc=$scan_rc)"
  sed 's/^/      /' "$scan_log" >&2
fi

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
