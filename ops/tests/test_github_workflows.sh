#!/usr/bin/env bash
# test_github_workflows.sh — keep the GitHub-native CI topology executable.
#
# The component workflows are reusable building blocks. pr-gate owns the
# pull_request entrypoint and merge-group-required owns the merge queue
# entrypoint; both expose the same short `required` contract without importing
# the slow confidence fan-out into the merge queue.

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
grep -Fq 'if: ${{ github.event_name == '\''workflow_dispatch'\'' }}' "$PR_GATE" \
  || fail "pr-gate does not guard manual dispatches"
grep -Fq 'if [[ "$EVENT_SHA" != "$HEAD_SHA" ]]' "$PR_GATE" \
  || fail "pr-gate does not bind manual dispatches to the event SHA"
if grep -Eq '^[[:space:]]*merge_group:' "$PR_GATE"; then
  fail "pr-gate still owns a merge_group trigger; merge queue requires the short dedicated workflow"
fi

PR_READINESS=".github/workflows/pr-readiness.yml"
grep -Eq 'types: \[[^]]*edited' "$PR_READINESS" \
  || fail "pr-readiness does not rerun after PR body metadata repair"
grep -q '^  workflow_dispatch:' "$PR_READINESS" \
  || fail "pr-readiness has no explicit metadata-race dispatch path"
grep -q 'pr_number:' "$PR_READINESS" \
  || fail "pr-readiness dispatch has no exact PR number input"
grep -q 'head_sha:' "$PR_READINESS" \
  || fail "pr-readiness dispatch has no exact HEAD input"
grep -Fq 'gh api "repos/$GITHUB_REPOSITORY/pulls/$PR_NUMBER"' "$PR_READINESS" \
  || fail "pr-readiness does not read the live PR body"
grep -Fq './ops/delivery.py validate-pr-body --head-sha "$HEAD_SHA"' "$PR_READINESS" \
  || fail "pr-readiness does not use the typed delivery receipt validator"
if grep -Eq 'grep .*Base SHA|perl -ne.*Digest' "$PR_READINESS"; then
  fail "pr-readiness duplicates typed receipt parsing in workflow shell"
fi
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
grep -Fq 'needs: [repo-gate]' "$PR_GATE" \
  || fail "pr-gate required job is not repo-gate-only"
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
grep -Fqx '    needs: [repo-gate]' <<<"$required_block" \
  || fail "pr-gate required job is not the short repo-gate-only merge gate"
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
grep -Fq './ops/test_ops.sh docs-lint worktree context-routing github-workflows delivery-control' <<<"$repo_gate_block" \
  || fail "repo-gate does not execute the delivery-control regression group"
grep -Fq '      - name: Check changed Python formatting' <<<"$repo_gate_block" \
  || fail "repo-gate has no bounded changed-Python format step"
grep -Fq 'for sha_name in BASE_SHA HEAD_SHA; do' <<<"$repo_gate_block" \
  || fail "changed-Python format step does not validate both exact refs"
grep -Fq 'git rev-parse --verify "$sha^{commit}"' <<<"$repo_gate_block" \
  || fail "changed-Python format step does not fail closed on an unresolved base/head"
grep -Fq 'actual_sha="$(git rev-parse HEAD)"' <<<"$repo_gate_block" \
  || fail "changed-Python format step does not bind the checkout to HEAD_SHA"
grep -Fq 'while IFS= read -r path; do' <<<"$repo_gate_block" \
  || fail "changed-Python format step is not Bash 3.2-compatible"
grep -Fq '[[ -n "$path" ]] && changed_python+=("$path")' <<<"$repo_gate_block" \
  || fail "changed-Python format step does not collect non-empty paths safely"
grep -Fq 'done < <(git diff --name-only "$BASE_SHA" "$HEAD_SHA" -- '\''*.py'\'')' <<<"$repo_gate_block" \
  || fail "changed-Python format step is not bound to the exact base/head diff"
grep -Fq 'if ((${#changed_python[@]} == 0)); then' <<<"$repo_gate_block" \
  || fail "changed-Python format step has no empty-set pass path"
grep -Fq 'uv run --no-project --python 3.13 --with '\''ruff==0.16.3'\'' ruff format --check "${changed_python[@]}"' <<<"$repo_gate_block" \
  || fail "changed-Python format step does not invoke the pinned ruff formatter"
delivery_control_group="$(awk '
  /delivery-control\)/ { in_group=1 }
  in_group { print }
  in_group && /^[[:space:]]*;;$/ { exit }
' ops/test_ops.sh)"
grep -Fq 'delivery_tests=(ops/tests/test_delivery_*.py)' <<<"$delivery_control_group" \
  || fail "delivery-control group does not declare the complete delivery-test glob"
grep -Fq '"${delivery_tests[@]}"' <<<"$delivery_control_group" \
  || fail "delivery-control group does not execute the discovered delivery-test array"
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

MERGE_GROUP_REQUIRED=".github/workflows/merge-group-required.yml"
[[ -f "$MERGE_GROUP_REQUIRED" ]] \
  || fail "missing dedicated merge-group required workflow: $MERGE_GROUP_REQUIRED"
