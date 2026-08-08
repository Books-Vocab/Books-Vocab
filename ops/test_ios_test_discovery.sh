#!/usr/bin/env bash
# test_ios_test_discovery.sh — behavioral verification for the -g (grep) test
# discovery logic used by ops/ios_test.sh.
#
# The discovery logic is extracted into ops/lib/ios_test_discovery.sh as a
# sourceable function `discover_only_flags <test_dir> <grep_pattern>` so it can
# be driven against an isolated fixture tree (no Xcode / no PTY needed).
#
# Regression guards:
#   1. Every test func is attributed to its OWN enclosing top-level container,
#      not the file's first struct (the historical `head -1` bug).
#   2. `@Suite struct X` (same-line) and `@Suite(.serialized)\nstruct X`
#      (split-line) containers are discovered, not silently skipped.
#   3. `final class X: XCTestCase` / `class X` containers are discovered.
#   4. Nested helper structs declared INSIDE a func body (indented) are NOT
#      treated as containers and never appear in a -only-testing path.
#   5. Files with no test container are skipped without emitting bogus flags.
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
LIB="$WORKSPACE/ops/lib/ios_test_discovery.sh"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

[[ -f "$LIB" ]] || { echo "FATAL: $LIB missing"; exit 1; }
# shellcheck source=/dev/null
source "$LIB"

# ── fixture tree ──────────────────────────────────────────────────────────────
FIX="$(mktemp -d)"
cleanup() { rm -rf "$FIX"; }
trap cleanup EXIT

# Multi top-level struct file: each func must attribute to its own struct.
cat > "$FIX/MultiStructTests.swift" <<'SWIFT'
import Testing

struct AlphaTests {
    @Test func alphaOne() {}
    @Test func alphaTwo() {
        struct NestedHelper: Error {}   // indented helper — NOT a container
    }
}

struct BravoTests {
    @Test func bravoOne() {}
}
SWIFT

# @Suite same-line containers.
cat > "$FIX/SuiteSameLineTests.swift" <<'SWIFT'
import Testing

@Suite struct CharlieTests {
    @Test func charlieOne() {}
}

@Suite struct DeltaTests {
    @Test func deltaOne() {}
}
SWIFT

# @Suite split-line + @Test-on-prev-line + a helper func that must NOT emit.
cat > "$FIX/SuiteSplitLineTests.swift" <<'SWIFT'
import Testing

@Suite(.serialized)
struct EchoTests {
    @Test func echoOne() {}
    @Test func echoTwo() {}

    @Test @MainActor
    func echoThree() throws {}

    func makeHelper() -> Int { 0 }   // plain helper — NOT a test
}
SWIFT

# XCTest class container with `func test...` (no @Test attribute).
cat > "$FIX/ClassTests.swift" <<'SWIFT'
import XCTest

final class FoxtrotTests: XCTestCase {
    func testFoxtrotOne() {}
    func testFoxtrotTwo() {}
}
SWIFT

# Parameterized @Test(arguments:) — single-line AND multiline-spanning forms.
# The func name does NOT start with `test`, so it is ONLY discoverable via the
# @Test attribute. The multiline `@Test(arguments: [ \n ... \n ])` must arm the
# next `func` across the intervening argument rows (the historical drop bug).
#
# Signature contract: Swift Testing -only-testing IDs must carry the FULL
# parameter-label signature (`golfSingleLine(_:)`, `golfLabeled(input:)`).
# Emitting `golfSingleLine()` for a parameterized func makes xcodebuild match
# 0 tests → "TEST SUCCEEDED" with nothing run (the 2026-06-11 silent FALSE
# GREEN only caught by the post-run zero-tests guard).
cat > "$FIX/ParamTests.swift" <<'SWIFT'
import Testing

struct GolfTests {
    // Single-line argument form (paren closes same line).
    @Test(arguments: [1, 2, 3])
    func golfSingleLine(_ n: Int) {}

    // Multiline argument form — paren opens here, rows below, closes later.
    @Test(arguments: [
        (1, 2.0),
        (3, 4.0),
    ])
    func golfMultiLine(_ a: Int, _ b: Double) {}

    // Labeled parameter — ID must carry the label, not `_`.
    @Test(arguments: ["a", "b"])
    func golfLabeled(input: String) {}

    // External/internal label pair — ID carries the EXTERNAL label.
    @Test(arguments: [1])
    func golfExtInt(for value: Int) {}

