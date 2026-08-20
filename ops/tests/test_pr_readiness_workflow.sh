#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKFLOW="$ROOT/.github/workflows/pr-readiness.yml"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[[ -f "$WORKFLOW" ]] || fail "missing $WORKFLOW"

grep -Fqx 'name: pr-readiness' <(sed -n '1p' "$WORKFLOW") \
  || fail "workflow name must be pr-readiness"
grep -Fq '  pull_request:' "$WORKFLOW" \
  || fail "workflow must listen to pull_request"
grep -Fq 'types: [opened, synchronize, reopened, ready_for_review]' "$WORKFLOW" \
  || fail "workflow trigger types are incomplete or reordered"

if grep -Eq '^  (push|schedule|workflow_dispatch):' "$WORKFLOW"; then
  fail "workflow has an unapproved trigger"
fi

grep -Fq 'if: ${{ github.event.pull_request.draft != true }}' "$WORKFLOW" \
  || fail "draft pull requests must skip validation"
grep -Fq 'timeout-minutes: 1' "$WORKFLOW" \
  || fail "validator must have a one-minute timeout"

for required in BODY BASE_SHA HEAD_SHA; do
  grep -Fq "${required}:" "$WORKFLOW" \
    || fail "workflow must pass ${required} through the environment"
done

for required in 'Scope' 'Validation' 'kg.worktree.handback.v1'; do
  grep -Fq "$required" "$WORKFLOW" \
    || fail "workflow does not validate $required"
done

grep -Fq "if has_field 'Base SHA' && has_field 'Head SHA'; then" "$WORKFLOW" \
  || fail "workflow does not validate the legacy SHA label pair"
grep -Fq "elif has_field 'base_sha' && has_field 'tip_sha'; then" "$WORKFLOW" \
  || fail "workflow does not validate the canonical SHA key pair"
grep -Fq 'Base SHA/Head SHA or base_sha/tip_sha' "$WORKFLOW" \
  || fail "workflow does not fail closed when neither SHA pair is present"

canonical_body='{"base_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "tip_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}'
legacy_body='Base SHA: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
Head SHA: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

for field in base_sha tip_sha; do
  grep -Eq "(^|[^[:alnum:]_])${field}[[:space:]]*['\"]?[[:space:]]*:" <<<"$canonical_body" \
    || fail "canonical regression does not recognize $field"
done
for field in 'Base SHA' 'Head SHA'; do
  grep -Eq "(^|[^[:alnum:]_])${field}[[:space:]]*['\"]?[[:space:]]*:" <<<"$legacy_body" \
    || fail "legacy regression does not recognize $field"
done

grep -Eq '\[0-9A-Fa-f\]\{64\}' "$WORKFLOW" \
  || fail "workflow does not validate a 64-hex digest"
grep -Fq 'grep -Fq "$BASE_SHA"' "$WORKFLOW" \
  || fail "workflow does not validate the current base SHA"
grep -Fq 'grep -Fq "$HEAD_SHA"' "$WORKFLOW" \
  || fail "workflow does not validate the current head SHA"

if grep -Eq 'backend|ios|pytest|ops/test_ops|ops-suite|pr-gate|workflow_call' "$WORKFLOW"; then
  fail "workflow imports a suite or existing workflow fan-out"
fi

echo "PASS: pr-readiness workflow contract"
