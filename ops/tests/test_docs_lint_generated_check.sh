#!/usr/bin/env bash
# test_docs_lint_generated_check.sh — IMP-20260805-462d28：generated 文檔的等值 gate
#
# 守的是什麼：docs/registry.yml 的 `generator:` 是全 registry 唯一宣告了「可機器檢查
# 關係」的欄位，但 docs_lint.sh 從來只驗「generator 欄非空 + 該檔存在」。產物與產生器
# 輸出的關係從未被評估，所以一份 generated 文檔可以腐爛到面目全非而 gate 照樣回綠。
# 本測試釘住：
#   1. 產物 == generator 輸出 → rc=0
#   2. 產物 drift            → rc=1，且**具名該筆 entry**
#   3. kind=generated 卻沒宣告 check: → rc=1（洞由構造關上，不靠記得）
#   4. stdin canary：check 命令若吃掉 stdin，後續 registry entry 會無聲消失
#   5. check: 沒指名自己的 path → rc=1（`check: true` 與「複製鄰居的 check」都被擋）
#   6. 真實 registry 是綠的
#   7. **真實的 check: 仍然「有能力變紅」** —— 逐筆 kind=generated entry 真的把產物弄髒，
#      要求 docs_lint 具名那筆 entry 轉紅，然後從備份還原。
#
# 為什麼要有 7（review D1）：1-5 全部跑在沙盒裡，用的是本測試自己寫的假 generator；6 是
# 純綠色斷言。三者加起來仍然無法察覺「真實的 check 變成裝飾品」——把 registry 的 check:
# 換成一條永遠回 0 的命令，整份測試照樣全綠，而 gate 已經死了。一個失敗路徑沒被測過的
# gate，是靠信仰在信任。7 是唯一會因此轉紅的東西。
#
# 2026-08-08（IMP-20260808-b63206）起，真實 registry 的 kind=generated entry 數是 **0**
# （唯一那筆 generated.ios_baseline 隨產物移出版控而刪除），所以 7 今天跑 0 圈。這件事在
# 7 裡是**具名申報**而不是靜默跳過，理由寫在那一段旁邊。要強調的是規則本身沒有因此失守：
# 1-5 的素材全是 build_sandbox 現造的合成 entry，刪掉真實 entry 後逐條仍轉紅（實測）。
#
# 設計紀律：
#   - 1-5 全部在 mktemp 沙盒裡跑（docs_lint.sh:37 是 `cd $(git rev-parse --show-toplevel)`，
#     指向一個 throwaway `git init` 目錄就能完全改道）。**不動任何 tracked 檔、不碰 index**。
#   - 7 必須動真實 tracked 產物（那就是被測的東西）。還原走**本測試自己 cp 的備份**，
#     trap 在任何離開路徑上都會跑；**不用 git checkout / git stash**（會碰 index，這裡是真 repo）。
#     還原後用 cmp 逐 byte 驗，並要求 registry 重新回綠——「還原了」是量到的，不是宣稱的。
#   - 每條斷言都 grep docs_lint 的**輸出檔**，不 grep 本腳本自己的 echo。
#   - 不用 test_docs_lint.sh 的 run_capture（它 rc!=0 就 exit，無法表達「必須失敗」），
#     改用 test_script_help.sh:32-40 的 assert_rc idiom。

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMPDIR="$(mktemp -d -t kg_gen_check_XXXXXX)"
RESTORE_MANIFEST="$TMPDIR/restore.manifest"
: > "$RESTORE_MANIFEST"

# 還原優先於清理：備份檔就住在 TMPDIR 裡，順序反了就永久失去 tracked 檔的原內容。
cleanup() {
  local rc=$?
  if [ -s "$RESTORE_MANIFEST" ]; then
    while IFS="$(printf '\t')" read -r bak orig; do
      [ -n "$bak" ] || continue
      if [ -f "$bak" ]; then
        cp "$bak" "$orig"
        echo "  [cleanup] restored $orig"
      else
        echo "  [cleanup] !! backup missing for $orig ($bak)" >&2
      fi
    done < "$RESTORE_MANIFEST"
  fi
  rm -rf "$TMPDIR"
  exit $rc
}
trap cleanup EXIT INT TERM

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

