#!/usr/bin/env bash
# test_docs_lint_generated_check.sh — IMP-20260805-462d28：generated 文檔的等值 gate
#
# 守的是什麼：docs/registry.yml 的 `generator:` 是全 registry 唯一宣告了「可機器檢查
# 關係」的欄位，但 docs_lint.sh 從來只驗「generator 欄非空 + 該檔存在」。產物與產生器
# 輸出的關係從未被評估，所以一份 generated 文檔可以腐爛到面目全非而 gate 照樣回綠。
# 本測試釘住三件事：
#   1. 產物 == generator 輸出 → rc=0
#   2. 產物 drift            → rc=1，且**具名該筆 entry**
#   3. kind=generated 卻沒宣告 check: → rc=1（洞由構造關上，不靠記得）
#   4. stdin canary：check 命令若吃掉 stdin，後續 registry entry 會無聲消失
#   5. 真實 registry 必須是綠的（這條逼第 6 步的 baseline 重生真的落地）
#
# 設計紀律：
#   - 1-4 全部在 mktemp 沙盒裡跑（docs_lint.sh:37 是 `cd $(git rev-parse --show-toplevel)`，
#     指向一個 throwaway `git init` 目錄就能完全改道）。**不動任何 tracked 檔、不碰 index**，
#     所以也不需要 cp 備份還原——沒有東西被擾動。
#   - 每條斷言都 grep docs_lint 的**輸出檔**，不 grep 本腳本自己的 echo。
#   - 不用 test_docs_lint.sh 的 run_capture（它 rc!=0 就 exit，無法表達「必須失敗」），
#     改用 test_script_help.sh:32-40 的 assert_rc idiom。

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMPDIR="$(mktemp -d -t kg_gen_check_XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

