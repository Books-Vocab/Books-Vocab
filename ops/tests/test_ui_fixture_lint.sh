#!/usr/bin/env bash
# test_ui_fixture_lint.sh — offline regression tests for ops/ui_fixture_lint.sh
#
# 為什麼存在（IMP-20260806-3ec803）：被測的那支 lint 的**唯一價值**是「錯的 id 會紅」。
# 一支只驗過正例的 lint 和一個 `exit 0` 的空檔案在 gate 上長得一模一樣 —— 而
# testBookshelfToReaderNavigation 之所以能紅著沒人發現數週，正是因為那條路徑上
# 沒有任何東西**能**變紅。所以本檔的重心是負控：注入 camelCase 假 id、注入結構性
# 破壞（enum 不見了、掃描目錄空了），逐一要求非零退出。
#
# 每個負控都同時是「env override 真的被讀了」的判別探針：real repo 綠 + 注入的
# 假目錄紅，兩者並存才證明 KG_UI_FIXTURE_SCAN_DIR 沒有被忽略；若 override 被忽略，
# 假目錄那筆會拿真 repo 的答案回來變綠，這裡就會失敗。
#
# 純文字檢查，不編譯、不開模擬器，可在 linux CI runner 跑。

set -uo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$WORKSPACE"
LINT="$WORKSPACE/ops/ui_fixture_lint.sh"
REAL_ENUM="$WORKSPACE/ios/BooksAndVocab/Support/Fixtures/Bookshelf/BookshelfFixtures.swift"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section(){ echo ""; echo "── $* ──"; }

TMP="$(mktemp -d -t kg_ui_fixture_lint_XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

OUT="$TMP/out.txt"

if [[ ! -x "$LINT" ]]; then
  echo "  ✗ ops/ui_fixture_lint.sh missing or not executable" >&2
  echo ""
  echo "ui-fixture-lint: 0 passed, 1 failed"
  exit 1
fi

# run_lint <scan_dir> [enum_file] -> echoes rc; combined output lands in $OUT
run_lint() {
  local dir="$1" enum_file="${2:-$REAL_ENUM}" rc=0
  KG_UI_FIXTURE_SCAN_DIR="$dir" KG_UI_FIXTURE_ENUM_FILE="$enum_file" \
    "$LINT" >"$OUT" 2>&1 || rc=$?
  echo "$rc"
}

dump() { sed 's/^/      /' "$OUT" >&2; }

# make_scan_dir <name> <swift body...> -> echoes the dir path
make_scan_dir() {
  local name="$1"; shift
  local dir="$TMP/scan_$name"
  mkdir -p "$dir"
  printf '%s\n' "$@" >"$dir/Injected${name}UITests.swift"
  echo "$dir"
}

section "help surface"
rc=0; "$LINT" --help >"$OUT" 2>&1 || rc=$?
if [[ "$rc" -eq 0 ]]; then ok "--help exits 0"; else fail_t "--help exits $rc"; dump; fi
if grep -q "Usage:" "$OUT"; then ok "--help prints Usage:"; else fail_t "--help has no Usage: block"; dump; fi

section "--list exposes the allowlist it is enforcing"
rc=0; "$LINT" --list >"$OUT" 2>&1 || rc=$?
if [[ "$rc" -eq 0 ]]; then ok "--list exits 0"; else fail_t "--list exits $rc"; dump; fi
if grep -qx "with_books_library" "$OUT"; then
  ok "--list prints the real rawValue with_books_library"
else
  fail_t "--list does not print with_books_library — the extractor is not reading BookshelfFixtureID"
  dump
fi
if grep -qx "withBooksLibrary" "$OUT"; then
  fail_t "--list printed the CASE NAME withBooksLibrary — the extractor grabbed the wrong half of 'case x = \"y\"'"
  dump
else
  ok "--list does not leak case names"
fi

section "positive control: the repo as it stands today is green"
rc=0; "$LINT" >"$OUT" 2>&1 || rc=$?
if [[ "$rc" -eq 0 ]]; then
  ok "lint on the real repo exits 0"
else
  fail_t "lint on the real repo exits $rc — either a real bad call site exists, or the lint is broken"
  dump
