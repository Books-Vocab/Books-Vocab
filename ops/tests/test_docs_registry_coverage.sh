#!/usr/bin/env bash
# Regression tests for docs registry coverage reporting.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/kg_docs_registry_coverage.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

./ops/docs_registry_coverage.py >"$tmpdir/coverage.out"
grep -q "docs_registry_coverage:" "$tmpdir/coverage.out"
grep -q "registered=" "$tmpdir/coverage.out"
grep -q "unregistered=" "$tmpdir/coverage.out"
grep -q "docs/reference/feature_boundary/reader.md" "$tmpdir/coverage.out"

./ops/docs_registry_coverage.py --json >"$tmpdir/coverage.json"
grep -q '"registered_count"' "$tmpdir/coverage.json"
grep -q '"unregistered_by_tier"' "$tmpdir/coverage.json"
grep -q '"docs/reference/feature_boundary/reader.md"' "$tmpdir/coverage.json"

if ./ops/docs_registry_coverage.py --strict >"$tmpdir/strict.out" 2>&1; then
  echo "docs_registry_coverage --strict unexpectedly passed despite unregistered active docs" >&2
  exit 1
fi
grep -q "STRICT FAIL" "$tmpdir/strict.out"
