#!/usr/bin/env bash
# Regression: UI tests must declare the package products needed by their
# helpers while remaining black-box XCTest bundles (no app-module linkage).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT="$ROOT/ios/BooksAndVocab.xcodeproj/project.pbxproj"

ui_block="$(awk '
  /E9EC4E2A2F4DD27200C3FFB6 \/\* BooksAndVocabUITests \*\// { in_target=1 }
  in_target { print }
  in_target && /productType = "com.apple.product-type.bundle.ui-testing"/ { exit }
' "$PROJECT")"

[[ -n "$ui_block" ]] || {
  echo "FAIL: could not locate BooksAndVocabUITests target" >&2
  exit 1
}

for product in \
  ReadiumShared \
  ReadiumStreamer \
  ReadiumNavigator \
  ReadiumAdapterGCDWebServer \
  GoogleSignIn \
  GoogleSignInSwift \
  PlaybookUI; do
  grep -Fq "/* $product */" <<<"$ui_block" || {
    echo "FAIL: BooksAndVocabUITests does not declare package product $product" >&2
    exit 1
  }
done

UI_TESTS_DIR="$ROOT/ios/BooksAndVocabUITests"
[[ -d "$UI_TESTS_DIR" ]] || {
  echo "FAIL: $UI_TESTS_DIR is missing" >&2
  exit 1
}

# swift_matches <ERE> <path>: status 0 = a .swift file matches (lines are
# printed), 1 = none. grep, not rg: the hosted macOS runner image ships no
# ripgrep, and in an `if rg ...; then FAIL` guard a missing binary reads as "no
# match", so the check would pass while enforcing nothing. Only grep's own
# "no match" status counts as clean; any other failure (2 = error) aborts the
# guard. Call it directly in `if`, never inside $(...): `exit` there would only
# end the subshell and turn the failure back into silence.
swift_matches() {
  local rc=0
  grep -rEn --include='*.swift' -e "$1" "$2" || rc=$?
  [[ "$rc" -le 1 ]] || {
    echo "FAIL: grep error ($rc) scanning $2" >&2
    exit 1
  }
  return "$rc"
}

# Positive control: the scan must see a planted violation and stay quiet on a
# clean tree, otherwise the two guards below prove nothing.
control_dir="$(mktemp -d)"
trap 'rm -rf "$control_dir"' EXIT
printf '@testable import BooksAndVocab\n' >"$control_dir/Testable.swift"
printf 'import BooksAndVocab\n' >"$control_dir/Linked.swift"
printf 'import XCTest\n' >"$control_dir/Clean.swift"
if swift_matches '@testable import BooksAndVocab' "$control_dir" >/dev/null \
  && swift_matches '^import BooksAndVocab$' "$control_dir" >/dev/null \
  && ! swift_matches '@testable import BooksAndVocab' "$control_dir/Clean.swift" >/dev/null \
  && ! swift_matches '^import BooksAndVocab$' "$control_dir/Clean.swift" >/dev/null; then
  :
else
  echo "FAIL: import scan control did not detect a planted violation" >&2
  exit 1
fi

if swift_matches '@testable import BooksAndVocab' "$UI_TESTS_DIR"; then
  echo "FAIL: UI tests must not import app internals; use accessibility contracts" >&2
  exit 1
fi

if swift_matches '^import BooksAndVocab$' "$UI_TESTS_DIR"; then
  echo "FAIL: UI tests must not link the app module; keep contracts inside the black-box target" >&2
  exit 1
fi

for config in E9EC4E3C2F4DD27200C3FFB6 E9EC4E3D2F4DD27200C3FFB6; do
  config_block="$(awk -v id="$config" '
    $0 ~ id " \/\*" { in_config=1 }
    in_config { print }
    in_config && /name = (Debug|Release);/ { exit }
  ' "$PROJECT")"
  if grep -Eq 'TEST_HOST|BUNDLE_LOADER' <<<"$config_block"; then
    echo "FAIL: BooksAndVocabUITests must not set TEST_HOST/BUNDLE_LOADER" >&2
    exit 1
  fi
done

echo "PASS: BooksAndVocabUITests package graph and black-box target contract"