fi

section "negative control: a camelCase id in .bookshelf(\"…\") must be red"
dir="$(make_scan_dir Bad1 \
  'import XCTest' \
  'final class InjectedBad1UITests: XCTestCase {' \
  '    func testThing() {' \
  '        let app = launchIsolatedApp(fixtures: [.bookshelf("withBooksLibrary")])' \
  '    }' \
  '}')"
rc="$(run_lint "$dir")"
if [[ "$rc" -eq 1 ]]; then ok ".bookshelf(\"withBooksLibrary\") exits 1"; else
  fail_t ".bookshelf(\"withBooksLibrary\") exits $rc — expected 1 (0 = the lint cannot fail; 2 = it died structurally instead of judging)"; dump; fi
if grep -q "InjectedBad1UITests.swift:4:" "$OUT"; then
  ok "names the offending file and line"
else
  fail_t "output does not carry file:line — an operator cannot act on it"; dump; fi
if grep -q "withBooksLibrary" "$OUT"; then ok "names the offending id"; else fail_t "output does not name the id"; dump; fi
if grep -q "with_books_library" "$OUT"; then
  ok "suggests the snake_case rawValue (did-you-mean closes the loop)"
else
  fail_t "no did-you-mean for the camelCase→snake_case case this ticket is about"; dump; fi

section "negative control: a camelCase id in the raw launch argument must be red"
dir="$(make_scan_dir Bad2 \
  'import XCTest' \
  'final class InjectedBad2UITests: XCTestCase {' \
  '    func testThing() {' \
  '        let app = launchApp(extraArgs: ["-seedFixture:bookshelf:withBooksLibrary"])' \
  '    }' \
  '}')"
rc="$(run_lint "$dir")"
if [[ "$rc" -eq 1 ]]; then ok "-seedFixture:bookshelf:withBooksLibrary exits 1"; else
  fail_t "raw launch-argument form exits $rc — expected 1; this is the exact shape of the 12166519f regression"; dump; fi
if grep -q "InjectedBad2UITests.swift:4:" "$OUT"; then ok "names file:line for the raw-argument form"; else
  fail_t "raw-argument finding has no file:line"; dump; fi

section "negative control: a plausible-but-nonexistent snake_case id must be red"
# camelCase is not the only way to be wrong; a typo'd/renamed snake_case id has no
# did-you-mean to fall back on and must still fail on membership alone.
dir="$(make_scan_dir Bad3 \
  'let app = launchIsolatedApp(fixtures: [.bookshelf("with_book_library")])')"
rc="$(run_lint "$dir")"
if [[ "$rc" -eq 1 ]]; then ok "unknown snake_case id with_book_library exits 1"; else
  fail_t "unknown snake_case id exits $rc — expected 1; membership is not actually being checked"; dump; fi

section "formatter-wrapped and space-padded calls are still checked"
# swift-format wraps long calls, and `.bookshelf( "x" )` is legal Swift. A pattern that
# only matched `.bookshelf("` would go quiet on both — and, worse, quietly: a repo with
# four good sites plus one wrapped bad one would print `ok: 4 … all ids valid`, which is
# the exact silent shape this lint exists to abolish.
dir="$(make_scan_dir Bad5 \
  'let a = launchIsolatedApp(fixtures: [' \
  '    .bookshelf(' \
  '        "withBooksLibrary"' \
  '    )' \
  '])')"
rc="$(run_lint "$dir")"
if [[ "$rc" -eq 1 ]]; then ok "wrapped .bookshelf( \\n \"bad\" ) exits 1"; else
  fail_t "wrapped call exits $rc — expected 1"; dump; fi
if grep -q "InjectedBad5UITests.swift:3:" "$OUT"; then
  ok "reports the line holding the literal (:3), not the open paren"
else
  fail_t "wrapped finding points at the wrong line"; dump; fi

dir="$(make_scan_dir Bad6 'let a = launchIsolatedApp(fixtures: [.bookshelf( "withBooksLibrary" )])')"
rc="$(run_lint "$dir")"
if [[ "$rc" -eq 1 ]]; then ok "space-padded .bookshelf( \"bad\" ) exits 1"; else
  fail_t "space-padded call exits $rc — expected 1"; dump; fi

