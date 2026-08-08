#!/usr/bin/env bash
# test_gen_ios_baseline.sh — the ios_baseline source-text counters must be able to count.
#
# IMP-20260805-958999: line 25 grepped the literal "async func", which is not Swift word
# order (`func f() async`), so the published metric was structurally 0 forever while the
# tree held 290 async declarations. A permanently-constant metric is the one value an
# equality-style drift check blesses as consistent — both sides agree, and both are wrong.
# So this file does not compare the doc to a recomputation; it asks each counter to prove
# it can move: a fixture with N occurrences must count N, a fixture with none must count 0.
#
# Ground truth for the fixtures below was hand-counted, then cross-checked on the real tree
# against a Swift lexer that strips comments/strings and walks balanced parens (async funcs
# 290, @MainActor attribute lines 252). The grep pipelines are approximations of that lexer;
# their measured residual error is recorded in ops/gen_ios_baseline.sh next to each counter.
#
# KNOWN, DELIBERATE HOLES (measured 0 occurrences in ios/BooksAndVocab on 2026-08-06, so
# they are not asserted here — see the generator's comments):
#   - `@MainActor` or `) async` inside a /* block comment */ or a string literal.
#   - funcs whose only `) async` is a non-async `@escaping () async ->` parameter (2 today).
set -uo pipefail
WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$WORKSPACE"
GEN="${KG_GEN_IOS_BASELINE_SCRIPT:-ops/gen_ios_baseline.sh}"
# 產物已於 IMP-20260808-b63206 移出版控（`--write` / `--check` 一併退場），所以這裡不再
# 有 committed 檔可讀。最後一節改成讀 generator 的 **stdout**——那本來就是被測的東西，
# 讀磁碟上的副本只是多了一層可能腐爛的間接。
OUT_PATH="docs/snapshot/ios_baseline.md"
pass=0; fail=0
ok(){ echo "  ✓ $*"; pass=$((pass+1)); }
fail_t(){ echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# Drive the REAL assignment line out of the generator against an arbitrary tree, so the
# test can never drift from the shipped pipeline the way a re-typed copy of it would.
count_with() {  # $1 = variable name, $2 = dir to scan -> stdout: the number the generator would print
  local var="$1" IOS_DIR="$2" line
  line="$(grep -E "^${var}=" "$GEN")"
  eval "$line"
  eval "printf '%s' \"\$${var}\""
}

section "each counter is a single extractable top-level line"
for var in ASYNC_FUNC MAIN_ACTOR; do
  n="$(grep -cE "^${var}=" "$GEN")"
  [[ "$n" == "1" ]] && ok "exactly one ^${var}= line in $GEN" \
    || fail_t "expected exactly 1 ^${var}= line in $GEN, found $n (the acceptance evals this line; it must stay single-line and unindented)"
done

section "async: canonical Swift declarations are counted, including multi-line signatures"
mkdir -p "$TMP/pos"
cat > "$TMP/pos/A.swift" <<'EOF'
func alpha() async {}
func beta() async throws -> Int { 0 }
static func gamma(x: Int) async -> String { "" }
public func delta(
    first: Int,
    second: String
) async throws -> Bool { true }
func epsilon(cb: (Int) async -> Void) async {}
EOF
# Hand-counted: alpha, beta, gamma, delta (multi-line signature), epsilon = 5.
got="$(count_with ASYNC_FUNC "$TMP/pos")"
[[ "$got" == "5" ]] && ok "5 async declarations counted as 5 (4 same-line + 1 multi-line)" \
  || fail_t "async-declaration counter is wrong: 5 canonical Swift async funcs counted as '$got' (Swift word order is 'func f() async', never 'async func'; a signature may also close on a later line)"

section "async: prose, string literals and closure-typed properties are not counted"
mkdir -p "$TMP/neg"
cat > "$TMP/neg/B.swift" <<'EOF'
func plain() {}
func thrower() throws -> Int { 0 }
let hint = "async func"
// TODO: make this an async func
//    ) async throws -> Void
var sleepy: (Duration) async -> Void = { _ in }
EOF
got="$(count_with ASYNC_FUNC "$TMP/neg")"
[[ "$got" == "0" ]] && ok "no async declarations counted as 0" \
  || fail_t "async counter matches non-declarations: expected 0, got '$got'"

section "@MainActor: attributes are counted, doc-comment prose is not"
mkdir -p "$TMP/ma"
cat > "$TMP/ma/C.swift" <<'EOF'
@MainActor
final class Foo {}
@MainActor func bar() {}
/// `AuthManaging` is `@MainActor`-isolated, so construct this inside a
/// @MainActor View body.
// @MainActor here is prose too
EOF
# Hand-counted: 2 real attribute lines; the 3 comment lines must not count.
got="$(count_with MAIN_ACTOR "$TMP/ma")"
[[ "$got" == "2" ]] && ok "2 @MainActor attributes counted as 2, 3 comment mentions excluded" \
  || fail_t "@MainActor counter is wrong: expected 2, got '$got' (doc comments discussing @MainActor are prose, not concurrency annotations)"

section "real tree: the counters are not stuck at an impossible constant"
got="$(count_with ASYNC_FUNC "ios/BooksAndVocab")"
[[ "$got" =~ ^[0-9]+$ && "$got" -gt 0 ]] && ok "ios/BooksAndVocab async declarations = $got (> 0)" \
  || fail_t "ios/BooksAndVocab async declarations = '$got'; a permanently-zero metric is a bug, not a fact"
# Non-tautological: this codebase demonstrably has multi-line async signatures (71 today),
# so a counter that only sees same-line ones must come out strictly lower than the real one.
same_line="$({ grep -rE "func [^{]*\)[[:space:]]*async" ios/BooksAndVocab --include="*.swift" 2>/dev/null || true; } | wc -l | tr -d ' ')"
[[ "$got" =~ ^[0-9]+$ && "$got" -gt "$same_line" ]] && ok "multi-line signatures are counted too ($got > same-line-only $same_line)" \
  || fail_t "counter sees only same-line signatures ($got vs same-line-only $same_line); multi-line 'func f(\\n...\\n) async' declarations are being dropped"

section "stdout is the only mode: --write / --check are gone"
# 這一節守的是 IMP-20260808-b63206 的實質：產物移出版控後，任何「落檔」或「比對磁碟產物」
# 的模式都必須消失，否則下一個 agent 照著舊 help 跑 --write，又把一個 repo 級產物夾進
# 自己的 commit——那正是這張票要拆掉的東西。
# 斷言用的是 **rc + 具名 stderr**：只驗 rc!=0 的話，腳本因為任何別的理由爆掉都能滿足它。
#
# rc 一律用 `|| rc=$?` 取，**不要**在這裡做 `set +e` … `set -e` 手術：本檔第 20 行是
# `set -uo pipefail`（errexit 是**關**的），那個 `set -e` 會把 errexit 打開留給整份腳本
# 剩下的部分，於是後面任何一支回非零的被測命令都會讓測試**中途靜默死掉**——章節標題印完
# 就沒了，一個 ✗ 都不印，連 passed/failed summary 都不印。那種「紅」是靠中止換來的，
# 而下一個人清掉多餘的 set -e 時它會直接變成假綠。
for flag in --write --check; do
  rc=0
  "$GEN" "$flag" >"$TMP/mode.out" 2>"$TMP/mode.err" || rc=$?
  if [[ "$rc" == "2" ]] && grep -qF -- "unknown arg: $flag" "$TMP/mode.err"; then
    ok "$flag rejected (rc=2, stderr names it: $(head -1 "$TMP/mode.err"))"
  else
    fail_t "$flag should be rejected as an unknown arg (rc=2 + 'unknown arg: $flag' on stderr); got rc=$rc stderr='$(head -1 "$TMP/mode.err")'"
  fi
done

help_rc=0
"$GEN" --help >"$TMP/help.out" 2>&1 || help_rc=$?
[[ "$help_rc" == "0" ]] && ok "--help exits 0" || fail_t "--help should exit 0, got $help_rc"
# 正控先於沉默：先證明 help 真的有內容且在講這支腳本，否則下面兩條「不含 --write/--check」
# 會被一份空 help 滿足。
if [[ "$(wc -l <"$TMP/help.out" | tr -d ' ')" -ge 3 ]] && grep -qF "gen_ios_baseline.sh" "$TMP/help.out"; then
  ok "--help is non-empty and names this script (positive control for the two negatives below)"
else
  fail_t "--help is empty or does not name gen_ios_baseline.sh — the negatives below would be vacuous"
fi
for flag in --write --check; do
  if grep -qF -- "$flag" "$TMP/help.out"; then
    fail_t "--help still advertises $flag; the flag is gone, the docs must be too"
  else
    ok "--help no longer advertises $flag"
  fi
done

section "the generator writes nothing into the tree"
# 用「跑前跑後 git status 逐字相同」表達，而不是 rm 掉再看它有沒有回來——後者要對一個
# 當下可能仍被追蹤的檔動手，測試不該有那種副作用。
before_status="$(git status --porcelain)"
gen_rc=0
"$GEN" >"$TMP/live.md" 2>"$TMP/live.err" || gen_rc=$?
after_status="$(git status --porcelain)"
lines="$(wc -l <"$TMP/live.md" | tr -d ' ')"
# 正控有兩條，缺一不可：
#   (a) exit status —— 沒有它，一支「印對了 49 行然後 exit 1」的 generator 可以走完整節
#       而沒有任何斷言看它一眼（本檔曾經就是這樣，見上面那段 set -e 的註解）。
#   (b) 產出量 —— 沒有它，「工作樹沒變」是廢話，一支什麼都不做的腳本也滿足。
[[ "$gen_rc" -eq 0 ]] && ok "plain run exited 0 (positive control)" \
  || fail_t "plain run exited $gen_rc; stderr: $(head -1 "$TMP/live.err")"
[[ "$lines" -ge 20 ]] && ok "plain run emitted a $lines-line baseline on stdout (positive control)" \
  || fail_t "plain run emitted only $lines lines on stdout; the no-write assertion below would be vacuous"
# 這條的涵蓋面**不含** gitignore 掉的路徑（實測 2026-08-08：把 generator 改回會寫檔，這條
# 仍然綠，因為 OUT_PATH 已被 gitignore，git status 根本看不到它）。它守的是「寫到任何**被
# 追蹤**的檔」；OUT_PATH 那個具體失效模式由下一條負責。兩條分工寫在這裡，免得下一個人
# 以為這條有它其實沒有的力氣。
[[ "$before_status" == "$after_status" ]] && ok "git status unchanged across the run (沒動到任何 tracked 檔)" \
  || fail_t "the generator dirtied a tracked file; diff of git status:
$(diff <(printf '%s\n' "$before_status") <(printf '%s\n' "$after_status") || true)"
# 票立的不變式是「**不在版控**」，不是「磁碟上不存在」，所以分兩條各說各的話——否則將來
# 真有殘留檔時，失敗訊息會指不到病灶。
if git ls-files --error-unmatch "$OUT_PATH" >/dev/null 2>&1; then
  fail_t "$OUT_PATH is tracked by git — 產物應已移出版控（git rm --cached 並確認 .gitignore 蓋到它）"
else
  ok "$OUT_PATH is not tracked by git (產物已移出版控)"
fi
[[ ! -e "$OUT_PATH" ]] && ok "$OUT_PATH was not written to disk by this run" \
  || fail_t "$OUT_PATH exists on disk — 這一跑把產物寫出來了，或工作樹留了殘骸"

section "the generated output carries the same non-zero reality"
for label in "async func" "@MainActor"; do
  row="$(awk -F'|' -v l="$label" '$2 ~ l {gsub(/[[:space:]]/,"",$3); print $3; exit}' "$TMP/live.md")"
  if [[ ! "$row" =~ ^[0-9]+$ ]]; then
    fail_t "could not parse the '$label' row out of the generator's stdout (got '$row') — the probe is broken, not the generator"
  elif [[ "$row" -gt 0 ]]; then
    ok "generator stdout '$label' row = $row (> 0)"
  else
    fail_t "generator publishes '$label = $row'; a permanently-zero metric is a bug, not a fact"
  fi
done

echo ""; echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
