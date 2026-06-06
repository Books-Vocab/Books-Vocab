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
if grep -q "docs/reference/feature_boundary/" "$tmpdir/coverage.out"; then
  echo "feature boundary docs should all be registered" >&2
  cat "$tmpdir/coverage.out" >&2
  exit 1
fi
if grep -Eq "docs/(sop/ui-design|reference/ui/)" "$tmpdir/coverage.out"; then
  echo "UI design docs should all be registered" >&2
  cat "$tmpdir/coverage.out" >&2
  exit 1
fi
if grep -Eq "docs/(runbook/system|reference/testing/(backend_strategy|smoke_checklist)|reference/cost_baseline|sop/(cost_review|review_discipline))\\.md" "$tmpdir/coverage.out"; then
  echo "agent-routed operational docs should all be registered" >&2
  cat "$tmpdir/coverage.out" >&2
  exit 1
fi
if grep -Eq "docs/(sop/(architecture|backup|backup_restore|i18n_lint|i18n_plural_keys|podcast_pipeline|llm_eval)|reference/llm_eval)\\.md" "$tmpdir/coverage.out"; then
  echo "agent-routed architecture/i18n/podcast/eval docs should all be registered" >&2
  cat "$tmpdir/coverage.out" >&2
  exit 1
fi

./ops/docs_registry_coverage.py --json >"$tmpdir/coverage.json"
grep -q '"registered_count"' "$tmpdir/coverage.json"
grep -q '"unregistered_by_tier"' "$tmpdir/coverage.json"
if grep -q '"docs/reference/feature_boundary/' "$tmpdir/coverage.json"; then
  echo "feature boundary docs should all be registered in JSON output" >&2
  cat "$tmpdir/coverage.json" >&2
  exit 1
fi
if grep -Eq '"docs/(sop/ui-design|reference/ui/)' "$tmpdir/coverage.json"; then
  echo "UI design docs should all be registered in JSON output" >&2
  cat "$tmpdir/coverage.json" >&2
  exit 1
fi
if grep -Eq '"docs/(runbook/system|reference/testing/(backend_strategy|smoke_checklist)|reference/cost_baseline|sop/(cost_review|review_discipline))\\.md' "$tmpdir/coverage.json"; then
  echo "agent-routed operational docs should all be registered in JSON output" >&2
  cat "$tmpdir/coverage.json" >&2
  exit 1
fi
if grep -Eq '"docs/(sop/(architecture|backup|backup_restore|i18n_lint|i18n_plural_keys|podcast_pipeline|llm_eval)|reference/llm_eval)\\.md' "$tmpdir/coverage.json"; then
  echo "agent-routed architecture/i18n/podcast/eval docs should all be registered in JSON output" >&2
  cat "$tmpdir/coverage.json" >&2
  exit 1
fi

if ./ops/docs_registry_coverage.py --strict >"$tmpdir/strict.out" 2>&1; then
  echo "docs_registry_coverage --strict unexpectedly passed despite unregistered active docs" >&2
  exit 1
fi
grep -q "STRICT FAIL" "$tmpdir/strict.out"
