#!/usr/bin/env bash
# test_ci_scope_router.sh — prove confidence routing is selective but fail-closed.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ROUTER="$ROOT/ops/ci_scope_router.sh"

failures=0
pass() {
  printf '✓ %s\n' "$1"
}

fail() {
  printf '✗ %s\n' "$1" >&2
  failures=$((failures + 1))
}

assert_plan() {
  local label="$1"
  local paths="$2"
  local expected="$3"
  local actual

  if ! actual="$(printf '%s\n' "$paths" | "$ROUTER" --paths-stdin --format json)"; then
    fail "$label: router command failed"
    return
  fi

  # Only the three suite booleans are asserted here; iOS selector routing has
  # its own assertions below (assert_ios_route).
  if jq -e -n --argjson actual "$actual" --argjson expected "$expected" \
    '($actual | {backend, ops, ios}) == $expected' >/dev/null; then
    pass "$label"
  else
    fail "$label: expected $expected, got $actual"
  fi
}

assert_plan 'backend source selects only backend confidence' \
  'backend/src/kg/app.py' \
  '{"backend":true,"ops":false,"ios":false}'
assert_plan 'iOS source selects only iOS confidence' \
  'ios/BooksAndVocab/App.swift' \
  '{"backend":false,"ops":false,"ios":true}'
assert_plan 'ordinary ops source stays off macOS' \
  'ops/backup_verify.sh' \
  '{"backend":false,"ops":true,"ios":false}'
assert_plan 'iOS shared helper selects ops plus iOS' \
  'ops/lib/project_python.sh' \
  '{"backend":false,"ops":true,"ios":true}'
assert_plan 'lab/podcast source selects only ops confidence (Issue #2064)' \
  'lab/podcast/pipeline.py' \
  '{"backend":false,"ops":true,"ios":false}'
assert_plan 'lab/podcast monitor test selects only ops confidence (Issue #2064)' \
  'lab/podcast/monitor/test_server.py' \
  '{"backend":false,"ops":true,"ios":false}'
assert_plan 'docs-only change avoids unrelated confidence suites' \
  'docs/reference/testing/smoke_checklist.md' \
  '{"backend":false,"ops":false,"ios":false}'
assert_plan 'PR-gate policy change reruns all confidence suites' \
  '.github/workflows/pr-gate.yml' \
  '{"backend":true,"ops":true,"ios":true}'
assert_plan 'confidence verdict policy change reruns all confidence suites' \
  'ops/ci_confidence_verdict.sh' \
  '{"backend":true,"ops":true,"ios":true}'
assert_plan 'confidence verdict contract test reruns all confidence suites' \
  'ops/tests/test_ci_confidence_verdict.sh' \
  '{"backend":true,"ops":true,"ios":true}'
assert_plan 'devops skill roster change selects only backend confidence' \
  '.claude/skills/devops/SKILL.md' \
  '{"backend":true,"ops":false,"ios":false}'
assert_plan 'unknown source fails closed to all confidence suites' \
  'new-top-level-runtime-config.toml' \
  '{"backend":true,"ops":true,"ios":true}'

if actual="$($ROUTER --all --format json)" \
  && jq -e -n --argjson actual "$actual" '$actual == {backend: true, ops: true, ios: true, ios_mode: "full", ios_selectors: ""}' >/dev/null; then
  pass 'manual mode selects all confidence suites'
else
  fail 'manual mode does not select all confidence suites'
fi

if "$ROUTER" --format json >/dev/null 2>&1; then
  fail 'router accepts a missing change source'
else
  pass 'router rejects a missing change source'
fi

if actual="$($ROUTER --base HEAD --head HEAD --format json)" \
  && jq -e -n --argjson actual "$actual" '$actual == {backend: false, ops: false, ios: false, ios_mode: "full", ios_selectors: ""}' >/dev/null; then
  pass 'git commit mode classifies an empty diff'
