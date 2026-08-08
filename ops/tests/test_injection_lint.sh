#!/usr/bin/env bash
# Offline regression tests for ops/injection_lint.sh — 三件事：
#   1. baseline sunset 執法（原有）
#   2. 掃描與 baseline 解析對 **repo** 錨定，不跟著呼叫者的 cwd（IMP-20260807-1674d1）
#   3. 掃到零個檔案必須 fail closed，不可讀成「乾淨」（同上）
#
# 為什麼存在（1）：baseline 的 `# sunset:` 原本只在過期時印一行 WARN 到 stderr，
# 然後照樣 `return 0`。也就是「這批債務的寬限期到了」這個事實**不會改變任何
# gate 的顏色**。2026-08-03 實測：sunset 已過期 21 天，CI / cutover / 本機
# 全部照樣綠，沒有任何人知道。
#
# 過期必須是紅的，否則 sunset 只是一句沒有後果的註解。
#
# 為什麼存在（2、3）：injection_lint 的 baseline 同時餵 cutover 的 block gate 與
# pre-commit hook，兩者都繼承呼叫端環境。模組常數對 cwd 解析時有兩種災情形狀：
# 站在 repo 外 → Views 找不到 → 全部掃不到；站在一個放著寬鬆 baseline 的目錄
# → 讀到那份、放行一切。第二種在 ops/backlog.py 上實際發生過（2026-08-07 修）。
# 而「掃到零個檔案」本身在修前是 exit 0 + `OK — no findings.`。

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd -P)"   # -P: 模組常數走 Path.resolve(),
                                                       # 邏輯路徑會在含 symlink 的 checkout 上假紅
cd "$WORKSPACE"
LINT="$WORKSPACE/ops/injection_lint.sh"

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# A baseline holding exactly today's findings, so nothing reads as a regression
# and the only variable under test is the sunset header.
CURRENT_FINDINGS="$TMP/current.txt"
"$LINT" --report 2>/dev/null | grep -E '^ios/.*\.swift' >"$CURRENT_FINDINGS" || true

write_baseline() {  # $1 = destination, $2 = sunset line (empty = omit header)
  local dest="$1" sunset_line="$2"
  {
    echo "# injection_lint baseline — synthesized by test_injection_lint.sh"
    [[ -n "$sunset_line" ]] && echo "$sunset_line"
    echo ""
    cat "$CURRENT_FINDINGS"
  } >"$dest"
}

run_check() {  # $1 = baseline path -> echoes exit code
  local rc=0
  KG_INJECTION_BASELINE="$1" "$LINT" --baseline-check >/dev/null 2>&1 || rc=$?
  echo "$rc"
}

section "baseline path is overridable (siblings already are)"
# Discriminating probe: an EMPTY baseline must read as a regression. A passing
# result here would mean the override was ignored and the real (passing)
# baseline answered instead — the probe has to be able to fail for the right
# reason, or every later assertion in this file is vacuous.
write_baseline "$TMP/empty.txt" "# sunset: 2099-01-01"
: >"$TMP/empty-findings.txt"
{ echo "# synthesized"; echo "# sunset: 2099-01-01"; } >"$TMP/empty.txt"
rc="$(run_check "$TMP/empty.txt")"
if [[ "$rc" -ne 0 ]]; then
  ok "KG_INJECTION_BASELINE honoured (empty baseline reads as regression, exit $rc)"
else
  fail_t "KG_INJECTION_BASELINE ignored — an empty baseline still exits 0, so the real baseline answered; injection_lint is the only lint of its family without a baseline override and its sunset behaviour cannot be tested"
fi

write_baseline "$TMP/future.txt" "# sunset: 2099-01-01"
rc="$(run_check "$TMP/future.txt")"
if [[ "$rc" -eq 0 ]]; then
  ok "a synthesized baseline holding today's findings with a future sunset passes"
else
  fail_t "synthesized current-findings baseline exits $rc — expected 0"
fi

section "an expired sunset must change the verdict, not just print a warning"
write_baseline "$TMP/expired.txt" "# sunset: 2000-01-01"
rc="$(run_check "$TMP/expired.txt")"
if [[ "$rc" -ne 0 ]]; then
  ok "expired sunset exits $rc"
else
  fail_t "expired sunset still exits 0 — the grace period has no teeth"
fi

section "a missing sunset header is not an unlimited grace period"
write_baseline "$TMP/nosunset.txt" ""
rc="$(run_check "$TMP/nosunset.txt")"
if [[ "$rc" -ne 0 ]]; then
  ok "baseline without a sunset exits $rc"
