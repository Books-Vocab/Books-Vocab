#!/usr/bin/env bash
# Regression tests for docs_lint changed-scope modes.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

./ops/docs_lint.sh --files docs/reference/tech_index.md docs/sop/architecture.md >/tmp/kg_docs_lint_files.out
grep -q "ERROR: 0" /tmp/kg_docs_lint_files.out

./ops/docs_lint.sh --since HEAD >/tmp/kg_docs_lint_since_head.out
if ! grep -q "docs_lint: no docs selected" /tmp/kg_docs_lint_since_head.out; then
  grep -q "ERROR: 0" /tmp/kg_docs_lint_since_head.out
fi

if ./ops/docs_lint.sh --definitely-not-a-real-flag >/tmp/kg_docs_lint_bad.out 2>&1; then
  echo "docs_lint accepted an unknown flag" >&2
  exit 1
fi
grep -q "Unknown arg" /tmp/kg_docs_lint_bad.out