else
  fail 'git commit mode does not classify an empty diff'
fi


# ---------------------------------------------------------------------------
# iOS selector routing (Issue #1051). Targeted is an allow-list of exactly one
# shape; every other input must keep ios_mode=full with no selectors, because a
# wrong "targeted" answer silently skips confidence tests.
# ---------------------------------------------------------------------------
STUBS="$(mktemp -d)"
trap 'rm -rf "$STUBS"' EXIT

make_stub() {
  local name="$1" body="$2"
  # Every stub also asserts the exact discovery argv the router must use.
  {
    printf '#!/usr/bin/env bash\n'
    printf '[[ "$1 $2 $3" == "--ui --list --file" ]] || { echo "bad argv: $*" >&2; exit 64; }\n'
    printf '%s\n' "$body"
  } > "$STUBS/$name"
  chmod +x "$STUBS/$name"
}

make_stub ok 'echo "[ios_test] matched 2 tests in file x (BooksAndVocabUITests)"
echo "-only-testing:BooksAndVocabUITests/OverviewFlowUITests/testA"
echo "-only-testing:BooksAndVocabUITests/OverviewFlowUITests/testB"'
make_stub no-header 'echo "-only-testing:BooksAndVocabUITests/OverviewFlowUITests/testA"'
make_stub fail 'echo "[ios_test] no tests discovered in file" >&2; exit 1'
make_stub fail-with-output 'echo "-only-testing:BooksAndVocabUITests/OverviewFlowUITests/testA"; exit 1'
make_stub empty 'exit 0'
make_stub suite-only 'echo "-only-testing:BooksAndVocabUITests/OverviewFlowUITests"'
make_stub target-only 'echo "-only-testing:BooksAndVocabUITests"'
make_stub foreign-target 'echo "-only-testing:BooksAndVocabTests/OverviewFlowUITests/testA"'
make_stub noise 'echo "-only-testing:BooksAndVocabUITests/OverviewFlowUITests/testA"
echo "warning: something unexpected"'
make_stub count-mismatch 'echo "[ios_test] matched 5 tests in file x (BooksAndVocabUITests)"
echo "-only-testing:BooksAndVocabUITests/OverviewFlowUITests/testA"'
make_stub extra-segment 'echo "-only-testing:BooksAndVocabUITests/OverviewFlowUITests/testA/extra"'
make_stub shell-meta 'echo "-only-testing:BooksAndVocabUITests/OverviewFlowUITests/test;rm"'

OVERVIEW='ios/BooksAndVocabUITests/OverviewFlowUITests.swift'

# assert_ios_route <label> <paths> <stub> <expected-mode> <expected-selectors>
assert_ios_route() {
  local label="$1" paths="$2" stub="$3" mode="$4" selectors="$5" actual

  if ! actual="$(printf '%s\n' "$paths" | KG_CI_IOS_SELECTOR_DISCOVERY="$STUBS/$stub" "$ROUTER" --paths-stdin --format json)"; then
    fail "$label: router command failed"
    return
  fi
  if jq -e -n --argjson actual "$actual" --arg mode "$mode" --arg sel "$selectors" \
    '$actual.ios_mode == $mode and $actual.ios_selectors == $sel' >/dev/null; then
    pass "$label"
  else
    fail "$label: expected mode=$mode selectors='$selectors', got $actual"
  fi
}

# Positive: the one admitted shape, with exact Suite/Method selectors (the form
# `ios_test.sh <selector>` accepts), and the plan keeps ios=true only.
assert_ios_route 'single top-level UITests file with discovered selectors is targeted' \
  "$OVERVIEW" ok targeted \
  'OverviewFlowUITests/testA OverviewFlowUITests/testB'
assert_ios_route 'discovery without the ios_test header is accepted when selectors are exact' \
  "$OVERVIEW" no-header targeted 'OverviewFlowUITests/testA'