else
  fail_t "baseline with no sunset header exits 0 — debt with no expiry date is permanent by default"
fi

section "a malformed sunset must not silently disable the check"
write_baseline "$TMP/garbage.txt" "# sunset: not-a-date"
rc="$(run_check "$TMP/garbage.txt")"
if [[ "$rc" -ne 0 ]]; then
  ok "malformed sunset exits $rc"
else
  fail_t "malformed sunset exits 0 — a typo in the date silently removes the expiry"
fi

section "the checked-in baseline's sunset is still in the future"
sunset="$(sed -n 's/^# sunset: *//p' ops/injection_baseline.txt | head -1)"
if [[ -z "$sunset" ]]; then
  fail_t "ops/injection_baseline.txt has no sunset header"
elif [[ "$sunset" > "$(date -u +%F)" ]]; then
  ok "checked-in sunset $sunset is in the future"
else
  fail_t "checked-in sunset $sunset has passed — resolve the outstanding items or make an explicit, dated decision to extend"
fi

# ═════════════════════════════════════════════════════════════════════════════
# IMP-20260807-1674d1 — 站在哪裡不可以改變這支 lint 掃到什麼
#
# 上面每一段都經由 $LINT（ops/injection_lint.sh）跑，而那支 wrapper 第一件事就是
# `cd "$ROOT_DIR"`——它永遠站在 repo root，所以**它永遠看不到這個缺陷**。以下刻意
# 直接呼叫 ops/injection_lint.py：gate 與 hook 以外的呼叫者（agent、編輯器、其他
# 腳本、票上的 acceptance_cmd）就是這樣叫它的。
# ═════════════════════════════════════════════════════════════════════════════

UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then UV_BIN="$HOME/.local/bin/uv"; else UV_BIN="uv"; fi
fi
PYRUN=("$UV_BIN" run --no-project --python 3.13 python)
LINT_PY="$WORKSPACE/ops/injection_lint.py"

# stdout / stderr 分開落檔：合併會讓「掃不到」的 stderr 混進本來要逐字比對的
# findings，兩份輸出就再也不可比。
run_py_from() {   # $1=cwd $2=stdout檔 $3=stderr檔 其餘=argv -> rc
  local dir="$1" out="$2" err="$3"; shift 3
  local rc=0
  ( cd "$dir" && "${PYRUN[@]}" "$LINT_PY" "$@" ) >"$out" 2>"$err" || rc=$?
  return "$rc"
}

# 讀模組常數。import 需要 ops/ 在 sys.path 上，故顯式給 PYTHONPATH——這樣
# **cwd 才是這幾條斷言裡唯一被操縱的變數**。
probe_const() {   # $1=cwd $2=python 表達式 -> stdout
  local dir="$1" expr="$2"
  ( cd "$dir" && PYTHONPATH="$WORKSPACE/ops" "${PYRUN[@]}" -c "import injection_lint as m; print($expr)" )
}

section "cwd 不得改變掃描結果"
ROOT_OUT="$TMP/report_root.out"; ROOT_ERR="$TMP/report_root.err"
rc=0; run_py_from "$WORKSPACE" "$ROOT_OUT" "$ROOT_ERR" --report || rc=$?
root_lines="$(grep -c . "$ROOT_OUT" || true)"
# 正控扣在 rc 上而不是 findings 筆數上：rc=0 現在**蘊含**掃到了檔案（零掃描 → 2），
# 那正是新守衛買到的東西。扣在「有 findings」會把這個檔綁死在「repo 保持不合規」，
# 34 筆債還清的那天反而轉紅——與這張票的 acceptance 拒用 --baseline-check 同一個理由。
if [[ "$rc" -eq 0 ]]; then
  ok "正控：站在 repo root 跑 --report rc=0（⇒ 掃到了檔案；當下 $root_lines 行 findings）"
else
  fail_t "站在 repo root 跑 --report → rc=$rc；後面「兩處輸出相同」的斷言會變成空對空的假綠"
  head -3 "$ROOT_ERR" | sed 's/^/      /'
fi

for probe_dir in "$WORKSPACE/ops" "$TMP"; do
  if [[ "$probe_dir" == "$TMP" ]]; then label="repo 外的暫存目錄"; else label="${probe_dir#"$WORKSPACE"/}"; fi
  o="$TMP/report_foreign.out"; e="$TMP/report_foreign.err"
  rc=0; run_py_from "$probe_dir" "$o" "$e" --report || rc=$?
  foreign_lines="$(grep -c . "$o" || true)"
  if [[ "$rc" -ne 0 ]]; then
    fail_t "站在 $label 跑 --report 回 rc=$rc — 掃描跟著 cwd 走：$(head -1 "$e")"
  elif cmp -s "$ROOT_OUT" "$o"; then
    ok "站在 $label 跑 --report，findings 與 repo root 逐字相同"
  else
    fail_t "站在 $label 跑 --report 得到 $foreign_lines 行、repo root 得到 $root_lines 行 — 掃到的不是同一棵樹"
  fi
