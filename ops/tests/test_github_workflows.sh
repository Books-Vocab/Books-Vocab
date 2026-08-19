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

grep -Fqx "      - '.claude/skills/devops/SKILL.md'" .github/workflows/backend-quality.yml \
  || fail "backend-quality main push trigger omits the devops skill roster contract"

PR_GATE=".github/workflows/pr-gate.yml"
grep -q '^  pull_request:' "$PR_GATE" || fail "pr-gate has no pull_request trigger"
# A draft-to-ready transition changes review metadata, not source. The latest
# `opened`/`synchronize` run already carries the relevant candidate evidence;
# triggering again would cancel or duplicate its full confidence fan-out.
if grep -Eq '^[[:space:]]*types:.*ready_for_review' "$PR_GATE"; then
  fail "pr-gate reruns on ready_for_review without a source change"
fi
grep -q '^  required:' "$PR_GATE" || fail "pr-gate has no final required job"
grep -q '^  changed-paths:' "$PR_GATE" || fail "pr-gate has no fail-closed confidence path classifier"
grep -q 'ops/ci_scope_router.sh' "$PR_GATE" \
  || fail "pr-gate does not invoke the confidence path classifier"
grep -q 'ops/ci_confidence_verdict.sh' "$PR_GATE" \
  || fail "pr-gate does not verify selected versus skipped confidence suites"
grep -q 'needs: \[repo-gate, llm-eval, design-system, ui-quality-gate\]' "$PR_GATE" \
  || fail "pr-gate required job is not the short merge gate"
grep -q '^  confidence:' "$PR_GATE" \
  || fail "pr-gate has no non-blocking full-confidence aggregator"
grep -q 'needs: \[changed-paths, repo-gate, backend-quality, llm-eval, design-system, ui-quality-gate, ops-suite, ios-quality\]' "$PR_GATE" \
  || fail "pr-gate confidence job does not depend on every component gate"
# `confidence` runs on a separate runner, so it must check out its own
# workspace before invoking the verdict helper.
if ! awk '
  /^  confidence:/ { in_confidence=1; next }
  in_confidence && /^  [A-Za-z0-9_-]+:/ { exit }
  in_confidence && index($0, "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1") { checkout=NR }
  in_confidence && index($0, "name: Report the complete validation fan-out") { report=NR }
  END { exit !(checkout && report && checkout < report) }
' "$PR_GATE"; then
  fail "pr-gate confidence job does not check out the workspace before its verdict"
fi
required_block="$(awk '
  /^  required:/ { in_required=1; next }
  in_required && /^  [A-Za-z0-9_-]+:/ { exit }
  in_required { print }
' "$PR_GATE")"
if grep -q 'backend-quality\|ops-suite\|ios-quality' <<<"$required_block"; then
  fail "slow backend/ops/iOS jobs are still merge-blocking"
fi
repo_gate_block="$(awk '
  /^  repo-gate:/ { in_repo_gate=1; next }
  in_repo_gate && /^  [A-Za-z0-9_-]+:/ { exit }
  in_repo_gate { print }
' "$PR_GATE")"
grep -q 'timeout-minutes: 3' <<<"$repo_gate_block" \
  || fail "repo-gate is not hard-bounded to the short merge-gate budget"
for workflow in "${component_workflows[@]}"; do
  grep -q "uses: ./.github/workflows/${workflow}.yml" "$PR_GATE" \
    || fail "pr-gate does not call ${workflow}"
done
grep -q "needs.changed-paths.outputs.backend == 'true'" "$PR_GATE" \
  || fail "backend confidence is not path-selected"
grep -q "needs.changed-paths.outputs.ops == 'true'" "$PR_GATE" \
  || fail "ops confidence is not path-selected"
grep -q "needs.changed-paths.outputs.ios == 'true'" "$PR_GATE" \
  || fail "iOS confidence is not path-selected"

# Every required-path component needs its own three-minute ceiling.  The final
# `required` aggregator cannot make a dependency fast if that dependency is
# still allowed to run for fifteen minutes.
for workflow in llm-eval design-system ui-quality-gate; do
  grep -q '^    timeout-minutes: 3$' ".github/workflows/${workflow}.yml" \
    || fail "${workflow} is not hard-bounded to three minutes"
done
grep -q 'timeout-minutes: 1' <<<"$required_block" \
  || fail "required aggregator is not hard-bounded to one minute"