    // Nested commas inside a tuple type must not split the label list.
    @Test(arguments: [((1, "x"), 2)])
    func golfTuple(_ pair: (Int, String), count: Int) {}

    // Param list spans lines — signature unknowable from the func line alone;
    // must degrade to a SUITE-level selector (safe superset), never a bare
    // name / wrong signature (both zero-match).
    @Test(arguments: [1])
    func golfMultiLineParams(
        _ n: Int,
        label other: Int
    ) {}

    // Display-name form on its own line above the func.
    @Test("a display name")
    func golfDisplayName() {}

    // Plain helper between tests — must NOT be armed/emitted.
    func makeFixture() -> Int { 0 }

    // Same-line @Test func still works after the multiline arm was consumed.
    @Test func golfSameLine() {}
}

// A second container right after a multiline @Test arm scenario: ensure the
// arm does not bleed across the container boundary onto Hotel's first func.
struct HotelTests {
    @Test(arguments: [
        "x",
        "y",
    ])
    func hotelMultiLine(_ s: String) {}
}
SWIFT

# No container at all — must be skipped, never emit a bogus flag.
cat > "$FIX/NoContainer.swift" <<'SWIFT'
import Foundation
enum Helpers { static func notATest() {} }
SWIFT

# helper: does the flag set contain exactly this -only-testing path?
has_flag() { printf '%s\n' "$1" | grep -qxF -e "-only-testing:BooksAndVocabTests/$2"; }

# ── 1. syntax ─────────────────────────────────────────────────────────────────
section "Syntax"
bash -n "$LIB" && ok "lib syntax" || fail_t "lib syntax"

# ── 2. multi-struct attribution (the head -1 bug) ─────────────────────────────
section "Multi-struct attribution"
FLAGS="$(discover_only_flags "$FIX" "")"
has_flag "$FLAGS" "AlphaTests/alphaOne()" && ok "alphaOne → AlphaTests" || fail_t "alphaOne misattributed"
has_flag "$FLAGS" "AlphaTests/alphaTwo()" && ok "alphaTwo → AlphaTests" || fail_t "alphaTwo misattributed"
has_flag "$FLAGS" "BravoTests/bravoOne()" && ok "bravoOne → BravoTests (not AlphaTests)" || fail_t "bravoOne misattributed"
printf '%s\n' "$FLAGS" | grep -qF "AlphaTests/bravoOne" && fail_t "bravoOne WRONGLY under AlphaTests" || ok "bravoOne not under AlphaTests"

# ── 3. nested helper struct is never a container ──────────────────────────────
section "Nested helper exclusion"
printf '%s\n' "$FLAGS" | grep -qF "NestedHelper" && fail_t "NestedHelper leaked as container" || ok "NestedHelper not a container"

# ── 4. @Suite same-line ───────────────────────────────────────────────────────
section "@Suite same-line"
has_flag "$FLAGS" "CharlieTests/charlieOne()" && ok "charlieOne → CharlieTests" || fail_t "@Suite same-line CharlieTests skipped"
has_flag "$FLAGS" "DeltaTests/deltaOne()"     && ok "deltaOne → DeltaTests"     || fail_t "@Suite same-line DeltaTests skipped"

# ── 5. @Suite split-line ──────────────────────────────────────────────────────
section "@Suite split-line"
has_flag "$FLAGS" "EchoTests/echoOne()" && ok "echoOne → EchoTests" || fail_t "@Suite split-line skipped"
has_flag "$FLAGS" "EchoTests/echoTwo()" && ok "echoTwo → EchoTests" || fail_t "@Suite split-line skipped"
has_flag "$FLAGS" "EchoTests/echoThree()" && ok "echoThree (@Test on prev line) → EchoTests" || fail_t "@Test-on-prev-line func skipped"
printf '%s\n' "$FLAGS" | grep -qF "makeHelper" && fail_t "plain helper makeHelper leaked" || ok "plain helper makeHelper excluded"

# ── 6. XCTest class container ─────────────────────────────────────────────────
section "XCTest class container"
has_flag "$FLAGS" "FoxtrotTests/testFoxtrotOne" && ok "testFoxtrotOne → FoxtrotTests" || fail_t "class container skipped"
has_flag "$FLAGS" "FoxtrotTests/testFoxtrotTwo" && ok "testFoxtrotTwo → FoxtrotTests" || fail_t "class container skipped"