if [[ -f "$MERGE_GROUP_REQUIRED" ]]; then
  grep -q '^  merge_group:' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group required workflow has no merge_group trigger"
  grep -Fqx '    types: [checks_requested]' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group required workflow is not limited to checks_requested"
  grep -q '^  required:' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group required workflow has no required job"
  merge_group_required_block="$(awk '
    /^  required:/ { in_required=1; next }
    in_required && /^  [A-Za-z0-9_-]+:/ { exit }
    in_required { print }
  ' "$MERGE_GROUP_REQUIRED")"
  grep -q 'timeout-minutes: 3' <<<"$merge_group_required_block" \
    || fail "merge-group required gate is not hard-bounded to three minutes"
  grep -q 'github.event.merge_group.base_sha' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group required gate does not use the merge-group base SHA"
  grep -q 'github.event.merge_group.head_sha' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group required gate does not use the merge-group head SHA"
  grep -Fq './ops/test_ops.sh docs-lint worktree context-routing github-workflows delivery-control' <<<"$merge_group_required_block" \
    || fail "merge-group required gate does not execute the delivery-control regression group"
  if grep -Eq 'backend-quality|ops-suite|ios-quality|llm-eval|ui-quality-gate|confidence' <<<"$merge_group_required_block"; then
    fail "merge-group required gate imports slow confidence jobs"
  fi
  grep -q '^  agent-review:' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group required workflow has no independent review gate"
  agent_review_block="$(awk '
    /^  agent-review:/ { in_review=1; next }
    in_review && /^  [A-Za-z0-9_-]+:/ { exit }
    in_review { print }
  ' "$MERGE_GROUP_REQUIRED")"
  grep -q '^    name: agent-review$' <<<"$agent_review_block" \
    || fail "merge-group independent review gate does not emit the required context"
  grep -q 'github.event.merge_group.head_sha' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate is not bound to the merge-group HEAD"
  grep -q 'mergeQueue' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not read queue membership"
  if grep -q 'headCommit.oid == "\$group_sha"' "$MERGE_GROUP_REQUIRED"; then
    fail "merge-group independent review gate compares the synthetic group SHA to the PR head"
  fi
  grep -q 'pullRequest.headRefOid' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not bind queue membership to the PR head ref"
  if grep -q 'solo == true' "$MERGE_GROUP_REQUIRED"; then
    fail "merge-group independent review gate incorrectly rejects grouped entries"
  fi
  grep -q 'group_pr_numbers' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not enumerate grouped PRs"
  grep -q 'target_position' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not bound group membership by queue position"
  grep -q 'MERGE_GROUP_PR_NUMBERS' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not consume explicit event membership"
  grep -q 'merge_group.pull_requests' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not bind membership to merge-group event evidence"
  grep -q 'membership evidence' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not fail closed without membership evidence"
  if grep -q 'maximumEntriesToMerge\|maximum_entries_to_merge' "$MERGE_GROUP_REQUIRED"; then
    fail "merge-group independent review gate infers membership from a configured ceiling"
  fi
  grep -q 'range(.*target_position' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not prove contiguous queue membership"
  grep -q 'for group_pr_number in' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not validate each grouped PR"
  grep -q 'check-runs' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not read PR check evidence"
  grep -q 'sort_by' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not select the latest exact-head review run"
  grep -q 'last' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not select the latest exact-head review run"
  grep -q 'review_candidates=' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate filters review status before selecting the latest observation"
  grep -q 'updated_at' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not order review observations by update time"
  grep -q 'review_status' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not validate the selected latest review status"
  grep -q 'review_provenance' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not isolate malformed review provenance"
  grep -q 'external_id' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not bind evidence to the trusted review check artifact"
  grep -q 'details_url' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not bind evidence to a workflow run"
  grep -q 'workflow_id' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not verify trusted workflow identity"
  grep -q 'agent-review.yml' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not identify the trusted workflow"
  grep -q '^  actions: read$' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not have Actions read permission"
  grep -q 'pull_requests' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not verify PR association"
  grep -q 'head.sha' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not bind PR association to exact HEAD"
  grep -q 'issue_comment' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not handle trusted issue-comment provenance"
  grep -q 'Independent agent review' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not validate trusted review output"
  grep -q 'startswith' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not distinguish the trusted review artifact"
  grep -q '== "completed"' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not require completed exact-head evidence"
  grep -q '== "success"' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not require successful exact-head evidence"
  queue_membership_fixture='[{"position":2},{"position":3},{"position":4},{"position":5}]'
  jq -e 'map(.position) as $positions | ($positions | min) as $start | ($positions | max) as $target_position | ($positions | unique | length) == ($positions | length) and ($positions | sort) == [range($start; ($target_position + 1))]' \
    <<<"$queue_membership_fixture" >/dev/null \
    || fail "merge-group fixture rejects a valid group larger than three entries"
  noncontiguous_fixture='[{"position":2},{"position":4}]'
  if jq -e 'map(.position) as $positions | ($positions | min) as $start | ($positions | max) as $target_position | ($positions | unique | length) == ($positions | length) and ($positions | sort) == [range($start; ($target_position + 1))]' \
    <<<"$noncontiguous_fixture" >/dev/null; then
    fail "merge-group fixture accepts non-contiguous membership"
  fi
  review_fixture='[{"updated_at":"2026-08-26T15:00:00Z","status":"completed","conclusion":"success"},{"updated_at":"2026-08-26T15:01:00Z","status":"in_progress","conclusion":""}]'
  latest_review_status="$(jq -r 'sort_by(.updated_at) | last.status' <<<"$review_fixture")"
  [[ "$latest_review_status" == "in_progress" ]] \
    || fail "review fixture does not select the newer in-progress observation"
  malformed_review_fixture='[{"details_url":"not-a-run","external_id":"wrong"}]'
  [[ "$(jq '[.[] | select((.details_url | startswith("https://github.com/")) and (.external_id | startswith("kg.agent-review.v1:")))] | length' <<<"$malformed_review_fixture")" == "0" ]] \
    || fail "review fixture accepts malformed provenance"
fi

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