# Keep Actions on the Node 24 generation.  Pinned SHAs preserve supply-chain
# review while avoiding the hosted-runner Node 20 deprecation path.
for workflow_path in .github/workflows/*.yml; do
  grep -q 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1' "$workflow_path" \
    || fail "${workflow_path} is not pinned to checkout v7"
  grep -q 'astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d # v10.0.1' "$workflow_path" \
    || fail "${workflow_path} is not pinned to setup-uv v10"
done
grep -q 'actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0' .github/workflows/design-system.yml \
  || fail "design-system is not pinned to setup-node v7"
for workflow_path in .github/workflows/backend-quality.yml .github/workflows/ios-quality.yml; do
  grep -q 'actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1' "$workflow_path" \
    || fail "${workflow_path} is not pinned to upload-artifact v7"
done

IOS=".github/workflows/ios-quality.yml"
grep -q "github.event.inputs.runner || 'macos-26'" "$IOS" \
  || fail "iOS workflow has no safe manual hosted-runner benchmark selector"
grep -q '^    timeout-minutes: 25$' "$IOS" \
  || fail "iOS workflow does not use the measured confidence timeout ceiling"
grep -q 'ios_ops.sh build' "$IOS" || fail "iOS workflow has no real Xcode build invocation"
grep -q -- '--unit' "$IOS" || fail "iOS workflow has no unit-test invocation"
grep -q -- '--ui' "$IOS" || fail "iOS workflow has no UI-test invocation"
grep -q -- '--dataset marketing_demo' "$IOS" || fail "UI tests do not pin a UI World dataset"
grep -q 'simulator ensure-booted' "$IOS" || fail "iOS workflow does not resolve a live simulator"
grep -q 'IOS_SIMULATOR_UDID' "$IOS" || fail "iOS workflow does not export an explicit simulator UDID"
grep -q -- '--device "$IOS_SIMULATOR_UDID"' "$IOS" || fail "iOS tests do not target the resolved simulator UDID"
if grep -q 'KG_IOS_TEST_LOG_IDLE_LIMIT' "$IOS"; then
  fail "hosted iOS workflow uses a raw log-silence watchdog; job/XCTest timeouts own liveness"
fi
grep -q "KG_IOS_TEST_MAX_EXECUTION_TIME_ALLOWANCE: '420'" "$IOS" \
  || fail "iOS workflow does not retain the bounded XCTest per-test timeout"
if grep -Eq 'KG_IOS_TEST_LOG_IDLE_LIMIT|LOG_IDLE_LIMIT|log-idle-timeout|log_idle_seconds' \
  ops/ios_test.sh ops/lib/ios_build_progress.sh; then
  fail "iOS test harness still contains a raw log-silence timeout"
fi
if grep -q 'self-hosted\|pull_request_target' "$IOS"; then
  fail "iOS workflow crosses the public fork/self-hosted trust boundary"
fi
grep -q 'actions/cache/restore@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0' "$IOS" \
  || fail "iOS workflow does not restore the pinned SwiftPM source cache"
grep -q 'actions/cache/save@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0' "$IOS" \
  || fail "iOS workflow does not save the pinned SwiftPM source cache"
if grep -q 'KG_IOS_SWIFTPM_CACHE_DIR: \${{ runner.temp }}/kg-ios-swiftpm' "$IOS"; then
  fail "iOS workflow uses runner.temp in job env, which GitHub rejects before scheduling"
fi
grep -q "KG_IOS_SWIFTPM_CACHE_DIR=%s/kg-ios-swiftpm.*\\\$RUNNER_TEMP" "$IOS" \
  || fail "iOS workflow does not export an external SwiftPM cache root for shell steps"
grep -q 'Package.resolved' "$IOS" || fail "iOS SwiftPM cache key is not lockfile-derived"
grep -q "github.event_name == 'push' && github.ref == 'refs/heads/main'" "$IOS" \
  || fail "iOS SwiftPM cache can be written outside trusted main pushes"
for ios_dependency in \
  ops/lib/project_python.sh \
  ops/lib/fixture_dataset_env.sh \
  ops/lib/userland_compat.sh \
  ops/lib/provenance.py \
  ops/review_calendar_clock.py; do
  grep -q "'$ios_dependency'" "$IOS" \
    || fail "iOS push trigger omits dependency: $ios_dependency"
done

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