# ── 7. no-container file emits nothing ────────────────────────────────────────
section "No-container file"
printf '%s\n' "$FLAGS" | grep -qF "NoContainer" && fail_t "NoContainer leaked" || ok "NoContainer skipped"
printf '%s\n' "$FLAGS" | grep -qF "Helpers" && fail_t "Helpers enum leaked" || ok "Helpers enum not a container"

# ── 8. grep pattern filters by func name ──────────────────────────────────────
section "Grep pattern filter"
ONLY_ALPHA="$(discover_only_flags "$FIX" "alpha")"
has_flag "$ONLY_ALPHA" "AlphaTests/alphaOne()" && ok "pattern 'alpha' keeps alphaOne" || fail_t "pattern dropped alphaOne"
printf '%s\n' "$ONLY_ALPHA" | grep -qF "bravoOne" && fail_t "pattern 'alpha' leaked bravoOne" || ok "pattern 'alpha' excludes bravoOne"
printf '%s\n' "$ONLY_ALPHA" | grep -qF "charlieOne" && fail_t "pattern 'alpha' leaked charlieOne" || ok "pattern 'alpha' excludes charlieOne"

# ── 9. case-insensitive pattern (preserves -i behavior) ───────────────────────
section "Case-insensitive pattern"
ONLY_FOX="$(discover_only_flags "$FIX" "FOXTROT")"
has_flag "$ONLY_FOX" "FoxtrotTests/testFoxtrotOne" && ok "uppercase pattern matches" || fail_t "lost case-insensitivity"

# ── 9b. pattern matches suite/container names too（2026-06-11 摩擦修復：以
#        suite 名跑整個 suite 不該再吐 no-tests-matching 浪費一輪 build+test）──
section "Suite/container-name pattern"
ONLY_BRAVO="$(discover_only_flags "$FIX" "BravoTests")"
has_flag "$ONLY_BRAVO" "BravoTests/bravoOne()" \
  && ok "suite-name pattern 'BravoTests' runs its tests" || fail_t "suite-name pattern dropped bravoOne"
printf '%s\n' "$ONLY_BRAVO" | grep -qF "alphaOne" \
  && fail_t "suite-name pattern 'BravoTests' leaked AlphaTests funcs" || ok "suite-name pattern excludes other suites"
# case-insensitive container match + XCTest class container
ONLY_FOXC="$(discover_only_flags "$FIX" "foxtrottests")"
has_flag "$ONLY_FOXC" "FoxtrotTests/testFoxtrotOne" \
  && ok "lowercase suite-name matches XCTest class container" || fail_t "class-container suite-name match failed"
has_flag "$ONLY_FOXC" "FoxtrotTests/testFoxtrotTwo" \
  && ok "suite-name match covers ALL funcs of the container" || fail_t "suite-name match missed testFoxtrotTwo"
# plain helper funcs must stay excluded even when their container matches
ONLY_ECHO="$(discover_only_flags "$FIX" "EchoTests")"
has_flag "$ONLY_ECHO" "EchoTests/echoThree()" \
  && ok "suite-name match includes @Test-on-prev-line funcs" || fail_t "suite-name match missed echoThree"
printf '%s\n' "$ONLY_ECHO" | grep -qF "makeHelper" \
  && fail_t "suite-name match leaked plain helper makeHelper" || ok "suite-name match still excludes plain helpers"
# 交叉地雷迴歸（兩 reviewer 點名）：suite 名 pattern 必須也覆蓋多行參數列的
# suite-level fallback。fallback 分支若自帶只比對 fn 的行內判斷，
# `-g GolfTests` 會無聲漏掉 golfMultiLineParams（partial silent miss）；
# emit() 與 fallback 共用 match_fn_or_container() 後此處必綠。
ONLY_GOLF="$(discover_only_flags "$FIX" "golftests")"
has_flag "$ONLY_GOLF" "GolfTests" \
  && ok "suite-name pattern reaches multiline-params suite fallback" || fail_t "suite-name pattern dropped multiline-params fallback (fn-only check drift)"
has_flag "$ONLY_GOLF" "GolfTests/golfSingleLine(_:)" \
  && ok "suite-name pattern keeps parameterized signatures" || fail_t "suite-name pattern dropped parameterized signature func"