done

section "模組常數對 repo 錨定，不對呼叫者的 cwd"
for probe_dir in "$WORKSPACE" "$WORKSPACE/ops" "$TMP"; do
  if [[ "$probe_dir" == "$TMP" ]]; then label="repo 外的暫存目錄"; else label="${probe_dir#"$WORKSPACE"/}"; [[ "$label" == "$WORKSPACE" ]] && label="repo root"; fi
  got="$(probe_const "$probe_dir" "m.VIEWS_ROOT" 2>/dev/null || echo "<import failed>")"
  [[ "$got" == "$WORKSPACE/ios/BooksAndVocab/Views" ]] \
    && ok "從 $label 讀 VIEWS_ROOT = $got" \
    || fail_t "從 $label 讀 VIEWS_ROOT = $got（期望 $WORKSPACE/ios/BooksAndVocab/Views）"
  got="$(probe_const "$probe_dir" "m.BASELINE_FILE" 2>/dev/null || echo "<import failed>")"
  [[ "$got" == "$WORKSPACE/ops/injection_baseline.txt" ]] \
    && ok "從 $label 讀 BASELINE_FILE = $got" \
    || fail_t "從 $label 讀 BASELINE_FILE = $got（期望 $WORKSPACE/ops/injection_baseline.txt）"
done

section "共用文法讀的 pbxproj 也對 repo 錨定"
# inject_package_linked() 真的去讀這個檔，讀不到就 except OSError → False，也就是
# R3 會**無聲地**翻面。斷言扣在「這個檔案的 read_text() 從任何 cwd 都成功」，
# 刻意**不**扣在 inject_package_linked() 今天回什麼：那個值是「Inject SPM package
# 有沒有接上」這個 repo 事實，接上的那天這條路徑錨定測試不該為了無關理由轉紅。
for probe_dir in "$WORKSPACE" "$TMP"; do
  if [[ "$probe_dir" == "$TMP" ]]; then label="repo 外的暫存目錄"; else label="repo root"; fi
  got="$(cd "$probe_dir" && PYTHONPATH="$WORKSPACE/ops" "${PYRUN[@]}" -c '
import _inject_shared as s
try:
    s.PBXPROJ.read_text(encoding="utf-8")
    readable = "readable"
except OSError as e:
    readable = f"unreadable({type(e).__name__})"
print(s.PBXPROJ.is_absolute(), readable)
' 2>/dev/null || echo "<import failed>")"
  [[ "$got" == "True readable" ]] \
    && ok "從 $label 讀 PBXPROJ：絕對=True、read_text 成功" \
    || fail_t "從 $label 讀 PBXPROJ 得到「$got」（期望「True readable」）— 讀不到就是 except OSError → False，R3 會靜靜翻面"
done

section "相對的 KG_INJECTION_BASELINE 對 repo root 解析，不對 cwd"
# 誘餌是一份**會放行的** baseline（今天全部 findings + 未來 sunset），放在 repo 外
# 一個假的 ops/ 底下。這正是 2026-08-07 在 ops/backlog.py 上量到的 disarm 形狀：
# 站在放著寬鬆 baseline 的目錄，ratchet 印 0 problems 並赦免每一筆。
DECOY_DIR="$TMP/decoy"; DECOY_REL="ops/kg_decoy_baseline.txt"
mkdir -p "$DECOY_DIR/ops"
write_baseline "$DECOY_DIR/$DECOY_REL" "# sunset: 2099-01-01"
if [[ ! -e "$WORKSPACE/$DECOY_REL" ]]; then
  ok "前提：repo root 底下沒有同名的 $DECOY_REL（相對解析必然落空）"
else
  fail_t "$WORKSPACE/$DECOY_REL 竟然存在 — 本段的紅綠會來自別的原因，請換一個誘餌檔名"
fi

# 正控：用**絕對**路徑指同一個誘餌 → 必須綠。這證明誘餌是一份合法、確實會放行的
# baseline；沒有這一條，下面那條「相對路徑時它必須紅」可能只是因為檔案是垃圾。
rc=0
( cd "$DECOY_DIR" && KG_INJECTION_BASELINE="$DECOY_DIR/$DECOY_REL" "${PYRUN[@]}" "$LINT_PY" --baseline-check ) \
  >"$TMP/decoy_abs.out" 2>&1 || rc=$?
