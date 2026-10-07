#!/usr/bin/env bash
# test_docs_lint_source_existence.sh — #2066：registry source hint 的存在性 gate
#
# 守的是什麼：docs/registry.yml 的 `sources:` 是 docs_impact.py 判斷「改了哪個 path 要
# 同步哪份文件」的唯一依據。一個不命中任何 path 的 source 是死的——impact 永遠不會因它
# 觸發，文件就無聲失去同步訊號（#2066 實測 11 份文件含死 source，其中兩份完全沒有活
# source）。舊 gate 只驗 entry 的 `path:` 存在，`sources:` 從未被評估。
#
# 判準刻意與 impact 引擎**同一支** `source_matches`：問的不是「磁碟上有沒有這個東西」，
# 而是「有沒有任何 path 能讓 impact 命中它」。兩者不同的實例就在 registry 裡：
# `.claude/skills/podcast-*/` 的目錄存在，但舊引擎把結尾 `/` 的 glob 當成「path 本身
# 要以 / 結尾」，永遠不命中任何檔案。
#
# path 宇宙 = tracked ∪ 未被忽略的新檔 − 已在工作樹刪除的 tracked 檔，與 impact 的
# changed-path 宇宙一致：同一個變更裡新增 source 檔＋登錄 registry 不會被誤判，
# 被 ignore 的產物與已刪檔不能讓死 source 假活。CI checkout 沒有新檔，等於 tracked-only。
#
# 設計紀律（比照 test_docs_lint_generated_check.sh）：
#   - 沙盒全是 mktemp + `git init` 的拋棄式 repo，不動任何 tracked 檔、不碰真 repo index。
#   - 每條斷言 grep docs_lint 的輸出檔，且具名 entry id 與 source。
#   - 失敗路徑（tool 跑不起來、tool 回 0 卻沒有結果）各有一條必須轉紅的 case。

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DOCS_LINT_BLOCK_RC=2
DOCS_LINT_TOOL_RC=1
TMPDIR="$(mktemp -d -t kg_src_exist_XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT INT TERM

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

assert_log_lacks() {
  local name="$1" needle="$2" logfile="$3"
  if grep -qF -- "$needle" "$logfile"; then
    fail_t "$name unexpectedly contains \"$needle\""
    dump_file "$logfile"
  else
    ok "$name lacks \"$needle\""
  fi
}

# build_sandbox <dir> <extra-source>...
#
# reference.live 的 source 覆蓋 registry 實際使用的四種形狀（exact／目錄／glob／
# 結尾 / 的 glob 目錄）加一條指向不存在 path 的 `!` 排除（排除不要求存在）。
# reference.probe 只放呼叫端給的 source，讓每個 case 的紅色只可能來自那一條。
build_sandbox() {
  local sb="$1"; shift
  local src
  mkdir -p "$sb/docs" "$sb/src" "$sb/ops" "$sb/skills/pod-pipeline"
  git -C "$sb" init -q
  printf 'live\n' > "$sb/docs/live.md"
  printf 'probe\n' > "$sb/docs/probe.md"
  printf 'print(1)\n' > "$sb/src/app.py"
  printf 'print(2)\n' > "$sb/ops/_i18n_extract_keys.py"
  printf 'skill\n' > "$sb/skills/pod-pipeline/SKILL.md"
  printf 'build/\n' > "$sb/.gitignore"
  {
    echo "documents:"
    echo "  - id: reference.live"
    echo "    path: docs/live.md"
    echo "    kind: reference"
    echo "    authority: SoT"
    echo "    triggers:"
    echo "      - live-changed"
    echo "    sources:"
    echo "      - src/app.py"
    echo "      - src/"
    echo "      - ops/_i18n_*.py"
    echo "      - skills/pod-*/"
    echo "      - \"!ghost-excluded/\""
    echo "  - id: reference.probe"
    echo "    path: docs/probe.md"
    echo "    kind: reference"
    echo "    authority: SoT"
    echo "    triggers:"
    echo "      - probe-changed"
    if [ "$#" -gt 0 ]; then
      echo "    sources:"
      for src in "$@"; do echo "      - $src"; done
    fi
  } > "$sb/docs/registry.yml"
  git -C "$sb" add -A
}

# run_lint <sandbox-dir> <logfile> ; echoes rc
run_lint() {
  local sb="$1" log="$2" rc
  ( cd "$sb" && "$ROOT/ops/docs_lint.sh" --registry ) > "$log" 2>&1 </dev/null
  rc=$?
  echo "$rc"
}

# ── 1. 四種活 source 形狀 → 綠 ────────────────────────────────────────────
section "green when every non-! source hits a path"
SB1="$TMPDIR/sb1"
build_sandbox "$SB1" "src/app.py"
LOG1="$TMPDIR/case1.out"
RC1="$(run_lint "$SB1" "$LOG1")"
assert_rc "live sources" 0 "$RC1" "$LOG1"
assert_log_contains "live sources" "REGISTRY OK: 2 documents" "$LOG1"
# 結尾 / 的 glob 是舊引擎的盲點：目錄在，impact 卻永不命中。
assert_log_lacks "glob directory source" "skills/pod-*/" "$LOG1"
# `!` 排除指向不存在的 path 不是死 source。
assert_log_lacks "exclusion source" "ghost-excluded" "$LOG1"

