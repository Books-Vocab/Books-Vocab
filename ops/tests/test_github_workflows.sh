#!/usr/bin/env bash
# test_github_workflows.sh — keep the GitHub-native CI topology executable.
#
# The component workflows are reusable building blocks. Only pr-gate owns the
# pull_request entrypoint and its final required status, so a new workflow cannot
# silently become a second PR control plane or bypass the macOS trust boundary.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

failures=0
fail() {
  printf '✗ %s\n' "$1" >&2
  failures=$((failures + 1))
}

component_workflows=(
  backend-quality
  design-system
  llm-eval
  ops-suite
  ui-quality-gate
  ios-quality
)

for workflow in "${component_workflows[@]}"; do
  path=".github/workflows/${workflow}.yml"
  [[ -f "$path" ]] || { fail "missing component workflow: $path"; continue; }
  grep -q '^  workflow_call:' "$path" || fail "$path is not reusable via workflow_call"
  if grep -q '^  pull_request:' "$path"; then
    fail "$path owns a pull_request trigger; pr-gate must be the only PR entrypoint"
  fi
done

PR_GATE=".github/workflows/pr-gate.yml"
grep -q '^  pull_request:' "$PR_GATE" || fail "pr-gate has no pull_request trigger"
grep -q '^  required:' "$PR_GATE" || fail "pr-gate has no final required job"
grep -q 'needs: \[repo-gate, backend-quality, llm-eval, design-system, ui-quality-gate, ops-suite, ios-quality\]' "$PR_GATE" \
  || fail "pr-gate required job does not depend on every component gate"
for workflow in "${component_workflows[@]}"; do
  grep -q "uses: ./.github/workflows/${workflow}.yml" "$PR_GATE" \
    || fail "pr-gate does not call ${workflow}"
done

IOS=".github/workflows/ios-quality.yml"
grep -q 'runs-on: macos-26' "$IOS" || fail "iOS workflow does not use the standard macos-26 runner"
grep -q 'ios_ops.sh build' "$IOS" || fail "iOS workflow has no real Xcode build invocation"
grep -q -- '--unit' "$IOS" || fail "iOS workflow has no unit-test invocation"
grep -q -- '--ui' "$IOS" || fail "iOS workflow has no UI-test invocation"
grep -q -- '--dataset marketing_demo' "$IOS" || fail "UI tests do not pin a UI World dataset"
if grep -q 'self-hosted\|pull_request_target' "$IOS"; then
  fail "iOS workflow crosses the public fork/self-hosted trust boundary"
fi

OPS=".github/workflows/ops-suite.yml"
grep -q 'fromJSON' "$OPS" || fail "ops-suite does not derive its matrix from the classified group list"
grep -q 'matrix.shard' "$OPS" || fail "ops-suite has no parallel shard matrix"
grep -q 'SHARD_COUNT' "$OPS" || fail "ops-suite does not pin the shard partition count"
if grep -q 'Run platform-independent ops groups' "$OPS"; then
  fail "ops-suite still runs all Linux groups serially"
fi

# Parse all workflow YAML with the runner's ubiquitous Ruby runtime. This
# catches indentation/anchor errors before GitHub has to schedule a runner.
# macOS ships Ruby 2.6, whose Psych does not accept the newer `aliases:`
# keyword; ordinary YAML.load_file still parses the anchored path lists used
# here and keeps this local contract compatible with both runner generations.
if ! ruby -e 'require "yaml"; ARGV.each { |path| YAML.load_file(path) }' .github/workflows/*.yml; then
  fail "workflow YAML does not parse"
fi

if (( failures > 0 )); then
  printf 'github workflow contract: %d failure(s)\n' "$failures" >&2
  exit 1
fi
printf 'github workflow contract: PASS (%d reusable component workflows, one PR aggregator)\n' "${#component_workflows[@]}"