# A UITests file that a BooksAndVocabTests source contract reads by path
# (ReviewCardEvidenceContractTests, SettingsFixturesTests) is input to the unit
# lane. Targeted mode skips that lane, so such a change must stay full or a
# contract violation merges green (Issue #2114).
for case_path in \
  'ios/BooksAndVocabUITests/ReviewCardLayoutEditorUITests.swift' \
  'ios/BooksAndVocabUITests/SettingsFlowUITests.swift'; do
  assert_ios_route "UITests file read by a unit-test source contract stays full: $case_path" \
    "$case_path" ok full ''
done

# Negative: inputs that would silently lose coverage must fall back to full.
assert_ios_route 'two UITests files fall back to full' \
  "$OVERVIEW
ios/BooksAndVocabUITests/SearchFlowUITests.swift" ok full ''
assert_ios_route 'the same UITests path twice falls back to full' \
  "$OVERVIEW
$OVERVIEW" ok full ''
assert_ios_route 'UITests file plus docs change falls back to full' \
  "$OVERVIEW
docs/reference/tech_index.md" ok full ''
assert_ios_route 'UITests file plus app source falls back to full' \
  "$OVERVIEW
ios/BooksAndVocab/App.swift" ok full ''
assert_ios_route 'UITests file plus ops source falls back to full' \
  "$OVERVIEW
ops/backup_verify.sh" ok full ''
assert_ios_route 'UITests file plus backend source falls back to full' \
  "$OVERVIEW
backend/src/kg/app.py" ok full ''
for case_path in \
  'ios/BooksAndVocabUITests/Helpers/UITestDiagnosticsUITests.swift' \
  'ios/BooksAndVocabUITests/Pages/LoginPageUITests.swift' \
  'ios/BooksAndVocabUITests/FixtureDatasetUITests.swift' \
  'ios/BooksAndVocabUITests/SharedHelperUITests.swift' \
  'ios/BooksAndVocabUITests/PageObjectUITests.swift' \
  'ios/BooksAndVocabUITests/UITestLaunchSupport.swift' \
  'ios/BooksAndVocabUITests/UITestsSupportUITests.swift' \
  'ios/BooksAndVocabUITests/Sub/NestedUITests.swift' \
  'ios/BooksAndVocabUITests/../BooksAndVocab/EvilUITests.swift' \
  'ios/BooksAndVocabUITests/OverviewFlowUITests.swift.bak' \
  'ios/BooksAndVocabUITests/OverviewFlowTests.swift' \
  'ios/BooksAndVocabUITests/Overview FlowUITests.swift' \
  'ios/BooksAndVocabUITests/Overview;FlowUITests.swift' \
  'ios/BooksAndVocabTests/OverviewFlowUITests.swift' \
  'ios/BooksAndVocab/Views/OverviewFlowUITests.swift' \
  'ios/BooksAndVocab.xcodeproj/project.pbxproj' \
  'ios/BooksAndVocab/Debug/Scenarios/StatsViewScenarios.swift' \
  'ios/BooksAndVocab/Views/Vocabulary/Scenes/StatsPresenter.swift' \
  'ios/BooksAndVocabUITests/NotARealFileUITests.swift'; do
  # A permissive stub proves the path rules, not discovery, reject these.
  assert_ios_route "ineligible iOS path falls back to full: $case_path" "$case_path" ok full ''
done
for case_path in \
  '.github/workflows/ios-quality.yml' \
  '.github/workflows/pr-gate.yml' \
  'ops/ci_scope_router.sh' \
  'ops/ci_confidence_verdict.sh' \
  'ops/ios_test.sh' \
  'ops/lib/ios_test_discovery.sh' \
  'ops/tests/test_ci_scope_router.sh' \
  'ops/tests/test_github_workflows.sh' \
  'new-top-level-runtime-config.toml'; do
  assert_ios_route "policy/unknown path falls back to full: $case_path" "$case_path" ok full ''