# build_sandbox <dir> <probe-content> <check-mode: yes|no|nopath|truthy> <after-entry-kind>
#
# 沙盒 registry 刻意有 **兩** 筆 entry：generated.probe 之後還有一筆非 generated 的
# reference.after。那筆不是填充物，是 stdin canary 的本體——沒有它，「entry 有沒有被
# 吃掉」這個斷言就是空的。
build_sandbox() {
  local sb="$1" probe_content="$2" check_mode="$3" after_kind="$4"
  mkdir -p "$sb/docs/snapshot" "$sb/ops"
  git -C "$sb" init -q

  printf '%s\n' "$probe_content" > "$sb/docs/snapshot/probe.md"
  printf 'after\n' > "$sb/docs/snapshot/after.md"
  # 鄰居的產物，內容刻意是乾淨值 hello：拿它當 check 目標的話命令會 **exit 0**。
  # 這讓「複製鄰居的 check」這個 case 只可能被新規則判紅，不可能被 drift 錯誤矇到。
  printf 'hello\n' > "$sb/docs/snapshot/neighbour.md"

  cat > "$sb/ops/fake_gen.sh" << 'FAKEGEN'
#!/usr/bin/env bash
# 沙盒專用的假 generator。產物路徑由 $2 傳入（真 registry 的 check: 也必須指名 path，
# 見 docs_lint.sh 的「check 未指名 path」規則），所以這裡也照著吃那個參數。
# 它**故意先讀 stdin**：這就是 docs_lint.sh 那個 `</dev/null` 的探針。少了那個重導向，
# 這行 cat 會吞掉外層 while-loop 尚未讀取的 registry entry，entry_count 無聲減少而 rc 照樣 0。
cat > /dev/null 2>&1 || true
if [ "${1:-}" = "--check" ]; then
  target="${2:-docs/snapshot/probe.md}"
  if [ "$(cat "$target")" = "hello" ]; then
    echo "$target is up to date."
    exit 0
  fi
  echo "STALE $target"
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
    case "$check_mode" in
      yes)
        echo "    check: ./ops/fake_gen.sh --check docs/snapshot/probe.md"
        ;;
      nopath)
        # 「從鄰居 entry 複製過來的 check」：合法命令、**exit 0**、檢查的是別人的產物。
        echo "    check: ./ops/fake_gen.sh --check docs/snapshot/neighbour.md"
        ;;
      truthy)
        # reviewer 舉的最小反例：`check: true` 在舊規則（非空 + 回 0）下完全通過。
        echo "    check: true"
        ;;
      no) ;;
      *) echo "internal error: bad check_mode $check_mode" >&2; exit 2 ;;
    esac
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