section "a half-literal interpolation is not accused of its own prefix"
# `-seedFixture:bookshelf:book_card_\(variant)` has no verifiable id. Reporting the
# literal prefix `book_card_` would be a false positive on a block gate — the fastest
# way to teach the next operator to route around this lint.
dir="$(make_scan_dir Good2 \
  'let arg = "-seedFixture:bookshelf:book_card_\(variant)"' \
  'let ok = launchIsolatedApp(fixtures: [.bookshelf("book_card_complete")])')"
rc="$(run_lint "$dir")"
if [[ "$rc" -eq 0 ]]; then ok "half-literal interpolation exits 0"; else
  fail_t "half-literal interpolation exits $rc — the literal prefix is being checked as if it were an id"; dump; fi

section "the escape hatch works, and only on the line that carries it"
# Without one, a regression note quoting the bad shape turns a fast-tier block gate red.
dir="$(make_scan_dir Good3 \
  '// Regression note (IMP-20260806-3ec803): this used to pass' \
  '// -seedFixture:bookshelf:withBooksLibrary and crashed the app.  // ui-fixture-allow: historical note' \
  'let ok = launchIsolatedApp(fixtures: [.bookshelf("with_books_library")])')"
rc="$(run_lint "$dir")"
if [[ "$rc" -eq 0 ]]; then ok "// ui-fixture-allow: suppresses that line"; else
  fail_t "escape hatch does not work (exit $rc) — a gate with no escape hatch gets routed around, not obeyed"; dump; fi

dir="$(make_scan_dir Bad7 \
  '// ui-fixture-allow: this comment must NOT cover the next line' \
  'let bad = launchIsolatedApp(fixtures: [.bookshelf("withBooksLibrary")])')"
rc="$(run_lint "$dir")"
if [[ "$rc" -eq 1 ]]; then ok "the hatch does not leak onto the following line"; else
  fail_t "one // ui-fixture-allow: silenced a different line (exit $rc) — that is a file-level mute wearing a line-level label"; dump; fi

section "false-positive guard: interpolated and non-literal forms must stay green"
# UITestAppLaunch.swift builds "-seedFixture:bookshelf:\(id)" and matches on
# `case .bookshelf(let id):`. If either reads as a finding the lint is unusable on
# its own repo and the first operator to meet it will route around it.
dir="$(make_scan_dir Good1 \
  'enum UITestFixture {' \
  '    case bookshelf(String)' \
  '    var launchArgument: String {' \
  '        switch self {' \
  '        case .bookshelf(let id):' \
  '            return "-seedFixture:bookshelf:\(id)"' \
  '        }' \
  '    }' \
  '}' \
  'let a = launchIsolatedApp(fixtures: [.bookshelf("with_books_library")])' \
  'let b = launchApp(extraArgs: ["-seedFixture:bookshelf:empty_library"])')"
rc="$(run_lint "$dir")"
if [[ "$rc" -eq 0 ]]; then
  ok "interpolation + pattern-match + valid literals exit 0"
else
  fail_t "false positive on interpolated/non-literal forms (exit $rc)"; dump; fi

section "every bad id in a file is reported, not just the first"
dir="$(make_scan_dir Bad4 \
  'let a = launchIsolatedApp(fixtures: [.bookshelf("emptyLibrary")])' \
  'let b = launchIsolatedApp(fixtures: [.bookshelf("loadingOverlay")])')"
rc="$(run_lint "$dir")"
if [[ "$rc" -eq 1 ]]; then ok "multi-finding file exits 1"; else fail_t "multi-finding file exits $rc — expected 1"; dump; fi
found=$(grep -c 'unknown bookshelf fixture id' "$OUT")
if [[ "$found" -eq 2 ]]; then
  ok "both bad ids reported (fixing one at a time is not a hidden second round-trip)"
else
  fail_t "expected 2 findings, got $found"; dump; fi

