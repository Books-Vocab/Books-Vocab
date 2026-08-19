#!/usr/bin/env bash
# test_ci_scope_router.sh — prove confidence routing is selective but fail-closed.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ROUTER="$ROOT/ops/ci_scope_router.sh"

failures=0
pass() {
  printf '✓ %s\n' "$1"
}

fail() {
  printf '✗ %s\n' "$1" >&2
  failures=$((failures + 1))
}

assert_plan() {
  local label="$1"
  local paths="$2"
  local expected="$3"
  local actual

  if ! actual="$(printf '%s\n' "$paths" | "$ROUTER" --paths-stdin --format json)"; then
    fail "$label: router command failed"
    return
  fi

  if jq -e -n --argjson actual "$actual" --argjson expected "$expected" '$actual == $expected' >/dev/null; then
    pass "$label"
  else
    fail "$label: expected $expected, got $actual"
  fi
}

assert_plan 'backend source selects only backend confidence' \
  'backend/src/kg/app.py' \
  '{"backend":true,"ops":false,"ios":false}'
assert_plan 'iOS source selects only iOS confidence' \
  'ios/BooksAndVocab/App.swift' \
  '{"backend":false,"ops":false,"ios":true}'
assert_plan 'ordinary ops source stays off macOS' \
  'ops/backup_verify.sh' \
  '{"backend":false,"ops":true,"ios":false}'
assert_plan 'iOS shared helper selects ops plus iOS' \
  'ops/lib/project_python.sh' \
  '{"backend":false,"ops":true,"ios":true}'
assert_plan 'docs-only change avoids unrelated confidence suites' \
  'docs/reference/testing/smoke_checklist.md' \
  '{"backend":false,"ops":false,"ios":false}'
assert_plan 'PR-gate policy change reruns all confidence suites' \
  '.github/workflows/pr-gate.yml' \
  '{"backend":true,"ops":true,"ios":true}'
assert_plan 'confidence verdict policy change reruns all confidence suites' \
  'ops/ci_confidence_verdict.sh' \
  '{"backend":true,"ops":true,"ios":true}'
assert_plan 'confidence verdict contract test reruns all confidence suites' \
  'ops/tests/test_ci_confidence_verdict.sh' \
  '{"backend":true,"ops":true,"ios":true}'
assert_plan 'devops skill roster change selects only backend confidence' \
  '.claude/skills/devops/SKILL.md' \
  '{"backend":true,"ops":false,"ios":false}'
assert_plan 'unknown source fails closed to all confidence suites' \
  'new-top-level-runtime-config.toml' \
  '{"backend":true,"ops":true,"ios":true}'

if actual="$($ROUTER --all --format json)" \
  && jq -e -n --argjson actual "$actual" '$actual == {backend: true, ops: true, ios: true}' >/dev/null; then
  pass 'manual mode selects all confidence suites'
else
  fail 'manual mode does not select all confidence suites'
fi

if "$ROUTER" --format json >/dev/null 2>&1; then
  fail 'router accepts a missing change source'
else
  pass 'router rejects a missing change source'
fi

if actual="$($ROUTER --base HEAD --head HEAD --format json)" \
  && jq -e -n --argjson actual "$actual" '$actual == {backend: false, ops: false, ios: false}' >/dev/null; then
  pass 'git commit mode classifies an empty diff'
else
  fail 'git commit mode does not classify an empty diff'
fi

if (( failures > 0 )); then
  printf 'ci scope router: %d failure(s)\n' "$failures" >&2
  exit 1
fi

printf 'ci scope router: PASS\n'