# build_multi_sandbox <dir>
#
# §7 專用：**兩** 筆 kind=generated entry（各自的產物、各自 check 指名自己的 path）＋一筆
# 非 generated。兩筆不是湊數——迴圈提早 break 或列舉器只吐第一筆，只有 N≥2 才看得出來。
# 產物內容用不同的乾淨值，這樣「弄髒 A 卻報 B」這種串線也會被具名斷言抓到。
build_multi_sandbox() {
  local sb="$1"
  mkdir -p "$sb/docs/snapshot" "$sb/ops"
  git -C "$sb" init -q

  printf 'alpha\n' > "$sb/docs/snapshot/probe_a.md"
  printf 'bravo\n' > "$sb/docs/snapshot/probe_b.md"
  printf 'after\n' > "$sb/docs/snapshot/after.md"

  # 假 generator：產物路徑與期望值都由參數傳入，所以同一支能服務兩筆 entry。
  # 一樣先讀 stdin（docs_lint.sh 那個 `</dev/null` 的探針，見 §4）。
  cat > "$sb/ops/fake_gen_multi.sh" << 'FAKEGENMULTI'
#!/usr/bin/env bash
cat > /dev/null 2>&1 || true
if [ "${1:-}" = "--check" ]; then
  target="${2:?target required}"
  expected="${3:?expected required}"
  if [ "$(cat "$target")" = "$expected" ]; then
    echo "$target is up to date."
    exit 0
  fi
  echo "STALE $target"
  exit 1
fi
echo "${1:-alpha}"
FAKEGENMULTI
  chmod +x "$sb/ops/fake_gen_multi.sh"

  {
    echo "documents:"
    echo "  - id: generated.probe_a"
    echo "    path: docs/snapshot/probe_a.md"
    echo "    kind: generated"
    echo "    authority: generated"
    echo "    generator: ops/fake_gen_multi.sh"
    echo "    check: ./ops/fake_gen_multi.sh --check docs/snapshot/probe_a.md alpha"
    echo "    triggers:"
    echo "      - probe_a_changed"
    echo "  - id: generated.probe_b"
    echo "    path: docs/snapshot/probe_b.md"
    echo "    kind: generated"
    echo "    authority: generated"
    echo "    generator: ops/fake_gen_multi.sh"
    echo "    check: ./ops/fake_gen_multi.sh --check docs/snapshot/probe_b.md bravo"
    echo "    triggers:"
    echo "      - probe_b_changed"
    echo "  - id: reference.after"
    echo "    path: docs/snapshot/after.md"
    echo "    kind: reference"
    echo "    authority: reference"
    echo "    triggers:"
    echo "      - after_changed"
  } > "$sb/docs/registry.yml"
}

# run_lint <sandbox-dir> <logfile> ; echoes rc
run_lint() {
  local sb="$1" log="$2" rc
  ( cd "$sb" && "$ROOT/ops/docs_lint.sh" --registry ) > "$log" 2>&1 </dev/null
  rc=$?
  echo "$rc"
}

