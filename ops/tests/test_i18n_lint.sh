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

echo "── an extractor crash fails --strict closed (invalid UTF-8 in a .swift file), never reads as clean ──"
mkdir -p "$TMP/crash"; cp -R "$FIX/clean/en.lproj" "$TMP/crash/en.lproj"
printf '\xff\xfe\x00bad' >"$TMP/crash/Bad.swift"
lint "$TMP/crash" --strict
expect "extractor crash" 1 "key extractor failed; coverage unverified" \
  "missing_key: <key extractor failed" "plural_missing: <key extractor failed"

echo "── Check C: plural key must be a valid plural entry in all 5 locales ──"
# the key extractor resolves paths relative to the repo root, so fixtures live under it (.cache is gitignored)
mkdir -p .cache; PL="$(mktemp -d "$PWD/.cache/i18n-plural.XXXXXX")"; trap 'rm -rf "$TMP" "$PL"' EXIT
mkplural() {  # $1 = dir, $2 = locale:ValueType:forms (space-sep, forms like "one,other"), ... overrides via PL_* env
  local d="$1" loc vt forms spec f
  mkdir -p "$d"
  printf 'let s = L10n.format("k_plural", Int64(3))\n' >"$d/App.swift"
  for loc in en zh-Hant zh-Hans ja ko; do
    mkdir -p "$d/$loc.lproj"
    [[ "$loc" == en ]] && printf '"k_plural" = "%%lld cards";\n' >"$d/$loc.lproj/Localizable.strings" \
      || : >"$d/$loc.lproj/Localizable.strings"
    vt=lld; forms="one other"; spec=NSStringPluralRuleType
    [[ "$loc" == "${PL_LOC:-}" ]] && { vt="${PL_VT:-lld}"; forms="${PL_FORMS:-one other}"; spec="${PL_SPEC:-NSStringPluralRuleType}"; }
    {
      echo '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
      if [[ "$loc" == "${PL_SKIP:-}" ]]; then :; else
        echo "<key>k_plural</key><dict><key>NSStringLocalizedFormatKey</key><string>%#@n@</string><key>n</key><dict>"
        echo "<key>NSStringFormatSpecTypeKey</key><string>$spec</string><key>NSStringFormatValueTypeKey</key><string>$vt</string>"
        for f in $forms; do echo "<key>$f</key><string>%lld x</string>"; done
        echo "</dict></dict>"
      fi
      echo '</dict></plist>'
    } >"$d/$loc.lproj/Localizable.stringsdict"
  done
}
mkplural "$PL/pl_ok"; lint "$PL/pl_ok" --strict
expect "valid 5-locale plural" 0
PL_LOC=ko PL_VT=d mkplural "$PL/pl_d"; lint "$PL/pl_d" --strict
expect "ValueType=d in ko" 1 "plural_type:" "k_plural" "[ko]"
PL_SKIP=ko mkplural "$PL/pl_noko"; lint "$PL/pl_noko" --strict
expect "no ko entry" 1 "plural_missing:" "k_plural" "ko"
PL_LOC=en PL_FORMS=other mkplural "$PL/pl_noone"; lint "$PL/pl_noone" --strict
expect "en lacks one" 1 "plural_form:" "k_plural" "[en]"
PL_LOC=en PL_FORMS=one mkplural "$PL/pl_noother"; lint "$PL/pl_noother" --strict
expect "en lacks other" 1 "plural_form:" "k_plural"
PL_LOC=ja PL_SPEC=NSStringVariableWidthRuleType mkplural "$PL/pl_spec"; lint "$PL/pl_spec" --strict
expect "non-plural SpecType in ja" 1 "plural_type:" "[ja]"
mkplural "$PL/pl_nofile"; rm "$PL/pl_nofile/zh-Hans.lproj/Localizable.stringsdict"; lint "$PL/pl_nofile" --strict
expect "missing stringsdict file" 1 "plural_missing:" "zh-Hans"
mkplural "$PL/pl_bad"; printf 'not a plist' >"$PL/pl_bad/ja.lproj/Localizable.stringsdict"; lint "$PL/pl_bad" --strict
expect "unparseable stringsdict" 1 "plural_missing:" "ja"