done
assert_ios_route 'docs-only change reports full (no iOS selection to narrow)' \
  'docs/reference/tech_index.md' ok full ''

# Discovery must be exact; any doubt returns to the full suite.
for bad_stub in fail fail-with-output empty suite-only target-only foreign-target noise count-mismatch extra-segment shell-meta; do
  assert_ios_route "discovery '$bad_stub' falls back to full" "$OVERVIEW" "$bad_stub" full ''
done
assert_ios_route 'missing discovery command falls back to full' \
  "$OVERVIEW" nonexistent-stub full ''

# Manual/--all never narrows, even with a permissive discovery stub.
if actual="$(KG_CI_IOS_SELECTOR_DISCOVERY="$STUBS/ok" "$ROUTER" --all --format github-output)" \
  && grep -qx 'ios_mode=full' <<<"$actual" && grep -qx 'ios_selectors=' <<<"$actual"; then
  pass '--all keeps ios_mode=full with empty selectors'
else
  fail '--all narrowed the iOS suite'
fi

# github-output carries both keys for the workflow, and selectors stay single-line.
if actual="$(printf '%s\n' "$OVERVIEW" | KG_CI_IOS_SELECTOR_DISCOVERY="$STUBS/ok" "$ROUTER" --paths-stdin --format github-output)" \
  && grep -qx 'ios_mode=targeted' <<<"$actual" \
  && grep -qx 'ios_selectors=OverviewFlowUITests/testA OverviewFlowUITests/testB' <<<"$actual" \
  && [[ "$(wc -l <<<"$actual" | tr -d ' ')" == 5 ]]; then
  pass 'github-output exposes ios_mode and single-line ios_selectors'
else
  fail "github-output routing keys wrong: $actual"
fi

# Commit-range mode is NUL-safe: exercise it against a throwaway repository so
# renames (two paths) and hostile filenames (embedded newline) are real diffs.
REPO="$STUBS/repo"
mkdir -p "$REPO/ios/BooksAndVocabUITests"
(
  cd "$REPO"
  git init -q
  git config user.email t@example.invalid
  git config user.name t
  printf 'a\n' > "ios/BooksAndVocabUITests/OverviewFlowUITests.swift"
  printf 'a\n' > "ios/BooksAndVocabUITests/OldNameUITests.swift"
  git add -A
  git commit -q -m base
  printf 'b\n' >> "ios/BooksAndVocabUITests/OverviewFlowUITests.swift"
  git commit -q -am single
  git mv ios/BooksAndVocabUITests/OldNameUITests.swift ios/BooksAndVocabUITests/NewNameUITests.swift
  git commit -q -m rename
  printf 'x\n' > "$(printf 'ios/BooksAndVocabUITests/Evil\nUITests.swift')"
  git add -A
  git commit -q -m newline
)
range_mode() {
  (cd "$REPO" && KG_CI_IOS_SELECTOR_DISCOVERY="$STUBS/ok" "$ROUTER" --base "$1" --head "$2" --format json | jq -r .ios_mode)
}
if [[ "$(range_mode HEAD~3 HEAD~2)" == targeted ]]; then
  pass 'commit-range mode admits a single modified UITests file'
else
  fail 'commit-range mode did not admit a single modified UITests file'
fi
if [[ "$(range_mode HEAD~2 HEAD~1)" == full ]]; then
  pass 'commit-range rename (delete+add) falls back to full'
else
  fail 'commit-range rename was narrowed'
fi
if [[ "$(range_mode HEAD~1 HEAD)" == full ]]; then
  pass 'commit-range hostile newline filename falls back to full'
else
  fail 'commit-range hostile filename was narrowed'
fi

if (( failures > 0 )); then
  printf 'ci scope router: %d failure(s)\n' "$failures" >&2
  exit 1
fi

printf 'ci scope router: PASS\n'
