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

if rg -n --glob '*.swift' '@testable import BooksAndVocab' "$ROOT/ios/BooksAndVocabUITests" >/dev/null; then
  echo "FAIL: UI tests must not import app internals; use accessibility contracts" >&2
  exit 1
fi

if rg -n --glob '*.swift' '^import BooksAndVocab$' "$ROOT/ios/BooksAndVocabUITests" >/dev/null; then
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
