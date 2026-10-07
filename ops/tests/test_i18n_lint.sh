#!/usr/bin/env bash
# Behavioral tests for the .strings/.stringsdict rules of ops/i18n_lint.sh, run
# against checked-in fixture trees (KG_I18N_SRC) and a scratch baseline
# (KG_I18N_BASELINE), never the live app or ops/i18n_baseline.txt.
#
# Why the duplicate-key rule exists: a key defined twice in one file is legal to
# plutil -lint, and CFPropertyList keeps the LAST value. en.lproj had
# "關閉" = "Close" and later "關閉" = "Off", so every Close button read "Off".
set -euo pipefail
cd "$(dirname "$0")/../.."

FIX=ops/tests/fixtures/i18n_lint
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
lint() {  # $1 = fixture root, $2 = mode, $3 = localized_calls watermark (default: loose 999)
  printf 'findings=999\nlocalized_calls=%s\n' "${3:-999}" >"$TMP/baseline.txt"
  rc=0; out="$(KG_I18N_SRC="$1" KG_I18N_BASELINE="$TMP/baseline.txt" ./ops/i18n_lint.sh "$2" 2>&1)" || rc=$?
}
expect() {  # $1 = label, $2 = wanted exit, $3.. = fixed strings the output must contain
  local label="$1" want="$2" s; shift 2
  [[ "$rc" == "$want" ]] && ok "$label: exit $rc" || fail_t "$label: exit $rc, want $want"
  for s in "$@"; do grep -qF -- "$s" <<<"$out" && ok "$label names: $s" || fail_t "$label missing: $s"; done
}

echo "── a key twice in one file fails every gating mode, whatever the baseline (once per locale is fine) ──"
d="$FIX/dup/en.lproj/Localizable"
for mode in --baseline-check --strict --baseline; do
  lint "$FIX/dup" "$mode"
  expect "dup $mode" 1 " dup=2 " "they cannot be baselined" \
    "$d.strings:4: duplicate key \"關閉\", first at $d.strings:2: \"Close\" -> \"Off\"" \
    "$d.stringsdict:15: duplicate key \"%d 個單字\", first at $d.stringsdict:5"
done
grep -q '^findings=999$' "$TMP/baseline.txt" && ok "--baseline left the baseline untouched" \
  || fail_t "--baseline wrote a baseline despite duplicate keys"
lint "$FIX/dup" --report
expect "dup --report (discovery only)" 0 " dup=2 "

echo "── comments, escaped quotes and multi-line values are not definitions ──"
lint "$FIX/clean" --baseline
expect "clean --baseline" 0 " dup=0 " "baseline written to"

echo "── an unparseable file or an empty root fails closed instead of reading as clean ──"
lint "$FIX/broken" --baseline-check
expect "broken" 1 "$FIX/broken/en.lproj/Localizable.strings:2: unparseable:"
lint "$TMP" --baseline-check
expect "no localization files" 1 "no .strings files under"

echo "── --strict also enforces the localized_calls watermark ──"
lint "$FIX/watermark" --strict 1
expect "strict at watermark" 0 "ok strict: 0 findings, localized_calls 1 <= baseline 1"
lint "$FIX/watermark" --strict 0
expect "strict over watermark" 1 "REGRESSION: localized_calls 1 > baseline 0"

echo "── CI contract: every PR runs i18n_lint --strict, and .lproj diffs select it ──"
grep -qF 'ui_quality_gate.sh --tier fast --execute --all-mechanisms' .github/workflows/ui-quality-gate.yml \
  && ok "ui-quality-gate workflow runs the fast tier on all mechanisms" \
  || fail_t "ui-quality-gate workflow no longer runs --tier fast --execute --all-mechanisms"
rc=0; out="$(./ops/ui_quality_gate.sh --tier fast --all-mechanisms --dry-run 2>&1)" || rc=$?
expect "CI plan" 0 "ops/i18n_lint.sh --strict"
rc=0; out="$(./ops/ui_quality_gate.sh --tier fast --dry-run --files ios/BooksAndVocab/en.lproj/Localizable.strings 2>&1)" || rc=$?
expect ".lproj-only diff" 0 "static.i18n"

echo ""
echo "i18n-lint: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
