#!/usr/bin/env bash
# Regression tests for registry-backed document impact hints.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/kg_docs_impact.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

require() {
  local pattern="$1" file="$2"
  grep -q "$pattern" "$file" || {
    echo "missing '$pattern' in $file" >&2
    sed -n '1,160p' "$file" >&2
    exit 1
  }
}

./ops/docs_impact.py --help >"$TMP/help"
require "match_type" "$TMP/help"
require "merge-base" "$TMP/help"

./ops/docs_impact.py --files ops/docs_lint.sh >"$TMP/docs-tooling"
require "sop.doc_sync" "$TMP/docs-tooling"
require "sop.docs_dogfood" "$TMP/docs-tooling"
require "reference.tech_index" "$TMP/docs-tooling"
if grep -qE "sop.deploy|sop.debug|policy.safety|reference.product_surface" "$TMP/docs-tooling"; then
  echo "document tooling changes produced unrelated runtime impact" >&2
  exit 1
fi

./ops/docs_impact.py --files docs/registry.yml >"$TMP/registry"
require "sop.doc_sync" "$TMP/registry"

./ops/docs_impact.py --files CLAUDE.md >"$TMP/guide"
require "reference.agent_context" "$TMP/guide"
if grep -q "sop.doc_sync" "$TMP/guide"; then
  echo "workspace guide changes should not imply docs implementation impact" >&2
  exit 1
fi

./ops/docs_impact.py --files backend/tests/test_api.py >"$TMP/backend"
require "reference.testing_backend_strategy" "$TMP/backend"
require "sop.backend" "$TMP/backend"
require "sop.scaling_readiness" "$TMP/backend"
if grep -qE "policy.safety|reference.product_surface|sop.deploy" "$TMP/backend"; then
  echo "backend test changes produced unrelated impact" >&2
  exit 1
fi

./ops/docs_impact.py --files ops/ios_release.sh >"$TMP/ios"
require "sop.ios" "$TMP/ios"
if grep -qE "policy.safety|sop.backend|sop.deploy" "$TMP/ios"; then
  echo "iOS release changes produced unrelated impact" >&2
  exit 1
fi

./ops/docs_impact.py --surface-paths >"$TMP/surface-paths"
grep -qxF '.claude/agents/' "$TMP/surface-paths"
grep -qxF 'docs/reference/tech_index.md' "$TMP/surface-paths"
grep -qxF 'docs/runbook/system.md' "$TMP/surface-paths"
if grep -qxF 'docs/runbook/' "$TMP/surface-paths"; then
  echo "surface paths must remain file-scoped" >&2
  exit 1
fi

mkdir -p "$TMP/tree/.claude/agents"
printf '%s\n' 'NEEDLE-XYZ in agent' >"$TMP/tree/.claude/agents/w.md"
printf '%s\n' 'NEEDLE-XYZ in top' >"$TMP/tree/top.md"
cat >"$TMP/tree/registry.yml" <<'EOF'
version: 1
description: fixture
agent_facing_surface:
  paths:
    - .claude/agents/
    - top.md
EOF
surface_out="$($ROOT/ops/docs_impact.py --root "$TMP/tree" --registry "$TMP/tree/registry.yml" --surface-scan 'NEEDLE-XYZ')"
printf '%s\n' "$surface_out" | grep -qE '^SURFACE \.claude/agents/w\.md:1:'
printf '%s\n' "$surface_out" | grep -qE '^SURFACE top\.md:1:'

if "$ROOT/ops/docs_impact.py" --root "$TMP/tree" --registry "$TMP/tree/missing.yml" --surface-paths >"$TMP/missing-registry.out" 2>&1; then
  echo "missing registry unexpectedly passed" >&2
  exit 1
fi
require "registry" "$TMP/missing-registry.out"

echo "docs-impact tests: PASS"
