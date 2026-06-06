#!/usr/bin/env bash
# Regression tests for docs_lint gate/audit split and registry checks.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

./ops/docs_lint.sh --files docs/reference/tech_index.md docs/sop/architecture.md >/tmp/kg_docs_lint_files.out
grep -q "ERROR: 0" /tmp/kg_docs_lint_files.out

./ops/docs_lint.sh >/tmp/kg_docs_lint_default.out
grep -q "mode=gate" /tmp/kg_docs_lint_default.out
if grep -q "STALE docs/" /tmp/kg_docs_lint_default.out; then
  echo "docs_lint default mode should not run full-repo staleness audit" >&2
  exit 1
fi

./ops/docs_lint.sh --audit >/tmp/kg_docs_lint_audit.out 2>&1
grep -q "mode=audit" /tmp/kg_docs_lint_audit.out
grep -q "WARN:  0" /tmp/kg_docs_lint_audit.out
grep -q "ERROR: 0" /tmp/kg_docs_lint_audit.out

./ops/docs_lint.sh --all >/tmp/kg_docs_lint_all.out 2>&1
grep -q "mode=audit" /tmp/kg_docs_lint_all.out
grep -q "WARN:  0" /tmp/kg_docs_lint_all.out
grep -q "ERROR: 0" /tmp/kg_docs_lint_all.out

./ops/docs_lint.sh --registry >/tmp/kg_docs_lint_registry.out
grep -q "REGISTRY OK" /tmp/kg_docs_lint_registry.out

./ops/docs_lint.sh --since HEAD >/tmp/kg_docs_lint_since_head.out
if ! grep -q "docs_lint: no docs selected" /tmp/kg_docs_lint_since_head.out; then
  grep -q "ERROR: 0" /tmp/kg_docs_lint_since_head.out
fi

impact_probe="ops/.docs_lint_impact_probe"
trap 'rm -f "$impact_probe"' EXIT
printf 'probe\n' >"$impact_probe"
./ops/docs_lint.sh --since HEAD >/tmp/kg_docs_lint_impact.out
grep -q "docs_lint: registry impact hints" /tmp/kg_docs_lint_impact.out
grep -q "reference.tech_index" /tmp/kg_docs_lint_impact.out
rm -f "$impact_probe"
trap - EXIT

if ./ops/docs_lint.sh --definitely-not-a-real-flag >/tmp/kg_docs_lint_bad.out 2>&1; then
  echo "docs_lint accepted an unknown flag" >&2
  exit 1
fi
grep -q "Unknown arg" /tmp/kg_docs_lint_bad.out

if ./ops/docs_lint.sh --files docs/reference/does-not-exist.md >/tmp/kg_docs_lint_missing.out 2>&1; then
  echo "docs_lint accepted a missing --files path" >&2
  exit 1
fi
grep -q "路徑不存在" /tmp/kg_docs_lint_missing.out

if ./ops/docs_lint.sh --files README.md >/tmp/kg_docs_lint_nondoc.out 2>&1; then
  echo "docs_lint accepted a non-doc --files path" >&2
  exit 1
fi
grep -q "只接受 docs/.*\\.md" /tmp/kg_docs_lint_nondoc.out