if [[ "$rc" -eq 0 ]]; then
  ok "正控：絕對路徑指向誘餌 → rc=0（誘餌確實是一份會放行的 baseline）"
else
  fail_t "絕對路徑指向誘餌卻 rc=$rc — 誘餌本身就不會放行，本段失去判別力"
  head -3 "$TMP/decoy_abs.out" | sed 's/^/      /'
fi

got="$(cd "$DECOY_DIR" && KG_INJECTION_BASELINE="$DECOY_REL" PYTHONPATH="$WORKSPACE/ops" \
        "${PYRUN[@]}" -c "import injection_lint as m; print(m.BASELINE_FILE)" 2>/dev/null || echo "<import failed>")"
[[ "$got" == "$WORKSPACE/$DECOY_REL" ]] \
  && ok "相對覆寫解到 repo root：$got" \
  || fail_t "相對覆寫解到 $got（期望 $WORKSPACE/$DECOY_REL）— 站在別的目錄就會讀到別人的 baseline"

rc=0
( cd "$DECOY_DIR" && KG_INJECTION_BASELINE="$DECOY_REL" "${PYRUN[@]}" "$LINT_PY" --baseline-check ) \
  >"$TMP/decoy_rel.out" 2>&1 || rc=$?
if [[ "$rc" -ne 0 ]] && grep -q 'REGRESSION' "$TMP/decoy_rel.out"; then
  ok "端到端：站在誘餌目錄用相對覆寫 → rc=$rc 且判 REGRESSION（讀的是 repo root 底下那條不存在的路徑，不是誘餌）"
elif [[ "$rc" -eq 0 ]]; then
  fail_t "站在誘餌目錄用相對覆寫 → rc=0，誘餌被讀到並赦免了全部 findings"
else
  fail_t "站在誘餌目錄用相對覆寫 → rc=$rc 但輸出沒有 REGRESSION，擋它的是別的原因"
  head -3 "$TMP/decoy_rel.out" | sed 's/^/      /'
fi

# IMP-0048 的裁決：`KG_INJECTION_BASELINE=`（空字串）必須仍然解到 repo root（一個
# 目錄），讓 ui_quality_gate.py 的 `.is_file()` 在父層攔得下來。ROOT 錨定不得順手
# 把這個形狀「修掉」，否則父子兩邊對同一個輸入又會分岔。
got="$(cd "$TMP" && KG_INJECTION_BASELINE= PYTHONPATH="$WORKSPACE/ops" \
        "${PYRUN[@]}" -c "import injection_lint as m; print(m.BASELINE_FILE)" 2>/dev/null || echo "<import failed>")"
[[ "$got" == "$WORKSPACE" ]] \
  && ok "KG_INJECTION_BASELINE=（空）仍解到 repo root $got" \
  || fail_t "KG_INJECTION_BASELINE=（空）解到 $got（期望 $WORKSPACE）— ui_quality_gate.py 的父層攔截會與子進程分岔"
# 常數對了還不夠：IMP-0048 保的是**行為**——子進程對空字串會死在 IsADirectoryError，
# 所以父層才需要先用 .is_file() 攔。有人日後給 read_baseline() 補一道守衛，上面那條
# 常數斷言會照樣綠，而父層那道攔截就變成沒有對象的儀式。
got="$(cd "$TMP" && KG_INJECTION_BASELINE= PYTHONPATH="$WORKSPACE/ops" "${PYRUN[@]}" -c '
import injection_lint as m
try:
    m.read_baseline()
    print("no-exception")
except IsADirectoryError:
    print("IsADirectoryError")
except Exception as e:
    print(type(e).__name__)
' 2>/dev/null || echo "<import failed>")"
[[ "$got" == "IsADirectoryError" ]] \
  && ok "KG_INJECTION_BASELINE=（空）時 read_baseline() 仍拋 IsADirectoryError（IMP-0048 的形狀未被改掉）" \
  || fail_t "KG_INJECTION_BASELINE=（空）時 read_baseline() 得到「$got」（期望 IsADirectoryError）— 父層的 .is_file() 攔截已無對象"

