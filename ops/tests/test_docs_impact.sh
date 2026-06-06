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
if grep -q "contract.sync_lifecycle" "$tmpdir/ios.out"; then
  echo "ordinary reader view changes should not imply sync lifecycle contract impact" >&2
  exit 1
fi
grep -q "generated.ios_baseline" "$tmpdir/ios.out"
grep -q "reference.feature_boundary.reader" "$tmpdir/ios.out"

./ops/docs_impact.py --files ios/BooksBrowser/Views/Settings/SettingsView.swift >"$tmpdir/settings.out"
if grep -q "contract.sync_lifecycle" "$tmpdir/settings.out"; then
  echo "ordinary settings view changes should not imply sync lifecycle contract impact" >&2
  exit 1
fi
grep -q "reference.feature_boundary.settings" "$tmpdir/settings.out"

./ops/docs_impact.py --files ios/BooksBrowser/Services/KGService+Sync.swift ios/BooksBrowser/Views/Vocabulary/Scenes/SyncCoordinator.swift >"$tmpdir/sync_sources.out"
grep -q "contract.sync_lifecycle" "$tmpdir/sync_sources.out"

./ops/docs_impact.py --files README.md >"$tmpdir/none.out"
grep -q "docs_impact: no registry impacts" "$tmpdir/none.out"

./ops/docs_impact.py --files backend/src/kg/routers/vocab.py --json >"$tmpdir/backend.json"
grep -q '"id": "reference.tech_index"' "$tmpdir/backend.json"
grep -q '"id": "contract.sync_lifecycle"' "$tmpdir/backend.json"
if grep -q '"id": "policy.safety"' "$tmpdir/backend.json"; then
  echo "ordinary backend router changes should not imply production safety impact" >&2
  exit 1
fi
if grep -q '"id": "sop.deploy"' "$tmpdir/backend.json"; then
  echo "ordinary backend router changes should not imply deploy workflow impact" >&2
  exit 1
fi
if grep -q '"id": "sop.backend"' "$tmpdir/backend.json"; then
  echo "ordinary backend router changes should not imply backend workflow impact" >&2
  exit 1
fi

./ops/docs_impact.py --files ops/devops_kg_safe.sh --json >"$tmpdir/devops_safe.json"
grep -q '"id": "policy.safety"' "$tmpdir/devops_safe.json"
grep -q '"id": "reference.tech_index"' "$tmpdir/devops_safe.json"
grep -q '"id": "sop.deploy"' "$tmpdir/devops_safe.json"
grep -q '"id": "sop.debug"' "$tmpdir/devops_safe.json"
if grep -q '"id": "contract.host_topology"' "$tmpdir/devops_safe.json"; then
  echo "safe wrapper changes should not imply host topology impact by default" >&2
  exit 1
fi
if grep -q '"id": "reference.product_surface"' "$tmpdir/devops_safe.json"; then
  echo "safe wrapper changes should not imply product surface impact by default" >&2
  exit 1
fi
if grep -q '"id": "sop.backend"' "$tmpdir/devops_safe.json"; then
  echo "safe wrapper changes should not imply backend workflow impact by default" >&2
  exit 1
fi

./ops/docs_impact.py --files ios/BooksBrowser/Models/Book.swift --json >"$tmpdir/book_model.json"
grep -q '"id": "reference.feature_boundary.bookshelf"' "$tmpdir/book_model.json"
grep -q '"id": "generated.ios_baseline"' "$tmpdir/book_model.json"
grep -q '"generator": "ops/gen_ios_baseline.sh"' "$tmpdir/book_model.json"
if grep -q '"id": "contract.sync_lifecycle"' "$tmpdir/book_model.json"; then
  echo "book model changes should not imply vocabulary sync lifecycle impact by default" >&2
  exit 1
fi
if grep -q '"id": "sop.ios"' "$tmpdir/book_model.json"; then
  echo "ordinary iOS model changes should not imply iOS workflow SOP impact" >&2
  exit 1
fi

./ops/docs_impact.py --files ops/tests/test_docs_lint.sh >"$tmpdir/docs_test.out"
if grep -q "reference.tech_index" "$tmpdir/docs_test.out"; then
  echo "docs tooling test changes should not imply tech index impact" >&2
  exit 1
fi