# ── 10. parameterized @Test(arguments:) single + multiline ───────────────────
section "Parameterized @Test(arguments:) discovery"
has_flag "$FLAGS" "GolfTests/golfSingleLine(_:)" && ok "golfSingleLine → (_:) signature" || fail_t "single-line @Test(arguments:) lacks (_:) signature"
has_flag "$FLAGS" "GolfTests/golfMultiLine(_:_:)" && ok "golfMultiLine → (_:_:) signature" || fail_t "multiline @Test(arguments:) lacks (_:_:) signature"
has_flag "$FLAGS" "GolfTests/golfLabeled(input:)" && ok "golfLabeled → (input:) signature" || fail_t "labeled param lost its label"
has_flag "$FLAGS" "GolfTests/golfExtInt(for:)" && ok "golfExtInt → (for:) external label" || fail_t "external/internal label pair mishandled"
has_flag "$FLAGS" "GolfTests/golfTuple(_:count:)" && ok "golfTuple → (_:count:) (tuple comma not split)" || fail_t "nested tuple comma split the label list"
printf '%s\n' "$FLAGS" | grep -qF "golfSingleLine()" && fail_t "parameterized func WRONGLY emitted bare () (xcodebuild matches 0 tests = false green)" || ok "no bare () emitted for parameterized funcs"
has_flag "$FLAGS" "GolfTests" && ok "golfMultiLineParams (params span lines) → suite-level fallback" || fail_t "multiline-params func did not fall back to suite-level selector"
printf '%s\n' "$FLAGS" | grep -qF "golfMultiLineParams" && fail_t "multiline-params func emitted a guessed (wrong) func selector" || ok "no guessed selector for multiline-params func"
has_flag "$FLAGS" "GolfTests/golfDisplayName()" && ok "golfDisplayName (@Test display name) → GolfTests" || fail_t "@Test(display-name) dropped"
has_flag "$FLAGS" "GolfTests/golfSameLine()" && ok "golfSameLine (@Test func after multiline arm) → GolfTests" || fail_t "same-line @Test regressed after multiline arm"
printf '%s\n' "$FLAGS" | grep -qF "makeFixture" && fail_t "plain helper makeFixture leaked" || ok "plain helper makeFixture excluded"
has_flag "$FLAGS" "HotelTests/hotelMultiLine(_:)" && ok "hotelMultiLine → HotelTests (no cross-container bleed)" || fail_t "multiline arm dropped in HotelTests"
printf '%s\n' "$FLAGS" | grep -qF "GolfTests/hotelMultiLine" && fail_t "hotelMultiLine WRONGLY under GolfTests (arm bled across container)" || ok "no arm bleed across struct boundary"

# ── 11. ios_test.sh -g 旗標 E2E（--list 在碰鎖/xcodebuild 前退出，可安全跑）──
# 多個 -g 必須累積成 OR（歷史 bug：後者無聲覆蓋前者 → 以為跑兩個實際跑一個）。
section "ios_test.sh multi -g accumulation (--list)"
# ios_test.sh 的 TEST_DIR 硬編真實 test 目錄（吃不到本檔的 $FIX fixture），
# 故直接從真實測試自我發現兩個方法名。注意：只認 XCTest 風格 `func testXxx`；
# 若全數遷移到 Swift Testing 命名，這裡會找不到名而 fail（屆時改抓 @Test func）。
IOS_TEST="$WORKSPACE/ops/ios_test.sh"
PAT_A="$(grep -rhoE 'func test[A-Za-z0-9_]+' "$WORKSPACE/ios/BooksAndVocabTests" 2>/dev/null | sed -n '1p' | sed 's/func //')"
PAT_B="$(grep -rhoE 'func test[A-Za-z0-9_]+' "$WORKSPACE/ios/BooksAndVocabTests" 2>/dev/null | tail -1 | sed 's/func //')"
if [[ -n "$PAT_A" && -n "$PAT_B" && "$PAT_A" != "$PAT_B" ]]; then
  LIST_A="$("$IOS_TEST" -g "$PAT_A" --list 2>/dev/null)" || LIST_A=""
  LIST_B="$("$IOS_TEST" -g "$PAT_B" --list 2>/dev/null)" || LIST_B=""
  OUT_AB="$("$IOS_TEST" -g "$PAT_A" -g "$PAT_B" --list 2>/dev/null)" || OUT_AB=""
  # 強斷言：合併輸出必須是兩個單獨輸出的聯集超集（防舊覆蓋 bug 用計數巧合矇混）。
  superset=1
  while IFS= read -r flag; do
    [[ -z "$flag" ]] && continue
    grep -qF -- "$flag" <<<"$OUT_AB" || { superset=0; break; }
  done < <(printf '%s\n%s\n' "$LIST_A" "$LIST_B" | grep only-testing)
  N_A="$(grep -c only-testing <<<"$LIST_A" || true)"
  N_B="$(grep -c only-testing <<<"$LIST_B" || true)"
  if (( N_A >= 1 && N_B >= 1 && superset == 1 )); then
    ok "multi -g 累積且合併輸出 ⊇ 兩單獨輸出聯集（$PAT_A:$N_A + $PAT_B:${N_B}）"
  else
    fail_t "multi -g 未累積（$PAT_A:$N_A, $PAT_B:$N_B, superset=${superset}）"
  fi
