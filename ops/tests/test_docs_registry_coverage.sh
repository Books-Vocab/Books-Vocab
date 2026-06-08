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
grep -q "active_unregistered=" "$tmpdir/coverage.out"
grep -q "backlog_unregistered=" "$tmpdir/coverage.out"
grep -q "no active registry debt; backlog docs below are informational only" "$tmpdir/coverage.out"
grep -q "BACKLOG_UNREGISTERED" "$tmpdir/coverage.out"
grep -q "docs/plans/2026-05-23-notebook-editorial-stack.md" "$tmpdir/coverage.out"
if grep -q "^UNREGISTERED " "$tmpdir/coverage.out"; then
  echo "coverage human output should not duplicate backlog entries as generic UNREGISTERED rows" >&2
  cat "$tmpdir/coverage.out" >&2
  exit 1
fi
if grep -q "ACTIVE_UNREGISTERED" "$tmpdir/coverage.out"; then
  echo "active docs should all be registered; only backlog docs may remain unregistered" >&2
  cat "$tmpdir/coverage.out" >&2
  exit 1
fi
if grep -q "docs/sop/figma-token-workflow.md" "$tmpdir/coverage.out"; then
  echo "Figma token workflow is an active SOP and should be registered" >&2
  cat "$tmpdir/coverage.out" >&2
  exit 1
fi
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
grep -q '"active_unregistered_count": 0' "$tmpdir/coverage.json"
grep -q '"backlog_unregistered_count"' "$tmpdir/coverage.json"
grep -q '"backlog_unregistered"' "$tmpdir/coverage.json"
grep -q '"docs/plans/2026-05-23-notebook-editorial-stack.md"' "$tmpdir/coverage.json"
if grep -q '"docs/sop/figma-token-workflow.md"' "$tmpdir/coverage.json"; then
  echo "Figma token workflow should be registered in JSON output" >&2
  cat "$tmpdir/coverage.json" >&2
  exit 1
fi
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

./ops/docs_registry_coverage.py --strict >"$tmpdir/strict.out"
grep -q "active_unregistered=0" "$tmpdir/strict.out"

fixture_root="$tmpdir/fixture"
mkdir -p "$fixture_root/docs/sop" "$fixture_root/docs/plans"
cat >"$fixture_root/docs/registry.yml" <<'YAML'
documents: []
YAML
cat >"$fixture_root/docs/sop/unregistered-active.md" <<'MD'
<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - docs/
verified_against: HEAD
-->
# Active SOP
MD
cat >"$fixture_root/docs/plans/unregistered-backlog.md" <<'MD'
<!-- doc-meta
tier: reference
authority: derived
update_trigger: plan-change
scope:
  - docs/
verified_against: HEAD
-->
# Backlog Plan
MD

if ./ops/docs_registry_coverage.py --root "$fixture_root" --registry docs/registry.yml --strict >"$tmpdir/fixture_strict_fail.out" 2>&1; then
  echo "fixture strict should fail when an active SOP is unregistered" >&2
  cat "$tmpdir/fixture_strict_fail.out" >&2
  exit 1
fi
grep -q "active_unregistered=1" "$tmpdir/fixture_strict_fail.out"

cat >"$fixture_root/docs/registry.yml" <<'YAML'
documents:
  - id: sop.fixture
    path: docs/sop/unregistered-active.md
    kind: sop
    authority: derived
    triggers:
      - fixture_changed
    sources:
      - docs/sop/unregistered-active.md
YAML

./ops/docs_registry_coverage.py --root "$fixture_root" --registry docs/registry.yml --strict >"$tmpdir/fixture_strict_pass.out"
grep -q "active_unregistered=0" "$tmpdir/fixture_strict_pass.out"
grep -q "backlog_unregistered=1" "$tmpdir/fixture_strict_pass.out"
grep -q "no active registry debt; backlog docs below are informational only" "$tmpdir/fixture_strict_pass.out"