section "structural failure must be red, never silently green"
# An empty allowlist would make every call site 'unknown'; a lint that instead
# shrugged and exited 0 would go quiet the moment the enum is renamed or moved.
# rc is asserted exactly, not merely non-zero: 2 is a published contract (the plane's
# `verdict`, tech_index, --help). A regression collapsing structural failure into 1
# would make "unknown id" and "the lint is blind" indistinguishable to every caller.
printf 'struct NotAnEnum {}\n' >"$TMP/no_enum.swift"
rc="$(run_lint "$WORKSPACE/ios/BooksAndVocabUITests" "$TMP/no_enum.swift")"
if [[ "$rc" -eq 2 ]]; then ok "enum file without BookshelfFixtureID exits 2"; else
  fail_t "a file with no BookshelfFixtureID exits $rc — expected 2; renaming the enum must not silently disable the lint"; dump; fi

rc="$(run_lint "$TMP/does_not_exist_dir")"
if [[ "$rc" -eq 2 ]]; then ok "missing scan dir exits 2"; else
  fail_t "missing scan dir exits $rc — expected 2; moving the UITest folder must not silently disable the lint"; dump; fi

mkdir -p "$TMP/scan_empty"
printf 'not swift\n' >"$TMP/scan_empty/README.md"
rc="$(run_lint "$TMP/scan_empty")"
if [[ "$rc" -eq 2 ]]; then ok "scan dir with zero .swift files exits 2"; else
  fail_t "scanning zero files exits $rc — expected 2; the emptiest possible run must not be the greenest"; dump; fi

section "the scheduled sweep this ticket adds is actually runnable"
# The plist is the other half of IMP-20260806-3ec803: the lint catches id typos in
# seconds, the sweep is what makes the UI target run at all. A plist whose command
# exits 1 on argument parsing would look installed and cover nothing.
PLIST="$WORKSPACE/ops/launchd/com.kg.uisweep.plist"
if [[ -f "$PLIST" ]]; then ok "ops/launchd/com.kg.uisweep.plist exists"; else fail_t "ops/launchd/com.kg.uisweep.plist missing"; fi
if [[ -f "$PLIST" ]] && plutil -lint "$PLIST" >/dev/null 2>&1; then
  ok "plist parses (plutil -lint)"
elif ! command -v plutil >/dev/null 2>&1; then
  ok "plutil unavailable (linux runner) — parse check skipped"
else
  fail_t "plist does not parse"
fi
# Read the PARSED argument vector, never the raw file. The first version of this
# assertion grepped the whole plist and was satisfied by the XML comment explaining
# why --dataset is mandatory: deleting the flag from ProgramArguments left the test
# green. The prose written to justify a guard must not be what keeps it quiet.
if [[ -f "$PLIST" ]]; then
  if prog="$(plutil -extract ProgramArguments json -o - "$PLIST" 2>/dev/null)"; then
    :
  else
    prog="$(sed '/<!--/,/-->/d' "$PLIST")"   # linux fallback: strip comments, keep XML
  fi
  if grep -q -- '--dataset' <<<"$prog"; then
    ok "ProgramArguments carries --dataset (ios_test.sh:451 rejects a bare --ui with exit 1)"
  else
    fail_t "ProgramArguments has no --dataset — 'ios_ops.sh test --ui' alone exits 1 before running anything, so the job would fail daily and look installed"
  fi
  # Negative control for the probe itself: comment-only text must NOT satisfy it.
  # Without this, a future refactor could reintroduce the whole-file grep unnoticed.
  probe="$TMP/probe.plist"
  sed 's|<string>--dataset</string>||; s|<string>marketing_demo</string>||' "$PLIST" >"$probe"
  if prog2="$(plutil -extract ProgramArguments json -o - "$probe" 2>/dev/null)"; then
    :
  else
    prog2="$(sed '/<!--/,/-->/d' "$probe")"
  fi
  if grep -q -- '--dataset' <<<"$prog2"; then
    fail_t "stripping --dataset from ProgramArguments still reads as present — the assertion is looking at the comment, not the command"
  else
    ok "stripping the flag from ProgramArguments is detected (probe is discriminating)"
  fi
fi

echo ""
echo "ui-fixture-lint: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