else
  fail_t "找不到兩個可用的真實測試名（PAT_A='$PAT_A' PAT_B='$PAT_B'）"
fi

# ── 11b. 空 -g pattern 必須被拒（空 ERE alternative 匹配一切 = silent broadening）─
section "empty -g pattern rejected"
EMPTY_ERR="$("$IOS_TEST" -g '' --list 2>&1 >/dev/null)" && EMPTY_RC=0 || EMPTY_RC=$?
[[ "$EMPTY_RC" -eq 2 ]] && ok "空 pattern exit 2" || fail_t "空 pattern rc=${EMPTY_RC}（應 2）"
grep -q "空 pattern" <<<"$EMPTY_ERR" && ok "錯誤訊息明示拒絕原因" || fail_t "錯誤訊息缺拒絕原因: $EMPTY_ERR"

# ── 12. 零匹配錯誤訊息必須講清楚匹配語意（方法名＋suite/容器名，不對檔名）────
section "zero-match error message semantics"
ZERO_ERR="$("$IOS_TEST" -g zzz_no_such_test_zzz --list 2>&1 >/dev/null)" && ZERO_RC=0 || ZERO_RC=$?
[[ "$ZERO_RC" -ne 0 ]] && ok "零匹配 exit 非 0" || fail_t "零匹配竟 exit 0"
grep -q "方法名" <<<"$ZERO_ERR" && grep -q "容器名" <<<"$ZERO_ERR" && grep -q "檔名" <<<"$ZERO_ERR" \
  && ok "錯誤訊息說明匹配方法名＋suite/容器名、不匹配檔名" \
  || fail_t "錯誤訊息未說明匹配語意: $ZERO_ERR"

# ── 12b. -g 用 suite 名 E2E（--list；歷史摩擦：suite 名 → no tests matching
#         浪費一輪 ~270s build+test）。從真實測試自我發現一個 @Suite/struct 名。──
section "ios_test.sh -g suite-name (--list)"
SUITE_NAME="$(grep -rhoE '^(@Suite[^A-Za-z]*)?(final )?(struct|class) [A-Za-z0-9_]+' "$WORKSPACE/ios/BooksAndVocabTests" 2>/dev/null | grep -oE '[A-Za-z0-9_]+$' | sed -n '1p')"
if [[ -n "$SUITE_NAME" ]]; then
  SUITE_LIST="$("$IOS_TEST" -g "$SUITE_NAME" --list 2>/dev/null)" || SUITE_LIST=""
  N_SUITE="$(grep -c "only-testing:BooksAndVocabTests/$SUITE_NAME/" <<<"$SUITE_LIST" || true)"
  if (( N_SUITE >= 1 )); then
    ok "-g '$SUITE_NAME'（suite 名）resolve 出 $N_SUITE 個 selector"
  else
    fail_t "-g '$SUITE_NAME'（suite 名）零 selector：$SUITE_LIST"
  fi
else
  fail_t "找不到可用的真實 suite 名"
fi

# ── 13. --ui 缺 dataset 錯誤必須列出可用 UI World 名單（IMP-0011 迴歸）──────
section "--ui missing dataset lists available worlds"
DS_ERR="$("$IOS_TEST" --ui -g Foo 2>&1 >/dev/null)" && DS_RC=0 || DS_RC=$?
[[ "$DS_RC" -ne 0 ]] && ok "--ui 缺 dataset exit 非 0" || fail_t "--ui 缺 dataset 竟 exit 0"
grep -q "available datasets" <<<"$DS_ERR" && grep -q "marketing_demo" <<<"$DS_ERR" \
  && ok "錯誤列出可用 dataset 名單（含 marketing_demo）" \
  || fail_t "錯誤未列可用 dataset: $DS_ERR"

