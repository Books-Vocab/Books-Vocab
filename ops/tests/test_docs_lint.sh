#!/usr/bin/env bash
# Regression tests for docs_lint gate/audit split and registry checks.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

dump_file() {
  file="$1"
  echo "---- $file (tail) ----" >&2
  if [ -f "$file" ]; then
    tail -80 "$file" >&2
  else
    echo "(missing)" >&2
  fi
}

run_capture() {
  out="$1"
  shift
  set +e
  "$@" >"$out" 2>&1
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    echo "command failed rc=$rc: $*" >&2
    dump_file "$out"
    exit "$rc"
  fi
}

require_grep() {
  pattern="$1"
  file="$2"
  if ! grep -q "$pattern" "$file"; then
    echo "missing pattern '$pattern' in $file" >&2
    dump_file "$file"
    exit 1
  fi
}

grep -q "docs/registry.yml" CLAUDE.md
grep -q "ops/docs_impact.py" CLAUDE.md
grep -q "ops/docs_lint.sh" CLAUDE.md
grep -q "ops/docs_registry_coverage.py" CLAUDE.md

run_capture /tmp/kg_docs_lint_files.out ./ops/docs_lint.sh --files docs/reference/tech_index.md docs/sop/architecture.md
require_grep "ERROR: 0" /tmp/kg_docs_lint_files.out

run_capture /tmp/kg_docs_lint_default.out ./ops/docs_lint.sh
require_grep "mode=gate" /tmp/kg_docs_lint_default.out
if grep -q "docs_lint: mode=audit" /tmp/kg_docs_lint_default.out; then
  echo "docs_lint default mode should stay in gate mode, not silently flip to audit" >&2
  dump_file /tmp/kg_docs_lint_default.out
  exit 1
fi

run_capture /tmp/kg_docs_lint_audit.out ./ops/docs_lint.sh --audit
require_grep "mode=audit" /tmp/kg_docs_lint_audit.out
require_grep "ERROR: 0" /tmp/kg_docs_lint_audit.out

run_capture /tmp/kg_docs_lint_all.out ./ops/docs_lint.sh --all
require_grep "mode=audit" /tmp/kg_docs_lint_all.out
require_grep "ERROR: 0" /tmp/kg_docs_lint_all.out

run_capture /tmp/kg_docs_lint_registry.out ./ops/docs_lint.sh --registry
require_grep "REGISTRY OK" /tmp/kg_docs_lint_registry.out
require_grep "OK:    1" /tmp/kg_docs_lint_registry.out

run_capture /tmp/kg_docs_lint_since_head.out ./ops/docs_lint.sh --since HEAD
if ! grep -q "docs_lint: no docs selected" /tmp/kg_docs_lint_since_head.out; then
  require_grep "ERROR: 0" /tmp/kg_docs_lint_since_head.out
fi

impact_probe="ops/.docs_lint_impact_probe"
trap 'rm -f "$impact_probe"' EXIT
printf 'probe\n' >"$impact_probe"
run_capture /tmp/kg_docs_lint_impact.out ./ops/docs_lint.sh --since HEAD
require_grep "docs_lint: registry impact hints" /tmp/kg_docs_lint_impact.out
require_grep "reference.tech_index" /tmp/kg_docs_lint_impact.out
require_grep "docs_lint: inspect suppression with ./ops/docs_impact.py --since HEAD --explain" /tmp/kg_docs_lint_impact.out
require_grep "docs_lint: frontmatter checks below only cover docs changed in the current checkout; use the impact hints above to judge non-doc changes" /tmp/kg_docs_lint_impact.out
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