pass=0; fail=0
ok()      { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t()  { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

dump_file() {
  echo "      ---- $1 ----" >&2
  if [ -f "$1" ]; then sed 's/^/      /' "$1" >&2; else echo "      (missing)" >&2; fi
}

assert_rc() {
  local name="$1" expected="$2" got="$3" logfile="$4"
  if [ "$got" = "$expected" ]; then
    ok "$name (rc=$got)"
  else
    fail_t "$name expect rc=$expected got rc=$got"
    dump_file "$logfile"
  fi
}

assert_log_contains() {
  local name="$1" needle="$2" logfile="$3"
  if grep -qF -- "$needle" "$logfile"; then
    ok "$name contains \"$needle\""
  else
    fail_t "$name missing \"$needle\""
    dump_file "$logfile"
  fi
}

# build_sandbox <dir> <probe-content> <declare-check:yes|no> <after-entry-kind>
#
# 沙盒 registry 刻意有 **兩** 筆 entry：generated.probe 之後還有一筆非 generated 的
# reference.after。那筆不是填充物，是 stdin canary 的本體——沒有它，「entry 有沒有被
# 吃掉」這個斷言就是空的。
build_sandbox() {
  local sb="$1" probe_content="$2" declare_check="$3" after_kind="$4"
  mkdir -p "$sb/docs/snapshot" "$sb/ops"
  git -C "$sb" init -q

  printf '%s\n' "$probe_content" > "$sb/docs/snapshot/probe.md"
  printf 'after\n' > "$sb/docs/snapshot/after.md"

  cat > "$sb/ops/fake_gen.sh" << 'FAKEGEN'
#!/usr/bin/env bash
# 沙盒專用的假 generator。
# 它**故意先讀 stdin**：這就是 docs_lint.sh 那個 `</dev/null` 的探針。少了那個重導向，
# 這行 cat 會吞掉外層 while-loop 尚未讀取的 registry entry，entry_count 無聲減少而 rc 照樣 0。
cat > /dev/null 2>&1 || true
if [ "${1:-}" = "--check" ]; then
  if [ "$(cat docs/snapshot/probe.md)" = "hello" ]; then
    echo "docs/snapshot/probe.md is up to date."
    exit 0
  fi
  echo "STALE docs/snapshot/probe.md"
  exit 1
fi
echo hello
FAKEGEN
  chmod +x "$sb/ops/fake_gen.sh"

  {
    echo "documents:"
    echo "  - id: generated.probe"
    echo "    path: docs/snapshot/probe.md"
    echo "    kind: generated"
    echo "    authority: generated"
    echo "    generator: ops/fake_gen.sh"
    [ "$declare_check" = "yes" ] && echo "    check: ./ops/fake_gen.sh --check"
    echo "    triggers:"
    echo "      - probe_changed"
    echo "  - id: reference.after"
    echo "    path: docs/snapshot/after.md"
    echo "    kind: $after_kind"
    echo "    authority: reference"
    echo "    triggers:"
    echo "      - after_changed"
  } > "$sb/docs/registry.yml"
}

# run_lint <sandbox-dir> <logfile> ; echoes rc
run_lint() {
  local sb="$1" log="$2" rc
  ( cd "$sb" && "$ROOT/ops/docs_lint.sh" --registry ) > "$log" 2>&1
  rc=$?
  echo "$rc"
}

# ── 1. 產物 == generator 輸出 → 綠 ─────────────────────────────────────────
section "green when product == generator output"
SB1="$TMPDIR/sb1"
build_sandbox "$SB1" "hello" yes reference
LOG1="$TMPDIR/case1.out"
RC1="$(run_lint "$SB1" "$LOG1")"
assert_rc "clean generated entry" 0 "$RC1" "$LOG1"
# 這行同時是 stdin canary 的正例：check 命令吃了 stdin 的話會變成 "1 documents"。
assert_log_contains "clean run" "REGISTRY OK: 2 documents" "$LOG1"

# ── 2. 產物 drift → 紅，且具名 ────────────────────────────────────────────
section "red when product drifted"
SB2="$TMPDIR/sb2"
build_sandbox "$SB2" "hello" yes reference
printf 'drifted\n' >> "$SB2/docs/snapshot/probe.md"
LOG2="$TMPDIR/case2.out"
RC2="$(run_lint "$SB2" "$LOG2")"
assert_rc "drifted product" 1 "$RC2" "$LOG2"
assert_log_contains "drifted product" \
  "ERROR registry — generated.probe 產物與 generator 輸出不一致" "$LOG2"

# ── 3. kind=generated 但沒宣告 check: → 紅 ────────────────────────────────
section "red when kind=generated declares no check:"
SB3="$TMPDIR/sb3"
build_sandbox "$SB3" "hello" no reference
LOG3="$TMPDIR/case3.out"
RC3="$(run_lint "$SB3" "$LOG3")"
assert_rc "generated without check" 1 "$RC3" "$LOG3"
# 訊息刻意與既有的「但缺 generator」不同字串，否則這個 grep 會被舊訊息滿足。
assert_log_contains "generated without check" \
  "ERROR registry — generated.probe kind=generated 但缺 check" "$LOG3"

# ── 4. stdin canary：check 失敗時後續 entry 仍須被讀到 ─────────────────────
section "stdin canary — entries after a failing check are still read"
SB4="$TMPDIR/sb4"
build_sandbox "$SB4" "hello" yes bogus_kind
printf 'drifted\n' >> "$SB4/docs/snapshot/probe.md"
LOG4="$TMPDIR/case4.out"
RC4="$(run_lint "$SB4" "$LOG4")"
assert_rc "canary sandbox" 1 "$RC4" "$LOG4"
assert_log_contains "canary" \
  "ERROR registry — generated.probe 產物與 generator 輸出不一致" "$LOG4"
# 少了 `</dev/null`，reference.after 會被 fake_gen 的 cat 吞掉，下面這行就永遠不會出現。
assert_log_contains "canary (entry after the check survived)" \
  "ERROR registry — reference.after 非法 kind: bogus_kind" "$LOG4"

# ── 5. 真實 registry 必須綠 ───────────────────────────────────────────────
# 沙盒證明機制對，這條證明機制套在真檔上是綠的——也就是那份腐爛 250 個 commit 的
# ios_baseline 真的被重生過了。純唯讀，不動任何檔。
section "real registry is green"
LOG5="$TMPDIR/case5.out"
( cd "$ROOT" && ./ops/docs_lint.sh --registry ) > "$LOG5" 2>&1
RC5=$?
assert_rc "real registry" 0 "$RC5" "$LOG5"
assert_log_contains "real registry" "REGISTRY OK" "$LOG5"
assert_log_contains "real registry" "ERROR: 0" "$LOG5"

echo ""
echo "─────────────────────────────────────"
echo "PASS: $pass  FAIL: $fail"
echo "─────────────────────────────────────"
[ "$fail" -eq 0 ] || exit 1
echo "PASS test_docs_lint_generated_check"