# ── 14. 裸方法名必須反查自身容器（IMP-0030）──────────────────────────────────
# 舊行為：非 `Class/method` 形式即硬拼 `$TEST_TARGET/$TEST_TARGET/$t`，把每個測試都
# 掛到「與 target 同名的 class」下。凡不住在該 class 的測試 → selector 0 匹配，
# 而 parse 期照樣 exit 0，要跑完一整輪 build+test 才被尾端 zero-executed guard 抓到。
section "bare method name resolves to its own container"
UI_DIR="$WORKSPACE/ios/BooksAndVocabUITests"
# 自我發現一個「容器 != BooksAndVocabUITests」的 UITest 方法（硬編會隨測試樹漂移）。
# 先整包收進變數再 awk：`producer | awk '...exit'` 會給 producer SIGPIPE，
# 在 `set -o pipefail` 下傳出 141 直接殺掉本腳本（IMP-0058 同一類地雷）。
UI_FLAGS="$(discover_only_flags "$UI_DIR" "" "BooksAndVocabUITests")"
FOREIGN="$(awk -F/ 'NF>=3 && $2 != "BooksAndVocabUITests" { print $2 "|" $3; exit }' <<<"$UI_FLAGS")"
FOREIGN_CLASS="${FOREIGN%%|*}"; FOREIGN_ID="${FOREIGN##*|}"; FOREIGN_BARE="${FOREIGN_ID%%(*}"
if [[ -n "$FOREIGN_CLASS" && -n "$FOREIGN_BARE" && "$FOREIGN_CLASS" != "BooksAndVocabUITests" ]]; then
  BARE_OUT="$("$IOS_TEST" --ui --list "$FOREIGN_BARE" 2>/dev/null)" || BARE_OUT=""
  grep -qxF -- "-only-testing:BooksAndVocabUITests/$FOREIGN_CLASS/$FOREIGN_ID" <<<"$BARE_OUT" \
    && ok "裸 $FOREIGN_BARE → ${FOREIGN_CLASS}（非 target 同名 class）" \
    || fail_t "裸方法未解析到自身容器 ${FOREIGN_CLASS}，實得：$BARE_OUT"
  PT_OUT="$("$IOS_TEST" --ui --list "$FOREIGN_CLASS/$FOREIGN_ID" 2>/dev/null)" || PT_OUT=""
  grep -qxF -- "-only-testing:BooksAndVocabUITests/$FOREIGN_CLASS/$FOREIGN_ID" <<<"$PT_OUT" \
    && ok "明確 Class/method 直通不變" || fail_t "Class/method 直通壞了：$PT_OUT"
else
  fail_t "找不到容器非 BooksAndVocabUITests 的 UITest 方法（FOREIGN='$FOREIGN'）"
fi

# ── 15. 不存在的裸方法名必須在 parse 期失敗（不得白跑一輪 build+test）─────────
section "unknown bare method fails at parse time"
BOGUS_ERR="$("$IOS_TEST" --ui --list zzzNoSuchBareMethodZzz 2>&1 >/dev/null)" && BOGUS_RC=0 || BOGUS_RC=$?
[[ "$BOGUS_RC" -ne 0 ]] && ok "不存在的裸方法 exit 非 0" \
  || fail_t "不存在的裸方法竟 exit 0（0 匹配的 selector 會被當成有效輸入送進 xcodebuild）"
# 只讀 stderr（`2>&1 >/dev/null`）：stdout 上任何含斜線的 selector 都不得滿足這條。
grep -q "Class/method" <<<"$BOGUS_ERR" \
  && ok "錯誤訊息指向 bare-method / Class/method 規則" \
  || fail_t "錯誤訊息未指向 bare-method 規則：$BOGUS_ERR"