section "掃到零個檔案必須 fail closed，不可讀成通過"
# 直接注入 VIEWS_ROOT 跑 collect_findings，因為這支工具刻意**沒有**掃描根的環境
# 覆寫（多一個覆寫就多一個把 gate 指向空樹的旋鈕）。單引號 heredoc：python 原始碼
# 不經 bash 展開。
scan_probe() {   # $1=views root $2=輸出檔 -> echo rc
  local root="$1" out="$2" rc=0
  ( cd "$WORKSPACE/ops" && "${PYRUN[@]}" -c '
import sys
from pathlib import Path
import injection_lint as m
m.VIEWS_ROOT = Path(sys.argv[1])
sys.argv = ["injection_lint.py", "--strict"]
raise SystemExit(m.main())
' "$root" ) >"$out" 2>&1 || rc=$?
  echo "$rc"
}

TREE="$TMP/trees"
mkdir -p "$TREE/clean" "$TREE/empty" "$TREE/allskipped/Debug" "$TREE/offender" \
         "$TREE/Debug/checkout_named_like_a_skip_fragment"
cat >"$TREE/clean/Compliant.swift" <<'SWIFT'
struct Compliant: View {
    @ObserveInjection var inject
    var body: some View { EmptyView().enableInjection() }
}
SWIFT
cp "$TREE/clean/Compliant.swift" "$TREE/allskipped/Debug/Compliant.swift"
cp "$TREE/clean/Compliant.swift" "$TREE/Debug/checkout_named_like_a_skip_fragment/Compliant.swift"
cat >"$TREE/offender/Offender.swift" <<'SWIFT'
struct Offender: View {
    var body: some View { EmptyView() }
}
SWIFT

# 負控先跑：證明這個探針不是「永遠紅」。
rc="$(scan_probe "$TREE/clean" "$TMP/probe_clean.out")"
[[ "$rc" -eq 0 ]] \
  && ok "負控：一個合規檔的樹 → rc=0（新守衛沒有把所有東西都變紅）" \
  || { fail_t "負控失敗：一個合規檔的樹 → rc=$rc（期望 0）"; sed 's/^/      /' "$TMP/probe_clean.out"; }

rc="$(scan_probe "$TREE/offender" "$TMP/probe_offender.out")"
[[ "$rc" -eq 1 ]] \
  && ok "負控：一個違規檔的樹 → rc=1（findings 的紅，不是結構性的紅）" \
  || { fail_t "負控失敗：一個違規檔的樹 → rc=$rc（期望 1）"; sed 's/^/      /' "$TMP/probe_offender.out"; }

# skip 判斷必須看「樹內」的路徑。VIEWS_ROOT 現在是絕對的，若拿整條絕對路徑做
# 子字串比對，一個住在名為 Debug/ 的目錄底下的 checkout 會排除掉每一個檔案 ——
# 那就是「零掃描」再一次，只是這次連使用者都不知道自己踩到了什麼。
rc="$(scan_probe "$TREE/Debug/checkout_named_like_a_skip_fragment" "$TMP/probe_debugroot.out")"
[[ "$rc" -eq 0 ]] \
  && ok "掃描根的**上層**叫 Debug/ 不影響 skip 判斷 → rc=0（skip 看的是樹內路徑）" \
  || { fail_t "掃描根上層叫 Debug/ 時 → rc=$rc（期望 0）— skip 拿整條絕對路徑比對，整棵樹被排除"; sed 's/^/      /' "$TMP/probe_debugroot.out"; }

for case_dir in empty allskipped; do
  case "$case_dir" in
    empty)      why="樹裡一個 .swift 都沒有" ;;
    allskipped) why="樹裡的 .swift 全被 skip 清單排除" ;;
  esac
  rc="$(scan_probe "$TREE/$case_dir" "$TMP/probe_$case_dir.out")"
  if [[ "$rc" -eq 2 ]]; then
    ok "正控：$why → rc=2"
  else
    fail_t "正控失敗：$why → rc=$rc（期望 2）— 掃了零個檔案卻不是紅的"
    sed 's/^/      /' "$TMP/probe_$case_dir.out"
  fi
  if grep -q 'scanned 0 files' "$TMP/probe_$case_dir.out"; then
    ok "正控：$why 時輸出具名說出「scanned 0 files」"
  else
    fail_t "正控失敗：$why 時輸出沒有具名說出掃了零個檔案 — 裸 rc 會被讀成別的失敗"
    sed 's/^/      /' "$TMP/probe_$case_dir.out"
  fi
  if grep -q 'no findings' "$TMP/probe_$case_dir.out"; then
    fail_t "正控失敗：$why 時仍印出 'no findings' — 零掃描被講成乾淨"
  else
    ok "正控：$why 時不再印出 'no findings'"
  fi
done

echo ""
echo "injection-lint: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
