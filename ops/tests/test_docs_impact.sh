#!/usr/bin/env bash
# Regression tests for registry-backed docs impact hints.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/kg_docs_impact.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

./ops/docs_impact.py --files ops/docs_lint.sh >"$tmpdir/ops.out"
grep -q "reference.tech_index" "$tmpdir/ops.out"
grep -q "sop.doc_sync" "$tmpdir/ops.out"
if grep -q "contract.host_topology" "$tmpdir/ops.out"; then
  echo "docs tooling changes should not imply host topology impact" >&2
  exit 1
fi
if grep -q "policy.safety" "$tmpdir/ops.out"; then
  echo "docs tooling changes should not imply production safety impact" >&2
  exit 1
fi
if grep -q "reference.product_surface" "$tmpdir/ops.out"; then
  echo "docs tooling changes should not imply product surface impact" >&2
  exit 1
fi
if grep -q "sop.deploy" "$tmpdir/ops.out"; then
  echo "docs tooling changes should not imply deploy workflow impact" >&2
  exit 1
fi
if grep -q "sop.debug" "$tmpdir/ops.out"; then
  echo "docs tooling changes should not imply debug workflow impact" >&2
  exit 1
fi

./ops/docs_impact.py --files docs/registry.yml >"$tmpdir/registry.out"
grep -q "sop.doc_sync" "$tmpdir/registry.out"

./ops/docs_impact.py --files ios/BooksBrowser/Views/Reader/ReaderView.swift >"$tmpdir/ios.out"
grep -q "contract.sync_lifecycle" "$tmpdir/ios.out"
grep -q "generated.ios_baseline" "$tmpdir/ios.out"

./ops/docs_impact.py --files README.md >"$tmpdir/none.out"
grep -q "docs_impact: no registry impacts" "$tmpdir/none.out"

./ops/docs_impact.py --files backend/src/kg/routers/vocab.py --json >"$tmpdir/backend.json"
grep -q '"id": "reference.tech_index"' "$tmpdir/backend.json"
grep -q '"id": "contract.sync_lifecycle"' "$tmpdir/backend.json"