# ── 16. Swift Testing 裸方法名必須帶簽名（無括號 id → xcodebuild 0 匹配）──────
section "bare Swift Testing method carries its signature"
UNIT_DIR="$WORKSPACE/ios/BooksAndVocabTests"
UNIT_FLAGS="$(discover_only_flags "$UNIT_DIR" "" "BooksAndVocabTests")"
SWIFT_PAIR="$(awk -F/ 'NF>=3 && $3 ~ /\(\)$/ { print $2 "|" $3; exit }' <<<"$UNIT_FLAGS")"
SWIFT_CLASS="${SWIFT_PAIR%%|*}"; SWIFT_FN="${SWIFT_PAIR##*|}"; SWIFT_BARE="${SWIFT_FN%%(*}"
if [[ -n "$SWIFT_CLASS" && -n "$SWIFT_BARE" ]]; then
  SW_OUT="$("$IOS_TEST" --list "$SWIFT_BARE" 2>/dev/null)" || SW_OUT=""
  grep -qxF -- "-only-testing:BooksAndVocabTests/$SWIFT_CLASS/$SWIFT_FN" <<<"$SW_OUT" \
    && ok "裸 $SWIFT_BARE → 帶簽名 $SWIFT_FN" \
    || fail_t "Swift Testing 裸名未帶簽名（xcodebuild 會 0 匹配），實得：$SW_OUT"
else
  fail_t "找不到 Swift Testing (@Test) 方法（SWIFT_PAIR='$SWIFT_PAIR'）"
fi

# ── 17. App Review live-demo 取證的實際命令形狀必須選到真的測試（IMP-0030）────
# 這條守的是 submission gate：ops/app_review_evidence.py 的 build_demo_run_command
# 以「裸方法名」呼叫 runner。期望值兩端都獨立於 ios_test.sh 與 discovery lib：
# 方法名讀自 caller 原始碼，class 名讀自 Swift 原始碼（本地 awk 反查最近的
# column-0 型別宣告），所以這條不可能被 runner 自己的輸出或本檔的 argv 滿足。
section "App Review live-demo command shape selects a real test"
DEMO_METHOD="$(awk -F'"' '/"--json", *"test/ { print $4; exit }' "$WORKSPACE/ops/app_review_evidence.py")"
DEMO_HITS="$(grep -rl "func ${DEMO_METHOD}(" "$UI_DIR" 2>/dev/null || true)"
DEMO_FILE="$(awk 'NR==1 { print; exit }' <<<"$DEMO_HITS")"
DEMO_CLASS=""
[[ -n "$DEMO_METHOD" && -n "$DEMO_FILE" ]] && DEMO_CLASS="$(awk -v fn="$DEMO_METHOD" '
  /^(final[ \t]+)?(public[ \t]+)?(class|struct|actor)[ \t]+[A-Za-z0-9_]+/ {
    name = $0
    sub(/^.*(class|struct|actor)[ \t]+/, "", name)
    sub(/[^A-Za-z0-9_].*$/, "", name)
    c = name
    next
  }
  $0 ~ ("func[ \t]+" fn "[ \t]*\\(") { print c; exit }
' "$DEMO_FILE")"
if [[ -n "$DEMO_METHOD" && -n "$DEMO_CLASS" ]]; then
  DEMO_SHA="$(printf 'd%.0s' {1..64})"
  DEMO_OUT="$("$IOS_TEST" --ui --configuration Release --evidence-kind exact-device \
    --destination 'platform=iOS,id=IMP0030-PLACEHOLDER' --live-demo \
    --live-demo-account-identity-sha256 "$DEMO_SHA" \
    --evidence-locale en_US --evidence-timezone UTC \
    --list "$DEMO_METHOD" 2>/dev/null)" || DEMO_OUT=""
  grep -qxF -- "-only-testing:BooksAndVocabUITests/$DEMO_CLASS/$DEMO_METHOD" <<<"$DEMO_OUT" \
    && ok "取證命令選到 $DEMO_CLASS/$DEMO_METHOD" \
    || fail_t "取證命令未選到 ${DEMO_CLASS}（0 匹配 = 送審證據什麼都沒證明），實得：$DEMO_OUT"
  # 缺陷簽章本身：這條若哪天 class == target 就退化成恆真，故明寫出來。
  [[ "$DEMO_CLASS" != "BooksAndVocabUITests" ]] \
    && ok "取證測試確實不住在 target 同名 class（本條非恆真）" \
    || fail_t "取證測試已搬進 BooksAndVocabUITests，本節失去鑑別力，需改測試樹或改斷言"
else
  fail_t "無法從 caller/Swift 原始碼推導取證身分（method='$DEMO_METHOD' file='$DEMO_FILE' class='$DEMO_CLASS'）"
fi

# ── result ────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
