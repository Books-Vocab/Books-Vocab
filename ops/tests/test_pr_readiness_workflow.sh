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

if grep -Fq 'grep -Fq "$BASE_SHA"' "$WORKFLOW"; then
  fail "workflow still validates the base SHA by substring"
fi
grep -Fq 'contains_exact_sha "$BASE_SHA"' "$WORKFLOW" \
  || fail "workflow does not validate the current base SHA as an exact token"
grep -Fq 'contains_exact_sha "$HEAD_SHA"' "$WORKFLOW" \
  || fail "workflow does not validate the current head SHA as an exact token"
grep -Fq 'grep -Eq "(^|[^[:alnum:]_])${sha}([^[:alnum:]_]|$)"' "$WORKFLOW" \
  || fail "workflow has no SHA token boundary check"
grep -Fq 'digest_count=' "$WORKFLOW" \
  || fail "workflow does not count handback digests"
grep -Fq '[[ "$digest_count" -eq 1 ]]' "$WORKFLOW" \
  || fail "workflow does not require exactly one handback digest"
grep -Fq "[\\x60\\x22\\x27]?[Dd]igest[\\x60\\x22\\x27]?\\s*:\\s*[\\x60\\x22\\x27]?([0-9A-Fa-f]{64})(?![[:alnum:]_])" "$WORKFLOW" \
  || fail "workflow must bind the digest count to a typed digest field"

sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
contains_exact_sha() {
  local sha="$1" body="$2"
  grep -Eq "(^|[^[:alnum:]_])${sha}([^[:alnum:]_]|$)" <<<"$body"
}
contains_exact_sha "$sha" "$sha" \
  || fail "SHA regression does not accept a standalone exact token"
if contains_exact_sha "$sha" "commit${sha}"; then
  fail "SHA regression accepts an identifier prefix"
fi
if contains_exact_sha "$sha" "${sha}suffix"; then
  fail "SHA regression accepts an identifier suffix"
fi

digest_a=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
digest_b=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
typed_digest_count() {
  (perl -ne 'while (/(?:^|[^[:alnum:]_])[\x60\x22\x27]?[Dd]igest[\x60\x22\x27]?\s*:\s*[\x60\x22\x27]?([0-9A-Fa-f]{64})(?![[:alnum:]_])/g) { print "$1\n" }' <<<"$1" || true) \
    | wc -l | tr -d ' '
}
[[ "$(typed_digest_count "Digest: $digest_a")" -eq 1 ]] \
  || fail "digest regression does not accept one typed digest"
json_digest_body="\"digest\": \"$digest_a\""
[[ "$(typed_digest_count "$json_digest_body")" -eq 1 ]] \
  || fail "digest regression does not accept canonical JSON digest"
json_spaced_digest_body="\"digest\" : \"$digest_a\""
[[ "$(typed_digest_count "$json_spaced_digest_body")" -eq 1 ]] \
  || fail "digest regression does not accept spaced JSON digest"
[[ "$(typed_digest_count "Digest: $digest_a Digest: $digest_b")" -eq 2 ]] \
  || fail "digest regression does not count typed digests independently"
[[ "$(typed_digest_count "Digest: ${digest_a}a")" -eq 0 ]] \
  || fail "digest regression accepts a 65-hex typed digest"
[[ "$(typed_digest_count "Digest: ${digest_a}wrong")" -eq 0 ]] \
  || fail "digest regression accepts an identifier suffix"
[[ "$(typed_digest_count "$digest_a")" -eq 0 ]] \
  || fail "digest regression counts an untyped body hex run"

if grep -Eq 'backend|ios|pytest|ops/test_ops|ops-suite|pr-gate|workflow_call' "$WORKFLOW"; then
  fail "workflow imports a suite or existing workflow fan-out"
fi

echo "PASS: pr-readiness workflow contract"