# ── 2. 死 source 的三種形狀 → 紅且具名 ────────────────────────────────────
section "red and named for each dead source shape"
case_dead() {
  local label="$1" source="$2" sb log rc
  sb="$TMPDIR/sb_dead_$label"
  build_sandbox "$sb" "$source"
  log="$TMPDIR/case_dead_$label.out"
  rc="$(run_lint "$sb" "$log")"
  assert_rc "dead $label source" "$DOCS_LINT_BLOCK_RC" "$rc" "$log"
  assert_log_contains "dead $label source" \
    "ERROR registry — reference.probe source 未命中任何 path: $source" "$log"
  # 反證：紅色只能來自 probe 那一條，live entry 不得被連坐。
  assert_log_lacks "dead $label source" "reference.live source" "$log"
}
case_dead exact "src/missing.py"
case_dead dir "ghost/"
# #2066 的原始形狀：glob 指向改名前的前綴（實檔是 `_i18n_`）。
case_dead glob "ops/i18n_*.py"

# ── 3. path 宇宙的邊界 ───────────────────────────────────────────────────
section "untracked-but-not-ignored file is live (same-change registration)"
SB3="$TMPDIR/sb3"
build_sandbox "$SB3" "src/new_module.py"
printf 'print(3)\n' > "$SB3/src/new_module.py"
LOG3="$TMPDIR/case3.out"
RC3="$(run_lint "$SB3" "$LOG3")"
assert_rc "untracked new file" 0 "$RC3" "$LOG3"

section "ignored file does not keep a source alive"
SB4="$TMPDIR/sb4"
build_sandbox "$SB4" "build/"
mkdir -p "$SB4/build"
printf 'artifact\n' > "$SB4/build/out.txt"
LOG4="$TMPDIR/case4.out"
RC4="$(run_lint "$SB4" "$LOG4")"
assert_rc "ignored artifact" "$DOCS_LINT_BLOCK_RC" "$RC4" "$LOG4"
assert_log_contains "ignored artifact" \
  "ERROR registry — reference.probe source 未命中任何 path: build/" "$LOG4"

section "tracked file deleted in the worktree does not keep a source alive"
SB5="$TMPDIR/sb5"
build_sandbox "$SB5" "src/legacy.py"
printf 'print(4)\n' > "$SB5/src/legacy.py"
git -C "$SB5" add src/legacy.py
rm "$SB5/src/legacy.py"
LOG5="$TMPDIR/case5.out"
RC5="$(run_lint "$SB5" "$LOG5")"
assert_rc "deleted tracked file" "$DOCS_LINT_BLOCK_RC" "$RC5" "$LOG5"
assert_log_contains "deleted tracked file" \
  "ERROR registry — reference.probe source 未命中任何 path: src/legacy.py" "$LOG5"

# ── 4. 檢查本身失效必須 fail closed ──────────────────────────────────────
section "source check that cannot run is a tool failure, not REGISTRY OK"
FAKE_FAIL="$TMPDIR/fake_impact_fail.sh"
printf '#!/usr/bin/env bash\necho "boom" >&2\nexit 1\n' > "$FAKE_FAIL"
FAKE_SILENT="$TMPDIR/fake_impact_silent.sh"
printf '#!/usr/bin/env bash\nexit 0\n' > "$FAKE_SILENT"
chmod +x "$FAKE_FAIL" "$FAKE_SILENT"
for fake in fail silent; do
  SB6="$TMPDIR/sb6_$fake"
  build_sandbox "$SB6" "src/app.py"
  LOG6="$TMPDIR/case6_$fake.out"
  if [ "$fake" = fail ]; then bin="$FAKE_FAIL"; else bin="$FAKE_SILENT"; fi
  ( cd "$SB6" && KG_DOCS_IMPACT_BIN="$bin" "$ROOT/ops/docs_lint.sh" --registry ) > "$LOG6" 2>&1 </dev/null
  RC6=$?
  assert_rc "source check tool[$fake]" "$DOCS_LINT_TOOL_RC" "$RC6" "$LOG6"
  assert_log_contains "source check tool[$fake]" "source 存在性檢查無法執行" "$LOG6"
  assert_log_lacks "source check tool[$fake]" "REGISTRY OK" "$LOG6"
done

# ── 5. 真實 registry 必須綠 ───────────────────────────────────────────────
section "real registry has no dead source"
LOG7="$TMPDIR/case7.out"
( cd "$ROOT" && ./ops/docs_lint.sh --registry ) > "$LOG7" 2>&1 </dev/null
RC7=$?
assert_rc "real registry" 0 "$RC7" "$LOG7"
assert_log_contains "real registry" "REGISTRY OK" "$LOG7"
assert_log_lacks "real registry" "source 未命中任何 path" "$LOG7"

echo ""
echo "─────────────────────────────────────"
echo "PASS: $pass  FAIL: $fail"
echo "─────────────────────────────────────"
[ "$fail" -eq 0 ] || exit 1
echo "PASS test_docs_lint_source_existence"