echo "── --strict fails with exit 2 when the baseline has no localized_calls= line ──"
printf 'findings=0\n' >"$TMP/nowm.txt"
rc=0; out="$(KG_I18N_SRC="$FIX/watermark" KG_I18N_BASELINE="$TMP/nowm.txt" ./ops/i18n_lint.sh --strict 2>&1)" || rc=$?
expect "strict without watermark" 2 "no localized_calls= watermark"

echo "── a malformed watermark fails closed with exit 2 (a non-numeric one made [ -gt ] error, read false, and pass) ──"
wm_lint() {  # $1 = mode, $2 = raw baseline body
  printf '%b' "$2" >"$TMP/badwm.txt"
  rc=0; out="$(KG_I18N_SRC="$FIX/watermark" KG_I18N_BASELINE="$TMP/badwm.txt" ./ops/i18n_lint.sh "$1" 2>&1)" || rc=$?
}
for mode in --strict --baseline-check; do
  wm_lint "$mode" 'findings=999\nlocalized_calls=abc\n'
  expect "$mode non-numeric watermark" 2 "malformed localized_calls watermark"
  wm_lint "$mode" 'findings=999\nlocalized_calls=\n'
  expect "$mode empty watermark" 2 "malformed localized_calls watermark"
  wm_lint "$mode" 'findings=999\nlocalized_calls=-1\n'
  expect "$mode negative watermark" 2 "malformed localized_calls watermark"
  wm_lint "$mode" 'findings=999\nlocalized_calls=1 \n'
  expect "$mode padded watermark" 2 "malformed localized_calls watermark"
  wm_lint "$mode" 'findings=999\nlocalized_calls=5\nlocalized_calls=6\n'
  expect "$mode duplicated watermark" 2 "duplicate localized_calls watermark"
  wm_lint "$mode" 'findings=999\nlocalized_calls=1\n'
  expect "$mode valid watermark (positive control)" 0 "ok"
done
wm_lint --baseline-check 'findings=abc\nlocalized_calls=1\n'
expect "--baseline-check non-numeric findings baseline" 2 "malformed findings baseline"
wm_lint --baseline-check 'findings=9\nfindings=9\nlocalized_calls=1\n'
expect "--baseline-check duplicated findings baseline" 2 "malformed findings baseline"
wm_lint --baseline-check 'findings=999\n'
expect "--baseline-check legacy baseline without watermark still passes" 0 "ok"

echo "── CI contract: every PR runs i18n_lint --strict, and .lproj diffs select it ──"
grep -qF 'ui_quality_gate.sh --tier fast --execute --all-mechanisms' .github/workflows/ui-quality-gate.yml \
  && ok "ui-quality-gate workflow runs the fast tier on all mechanisms" \
  || fail_t "ui-quality-gate workflow no longer runs --tier fast --execute --all-mechanisms"
rc=0; out="$(./ops/ui_quality_gate.sh --tier fast --all-mechanisms --dry-run 2>&1)" || rc=$?
expect "CI plan" 0 "ops/i18n_lint.sh --strict"
rc=0; out="$(./ops/ui_quality_gate.sh --tier fast --dry-run --files ios/BooksAndVocab/en.lproj/Localizable.strings 2>&1)" || rc=$?
expect ".lproj-only diff" 0 "static.i18n"
rc=0; out="$(./ops/ui_quality_gate.sh --tier fast --dry-run --files ios/BooksAndVocab/en.lproj/Localizable.stringsdict 2>&1)" || rc=$?
expect ".stringsdict-only diff" 0 "static.i18n"

echo ""
echo "i18n-lint: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
