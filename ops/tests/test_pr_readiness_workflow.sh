#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

WORKFLOW=.github/workflows/pr-readiness.yml

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

grep -Eq 'types: \[[^]]*opened[^]]*edited[^]]*synchronize[^]]*reopened[^]]*ready_for_review' "$WORKFLOW" \
  || fail "workflow does not rerun on every PR metadata or head transition"
grep -Fq 'if: ${{ github.event.pull_request.draft != true }}' "$WORKFLOW" \
  || fail "workflow does not keep draft PRs outside readiness admission"
grep -Fq 'timeout-minutes: 1' "$WORKFLOW" \
  || fail "workflow readiness validation has no bounded timeout"
grep -Fq 'HEAD_SHA: ${{ github.event.pull_request.head.sha }}' "$WORKFLOW" \
  || fail "workflow does not bind validation to the exact PR HEAD"
grep -Fq './ops/delivery.py validate-pr-body --head-sha "$HEAD_SHA"' "$WORKFLOW" \
  || fail "workflow does not call the typed delivery receipt validator"

if grep -Eq 'BASE_SHA:|contains_exact_sha|grep .*Base SHA|perl -ne.*Digest' "$WORKFLOW"; then
  fail "workflow duplicates receipt parsing or blocks durable historical-base publication"
fi
if grep -Eq 'backend|ios|pytest|ops/test_ops|ops-suite|pr-gate|workflow_call' "$WORKFLOW"; then
  fail "readiness workflow imports product quality suites"
fi

echo "PASS: pr-readiness workflow delegates to the typed receipt validator"