# run_real_lint <logfile> ; echoes rc（真 repo，唯讀）
run_real_lint() {
  local log="$1" rc
  ( cd "$ROOT" && ./ops/docs_lint.sh --registry ) > "$log" 2>&1 </dev/null
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

# ── 5. check: 沒指名自己的 path → 紅（review D2）──────────────────────────
# 這裡的 check 是**合法命令、今天 exit 0**，只是檢查的是別人的檔。舊規則（非空 + 回 0）
# 會放行；`check: true` 也會放行。沙盒產物是乾淨的，所以「不一致」那條錯誤不會出現，
# 這個 case 只能由新規則滿足。
section "red when check: does not name its own path"
for mode in nopath truthy; do
  SB5="$TMPDIR/sb5_$mode"
  build_sandbox "$SB5" "hello" "$mode" reference
  LOG5="$TMPDIR/case5_$mode.out"
  RC5="$(run_lint "$SB5" "$LOG5")"
  assert_rc "check[$mode] not naming path" 1 "$RC5" "$LOG5"
  assert_log_contains "check[$mode] not naming path" \
    "ERROR registry — generated.probe check 未指名 path" "$LOG5"
  # 反證：不能是被「產物不一致」那條錯誤滿足的。沙盒產物是乾淨的、兩種 check 都 exit 0，
  # 所以那條錯誤根本不該出現；它若出現，代表這個 case 在測別的東西（同形 token 假綠）。
  if grep -qF -- "generated.probe 產物與 generator 輸出不一致" "$LOG5"; then
    fail_t "check[$mode] not naming path — 被不相干的 drift 錯誤滿足了（沙盒產物應該是乾淨的）"
    dump_file "$LOG5"
  else
    ok "check[$mode] not naming path (verdict came from the path rule, not from a drift error)"
  fi
done

# ── 6. 真實 registry 必須綠 ───────────────────────────────────────────────
section "real registry is green"
LOG6="$TMPDIR/case6.out"
RC6="$(run_real_lint "$LOG6")"
assert_rc "real registry" 0 "$RC6" "$LOG6"
assert_log_contains "real registry" "REGISTRY OK" "$LOG6"
assert_log_contains "real registry" "ERROR: 0" "$LOG6"

# ── 7. 逐筆 drift 施壓：合成 registry（永遠有素材）＋ 真實 registry（有才加碼）──
# 這一節原本只跑**真實** registry 的 kind=generated entry。2026-08-08（IMP-20260808-b63206）
# 唯一那筆隨產物移出版控而刪除，於是它退化成零實例——而一個沒有素材的反空轉守衛只剩
# 兩條路：恆紅（擋住一個正確的狀態）或恆綠（變成空話）。兩條都不能要，尤其不能在一張
# 「拆掉空話守衛」的票裡順手製造另一個空話守衛。
#
# 解法比照本檔 §1-§5：**自帶合成 entry**。這一節真正在守的機械是「多筆列舉 + 逐筆弄髒 +
# 逐筆具名轉紅 + 逐筆還原」，它必須每次都被跑到，而不是「repo 裡剛好還有一個真實實例」
# 才被跑到——那個前提會消失，而且已經消失過一次。
# 真實 registry 的 live-fire 仍在（下半節），但它是**加碼**：有素材才跑，沒素材不計分、
# 不宣稱、也不擋。

# 兩個呼叫點（合成 / 真實）共用同一支列舉器。分成兩份 awk 的話，合成那邊測到的就不是
# 真實路徑上跑的那支，這一節的合成化就會變成自我安慰。
enumerate_generated() {  # $1 = registry path -> stdout: "<id>\t<path>" per kind=generated entry
  awk '
    function flush() { if (id != "" && kind == "generated") print id "\t" path }
    /^  - id:[[:space:]]*/ {
      flush()
      id=$0; sub(/^  - id:[[:space:]]*/, "", id)
      path=""; kind=""
      next
    }
    id != "" && /^    path:[[:space:]]*/ { path=$0; sub(/^    path:[[:space:]]*/, "", path); next }
    id != "" && /^    kind:[[:space:]]*/ { kind=$0; sub(/^    kind:[[:space:]]*/, "", kind); next }
    END { flush() }
  ' "$1"
}

# drift_loop <root> <list-tsv> <label>
# 逐筆：備份 → 弄髒產物 → 要求 docs_lint 具名那筆 entry 轉紅 → 還原 → cmp 驗 byte 相同。
# fd 3：不讓迴圈的 stdin 被任何子命令吃掉（§4 守的就是這個失效模式）。
drift_loop() {
  local root="$1" list="$2" label="$3"
  local gid gpath artifact bak slug LOGD RCD
  while IFS="$(printf '\t')" read -r gid gpath <&3; do
    [ -n "$gid" ] || continue
    artifact="$root/$gpath"
    if [ ! -f "$artifact" ]; then
      fail_t "[$label] $gid — 產物不存在: $gpath"
      continue
    fi
    slug="$(echo "${label}_${gid}" | tr '/.' '__')"
    bak="$TMPDIR/${slug}.bak"
    cp "$artifact" "$bak"
    # 只有真實 repo 的檔要進還原清單；沙盒是拋棄式的，登記它只會讓 cleanup 噪音變多。
    [ "$root" = "$ROOT" ] && printf '%s\t%s\n' "$bak" "$artifact" >> "$RESTORE_MANIFEST"

    printf 'KG-DRIFT-PROBE-%s\n' "$$" >> "$artifact"
    LOGD="$TMPDIR/drift_${slug}.out"
    RCD="$(run_lint "$root" "$LOGD")"
    assert_rc "[$label] $gid drifted artifact" 1 "$RCD" "$LOGD"
    assert_log_contains "[$label] $gid drifted artifact" \
      "ERROR registry — $gid 產物與 generator 輸出不一致" "$LOGD"

    cp "$bak" "$artifact"
    if cmp -s "$bak" "$artifact"; then
      ok "[$label] $gid restored byte-identical from the test's own cp backup"
    else
      fail_t "[$label] $gid RESTORE FAILED — $gpath 與備份不同，請手動還原: cp $bak $artifact"
    fi
  done 3< "$list"
}

section "drift loop bites, on a synthetic registry that always has subjects"
# 刻意放 **兩** 筆 generated entry：一筆只證明迴圈跑得動，兩筆才證明它「逐筆」跑——
# 迴圈提早 break、或列舉器只吐第一筆，都只有在 N≥2 時才看得出來。
SB7="$TMPDIR/sb7"
build_multi_sandbox "$SB7"
GEN_LIST_SYNTH="$TMPDIR/generated_entries_synth.tsv"
enumerate_generated "$SB7/docs/registry.yml" > "$GEN_LIST_SYNTH"
synth_parsed=$(wc -l < "$GEN_LIST_SYNTH" | tr -d ' ')
# 反空轉守衛：用一個獨立的量法（直接數 registry 的 kind 行）交叉核對列舉器。
synth_declared=$(grep -c '^    kind: generated$' "$SB7/docs/registry.yml" | tr -d ' ')
if [ "$synth_parsed" = "$synth_declared" ] && [ "$synth_parsed" -eq 2 ]; then
  ok "enumerated $synth_parsed synthetic kind=generated entries (matches the sandbox registry's own count)"
else
  fail_t "synthetic enumeration is wrong: parsed=$synth_parsed declared=$synth_declared (本節自己造的沙盒剛好有 2 筆，對不上就是列舉器壞了)"
fi
# 沙盒起手必須是綠的，否則下面每一條紅色都可能是別的原因造成的。
LOG7C="$TMPDIR/case7_clean.out"
RC7C="$(run_lint "$SB7" "$LOG7C")"
assert_rc "synthetic sandbox is green before any drift" 0 "$RC7C" "$LOG7C"
drift_loop "$SB7" "$GEN_LIST_SYNTH" "synthetic"
LOG7R="$TMPDIR/case7_restored.out"
RC7R="$(run_lint "$SB7" "$LOG7R")"
assert_rc "synthetic sandbox is green again after restore" 0 "$RC7R" "$LOG7R"

section "real registry: live-fire on whatever generated entries exist today (加碼，非必要條件)"
GEN_LIST="$TMPDIR/generated_entries.tsv"
enumerate_generated "$ROOT/docs/registry.yml" > "$GEN_LIST"
gen_parsed=$(wc -l < "$GEN_LIST" | tr -d ' ')
gen_declared=$(grep -c '^    kind: generated$' "$ROOT/docs/registry.yml" | tr -d ' ')
if [ "$gen_parsed" != "$gen_declared" ]; then
  fail_t "generated-entry enumeration mismatch on the REAL registry: parsed=$gen_parsed declared=$gen_declared — 兩個獨立量法不一致，代表列舉器壞了"
elif [ "$gen_parsed" -eq 0 ]; then
  # 刻意**不**記 ok：沒有素材就沒有驗到東西，計分等於宣稱。上面那節才是這條規則的保證。
  echo "  · real registry declares 0 kind=generated entries — nothing to live-fire (覆蓋由上一節的合成 entry 承擔，不計分)"
else
  ok "enumerated $gen_parsed real kind=generated entries (matches registry's own count)"
  drift_loop "$ROOT" "$GEN_LIST" "real"
fi

# ── 8. 還原後真實 registry 必須重新回綠 ───────────────────────────────────
# 這條有兩個作用：證明 7 沒有留下殘骸，也證明 7 的紅色確實是那個 drift 造成的
# （而不是這棵樹本來就紅）。
section "real registry is green again after restore"
LOG8="$TMPDIR/case8.out"
RC8="$(run_real_lint "$LOG8")"
assert_rc "real registry after restore" 0 "$RC8" "$LOG8"
assert_log_contains "real registry after restore" "ERROR: 0" "$LOG8"

echo ""
echo "─────────────────────────────────────"
echo "PASS: $pass  FAIL: $fail"
echo "─────────────────────────────────────"
[ "$fail" -eq 0 ] || exit 1
echo "PASS test_docs_lint_generated_check"
