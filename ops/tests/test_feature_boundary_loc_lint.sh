#!/usr/bin/env bash
# Regression tests for the feature-boundary documentation LOC guard.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

fixture="docs/reference/feature_boundary/.lint_test_loc_guard.md"
output="$(mktemp "${TMPDIR:-/tmp}/kg_feature_boundary_loc_lint.XXXXXX")"
cleanup() {
  rm -f "$fixture" "$output"
}
trap cleanup EXIT

write_fixture() {
  body="$1"
  cat >"$fixture" <<EOF
<!-- doc-meta
tier: reference
authority: SoT
update_trigger: manual
scope:
  - ops/docs_lint.sh
verified_against: HEAD
-->
# Synthetic feature-boundary fixture

$body
EOF
}

assert_rejected() {
  if ./ops/docs_lint.sh --files "$fixture" >"$output" 2>&1; then
    echo "feature-boundary LOC fixture unexpectedly passed docs_lint" >&2
    cat "$output" >&2
    exit 1
  fi
  grep -q "feature-boundary" "$output"
  grep -q "行數" "$output"
}

write_fixture '| 檔案 | 行數 | 說明 |
| --- | ---: | --- |
| `ReviewCardView.swift` | card renderer |'
assert_rejected

write_fixture '| 檔案 | 說明 |
| --- | --- |
| `ReviewCardView.swift` | 869 |'
assert_rejected

write_fixture '| 檔案 | 說明 |
| --- | --- |
| `ReviewCardView.swift` | ~869 |'
assert_rejected

write_fixture '| 檔案 | 說明 |
| --- | --- |
| `ReviewCardView.swift` | card renderer；效能 budget 60ms（2026-08-10） |'
if ! ./ops/docs_lint.sh --files "$fixture" >"$output" 2>&1; then
  echo "feature-boundary file/responsibility fixture unexpectedly failed docs_lint" >&2
  cat "$output" >&2
  exit 1
fi
grep -q "ERROR: 0" "$output"

echo "PASS test_feature_boundary_loc_lint"
