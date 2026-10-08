#!/usr/bin/env bash
# test_github_workflows.sh — keep the GitHub-native CI topology executable.
#
# The component workflows are reusable building blocks. pr-gate owns the
# pull_request entrypoint and merge-group-required owns the merge queue
# entrypoint; both expose the same `required` context without importing
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
# A deleted file cannot be format-checked (ruff errors on the missing path), so every
# changed-file listing feeding the format step must exclude deletions or any PR that
# removes a Python file fails repo-gate.
listings="$(grep -c 'git diff --name-only' "$PR_GATE" || true)"
filtered="$(grep -c 'git diff --name-only --diff-filter=d' "$PR_GATE" || true)"
{ [[ "$listings" -ge 1 ]] && [[ "$listings" == "$filtered" ]]; } \
  || fail "pr-gate lists deleted files for the format check (${filtered}/${listings} listings filter deletions)"
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
grep -Fq 'done < <(git diff --name-only --diff-filter=d "$diff_base_sha" "$HEAD_SHA" -- '\''*.py'\'')' <<<"$repo_gate_block" \
  || fail "changed-Python format step is not bound to the merge-base/head diff"
grep -Fq 'git diff --check "$(git merge-base "$BASE_SHA" "$HEAD_SHA")" "$HEAD_SHA"' <<<"$repo_gate_block" \
  || fail "repo-gate whitespace check is not bound to the merge-base/head diff"
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
  # Job-level bound only (4-space indent): short gate plus the backend pytest
  # suite must fit; 15 minutes was too tight for both.
  grep -Eq '^    timeout-minutes: 25$' <<<"$merge_group_required_block" \
    || fail "merge-group required gate is not hard-bounded to twenty-five minutes"
  # ubuntu-latest is a moving label; the apt ffmpeg series follows the image and
  # the podcast preview skip allowlist turns a changed series into a red queue.
  grep -Eq '^    runs-on: ubuntu-24\.04$' <<<"$merge_group_required_block" \
    || fail "merge-group required gate is not pinned to ubuntu-24.04"
  grep -Fq "version: '0.8.23'" <<<"$merge_group_required_block" \
    || fail "merge-group required gate does not pin uv to the backend-quality version"
  grep -q 'github.event.merge_group.base_sha' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group required gate does not use the merge-group base SHA"
  grep -q 'github.event.merge_group.head_sha' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group required gate does not use the merge-group head SHA"
  grep -Fq './ops/test_ops.sh docs-lint worktree context-routing github-workflows delivery-control' <<<"$merge_group_required_block" \
    || fail "merge-group required gate does not execute the delivery-control regression group"
  if grep -Eq 'ops-suite|ios-quality|llm-eval|ui-quality-gate|confidence' <<<"$merge_group_required_block"; then
    fail "merge-group required gate imports slow confidence jobs"
  fi
  if grep -Eq 'uses:[[:space:]]*\./\.github/workflows/backend-quality\.yml' <<<"$merge_group_required_block"; then
    fail "merge-group required gate must run the backend suite inline, not import backend-quality"
  fi
  # Backend suite runs inline, but only behind the fail-closed scope router.
  scope_step_id="$(awk '
    /^      - name:/ { id="" }
    /^        id:/ { id=$2 }
    /ci_scope_router\.sh --base "\$BASE_SHA" --head "\$HEAD_SHA" --format github-output/ { print id; exit }
  ' <<<"$merge_group_required_block")"
  [[ -n "$scope_step_id" ]] \
    || fail "merge-group required gate has no id'd step running ci_scope_router.sh --format github-output"
  backend_pytest_step="$(awk '
    /^      - / { if (in_step && has_pytest) { printf "%s", buf; exit } in_step=1; has_pytest=0; buf="" }
    in_step { buf = buf $0 "\n" }
    /uv run python -m pytest -q -rs --skip-allowlist=tests\/skip_allowlist\.json/ { has_pytest=1 }
    END { if (in_step && has_pytest) printf "%s", buf }
  ' <<<"$merge_group_required_block")"
  [[ -n "$backend_pytest_step" ]] \
    || fail "merge-group required gate does not run the backend pytest suite"
  # Anchored to a live step-level key: a commented-out `# if: ...` must not pass.
  grep -Eq "^        if: steps\.${scope_step_id}\.outputs\.backend == 'true'\$" <<<"$backend_pytest_step" \
    || fail "merge-group backend pytest step is not guarded by the router backend output"
  grep -Fq 'working-directory: backend' <<<"$backend_pytest_step" \
    || fail "merge-group backend pytest step does not run in backend/"
  grep -Fq 'uv sync --locked' <<<"$backend_pytest_step" \
    || fail "merge-group backend pytest step does not sync the locked environment"
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
    || fail "merge-group independent review gate does not consume derived membership"
  # The merge_group event payload carries no pull_requests list, so a join()
  # over it is always empty and the gate failed on every run.
  if grep -q 'merge_group.pull_requests' "$MERGE_GROUP_REQUIRED"; then
    fail "merge-group independent review gate reads merge_group.pull_requests, which the event payload never provides"
  fi
  grep -Fq 'MERGE_GROUP_PR_NUMBERS: ${{ steps.membership.outputs.pr_numbers }}' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not take membership from the derive step output"
  grep -q 'membership evidence' "$MERGE_GROUP_REQUIRED" \
    || fail "merge-group independent review gate does not fail closed without membership evidence"
  membership_step="$(awk '
    /^      - name: Derive merge-group membership$/ { in_step=1; next }
    in_step && /^      - name:/ { exit }
    in_step && /^  [A-Za-z0-9_-]+:/ { exit }
    in_step { print }
  ' "$MERGE_GROUP_REQUIRED")"
  [[ -n "$membership_step" ]] \
    || fail "merge-group workflow has no 'Derive merge-group membership' step"
  grep -q '^        id: membership$' <<<"$membership_step" \
    || fail "merge-group membership step has no id: membership"
  grep -Fq 'github.event.merge_group.head_ref' <<<"$membership_step" \
    || fail "merge-group membership step does not derive PRs from merge_group.head_ref"
  membership_script="$(awk '
    /^        run: \|$/ { grab=1; next }
    grab { sub(/^          /, ""); print }
  ' <<<"$membership_step")"
  if [[ -z "$membership_script" ]]; then
    fail "merge-group membership step has no run script"
  else
    # Behavioural check: execute the step's own script against a fixture repo.
    membership_tmp="$(mktemp -d)"
    membership_repo="$membership_tmp/repo"
    mfx() { git -C "$membership_repo" -c user.name=t -c user.email=t@example.com -c commit.gpgsign=false "$@"; }
    run_membership() { # head_ref base_sha head_sha -> GITHUB_OUTPUT content; status = script status
      : >"$membership_tmp/out"
      (cd "$membership_repo" && GITHUB_OUTPUT="$membership_tmp/out" GITHUB_REF="" \
        MERGE_GROUP_HEAD_REF="$1" MERGE_GROUP_BASE_SHA="$2" MERGE_GROUP_HEAD_SHA="$3" \
        bash -c "$membership_script") >/dev/null 2>&1 || return 1
      cat "$membership_tmp/out"
    }
    git init -q -b main "$membership_repo"
    mfx commit -q --allow-empty -m base
    m_base="$(mfx rev-parse HEAD)"
    mfx checkout -q -b pr11
    mfx commit -q --allow-empty -m "Merge pull request #99 from evil/forged-subject-on-plain-commit"
    mfx checkout -q main
    mfx merge -q --no-ff pr11 -m "Merge pull request #11 from Books-Vocab/lane-a"
    m_solo="$(mfx rev-parse HEAD)"
    mfx checkout -q -b pr12
    mfx commit -q --allow-empty -m work
    mfx checkout -q main
    mfx merge -q --no-ff pr12 -m "Merge pull request #12 from Books-Vocab/lane-b"
    m_group="$(mfx rev-parse HEAD)"
    out="$(run_membership "refs/heads/gh-readonly-queue/main/pr-11-$m_base" "$m_base" "$m_solo" || true)"
    [[ "$out" == "pr_numbers=11" ]] \
      || fail "membership step, solo group: expected pr_numbers=11, got '$out' (a plain commit with a forged subject must be ignored)"
    out="$(run_membership "refs/heads/gh-readonly-queue/main/pr-12-$m_base" "$m_base" "$m_group" || true)"
    [[ "$out" == "pr_numbers=11,12" ]] \
      || fail "membership step, multi-PR group: expected pr_numbers=11,12, got '$out'"
    out="$(run_membership "refs/heads/gh-readonly-queue/main/pr-7-$m_base" "$m_base" "$m_base" || true)"
    [[ "$out" == "pr_numbers=7" ]] \
      || fail "membership step must still name the head_ref PR when history has no merge commits, got '$out'"
    if run_membership "refs/heads/gh-readonly-queue/main/no-pr-here" "$m_base" "$m_solo" >/dev/null; then
      fail "membership step accepts a head_ref that names no PR"
    fi
    rm -rf "$membership_tmp"
  fi
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

# --- iOS selector-aware routing (Issue #1051) --------------------------------
# The router decides; ios-quality re-validates and owns the full fallback. These
# checks pin both the wiring and the executable shell of the two decision steps.
grep -Fq 'ios_mode: ${{ steps.plan.outputs.ios_mode }}' "$PR_GATE" \
  || fail "pr-gate changed-paths does not export the router ios_mode"
grep -Fq 'ios_selectors: ${{ steps.plan.outputs.ios_selectors }}' "$PR_GATE" \
  || fail "pr-gate changed-paths does not export the router ios_selectors"
grep -Fq 'ios_mode: ${{ needs.changed-paths.outputs.ios_mode }}' "$PR_GATE" \
  || fail "pr-gate does not forward ios_mode to ios-quality"
grep -Fq 'ios_selectors: ${{ needs.changed-paths.outputs.ios_selectors }}' "$PR_GATE" \
  || fail "pr-gate does not forward ios_selectors to ios-quality"

ruby -e 'require "yaml"; y = YAML.load_file(ARGV[0]); i = y[true]["workflow_call"]["inputs"]
  exit 1 unless i["ios_mode"]["default"] == "full" && i["ios_selectors"]["default"] == "" &&
    i["ios_mode"]["type"] == "string" && i["ios_selectors"]["type"] == "string" &&
    i["ios_mode"]["required"] == false && i["ios_selectors"]["required"] == false' "$IOS" \
  || fail "ios-quality workflow_call inputs are not optional string inputs defaulting to full"
grep -q '^  plan:' "$IOS" || fail "ios-quality has no fail-closed plan job"
grep -q '^  ios-targeted:' "$IOS" || fail "ios-quality has no targeted job"
# Full path is the default: both full jobs run unless a validated targeted run
# accepted its own result, and a failed/skipped plan still means full.
full_gate="if: \${{ always() && (needs.plan.outputs.mode != 'targeted' || needs.ios-targeted.outputs.fallback_full == 'true') }}"
[[ "$(grep -cF "$full_gate" "$IOS")" == 2 ]] \
  || fail "ios-build and ios-tests are not both gated as full-unless-targeted-accepted"
grep -Fq "if: \${{ needs.plan.outputs.mode == 'targeted' }}" "$IOS" \
  || fail "targeted job is not gated on a validated targeted plan"
grep -Fq "matrix.scope" "$IOS" && grep -Fq -- '- scope: unit' "$IOS" && grep -Fq -- '- scope: ui-smoke' "$IOS" \
  || fail "full iOS matrix (unit, ui-smoke) was altered"
# Targeted invocation: exactly the planned selectors, no video/visual capture.
grep -Fq "KG_IOS_VISUAL_CAPTURE: '0'" "$IOS" \
  || fail "targeted iOS run does not pin KG_IOS_VISUAL_CAPTURE=0"
if grep -Eq -- '--visual|--visual-capture|KG_IOS_VISUAL_CAPTURE: .1|KG_IOS_VISUAL_ROOT|--video' "$IOS"; then
  fail "iOS workflow enables visual capture or video"
fi
grep -Fq '"${selectors[@]}"' "$IOS" \
  || fail "targeted iOS run does not pass exactly the planned selectors"
if awk '/^  ios-targeted:/{on=1} on' "$IOS" | grep -Eq -- '--file|--grep|-g '; then
  fail "targeted iOS run widens selection beyond the planned selectors"
fi
grep -Fq 'IOS_TARGETED_SELECTORS: ${{ needs.plan.outputs.selectors }}' "$IOS" \
  || fail "targeted job selectors do not come from the validated plan output"
grep -Fq 'false-green-0-executed' "$IOS" \
  || fail "targeted job does not wire the zero-executed guard to the full fallback"
grep -Fq 'fallback_full: ${{ steps.verdict.outputs.fallback_full }}' "$IOS" \
  || fail "targeted job does not export the full-fallback signal"

extract_step_run() {
  ruby -e 'require "yaml"; y = YAML.load_file(ARGV[0])
    step = y["jobs"][ARGV[1]]["steps"].find { |s| s["id"] == ARGV[2] }
    abort "missing step" unless step
    puts step["run"]' "$IOS" "$1" "$2"
}

wf_tmp="$(mktemp -d)"
trap 'rm -rf "$wf_tmp"' EXIT
extract_step_run plan plan > "$wf_tmp/plan.sh"
extract_step_run ios-targeted verdict > "$wf_tmp/verdict.sh"

# plan: only a strictly valid single-line Suite/Method list stays targeted.
plan_mode() {
  local out="$wf_tmp/plan.out"
  : > "$out"
  REQUESTED_MODE="$1" REQUESTED_SELECTORS="$2" GITHUB_OUTPUT="$out" bash "$wf_tmp/plan.sh" >/dev/null 2>&1 || { echo ERROR; return; }
  grep '^mode=' "$out" | head -1 | cut -d= -f2-
}
expect_plan() {
  local label="$1" mode="$2" selectors="$3" expected="$4" actual
  actual="$(plan_mode "$mode" "$selectors")"
  [[ "$actual" == "$expected" ]] || fail "ios plan: $label expected $expected, got $actual"
}
expect_plan 'valid single selector' targeted 'OverviewFlowUITests/testA' targeted
expect_plan 'valid multiple selectors' targeted 'OverviewFlowUITests/testA OverviewFlowUITests/testB' targeted
expect_plan 'missing mode' '' 'OverviewFlowUITests/testA' full
expect_plan 'explicit full' full 'OverviewFlowUITests/testA' full
expect_plan 'case-variant mode' TARGETED 'OverviewFlowUITests/testA' full
expect_plan 'unknown mode' narrow 'OverviewFlowUITests/testA' full
expect_plan 'targeted without selectors' targeted '' full
expect_plan 'whitespace-only selectors' targeted '   ' full
expect_plan 'suite-only selector' targeted 'OverviewFlowUITests' full
expect_plan 'target-qualified selector' targeted 'BooksAndVocabUITests/OverviewFlowUITests/testA' full
expect_plan 'valid plus invalid selector' targeted 'OverviewFlowUITests/testA bad' full
expect_plan 'shell metacharacters' targeted 'OverviewFlowUITests/test;rm' full
expect_plan 'command substitution' targeted '$(id)/testA' full
expect_plan 'newline output injection' targeted $'OverviewFlowUITests/testA\nmode=targeted' full

# verdict: success needs the exact executed count; zero-test guard and count
# mismatch fall back to full; genuine red stays red.
run_verdict() {
  local outcome="$1" verdict="$2" out="$wf_tmp/verdict.out" json="$wf_tmp/verdict.json" rc=0
  : > "$out"
  rm -f "$json"
  [[ "$verdict" == '-' ]] || printf '%s\n' "$verdict" > "$json"
  RUN_OUTCOME="$outcome" VERDICT_JSON="$json" IOS_TARGETED_SELECTORS='OverviewFlowUITests/testA OverviewFlowUITests/testB' \
    GITHUB_OUTPUT="$out" bash "$wf_tmp/verdict.sh" >/dev/null 2>&1 || rc=$?
  if grep -qx 'fallback_full=true' "$out"; then
    echo "fallback rc=$rc"
  else
    echo "plain rc=$rc"
  fi
}
expect_verdict() {
  local label="$1" outcome="$2" verdict="$3" expected="$4" actual
  actual="$(run_verdict "$outcome" "$verdict")"
  [[ "$actual" == "$expected" ]] || fail "ios verdict: $label expected '$expected', got '$actual'"
}
expect_verdict 'exact executed count passes' success '{"result":"ok","executed":"2"}' 'plain rc=0'
expect_verdict 'executed below selector count falls back' success '{"result":"ok","executed":"1"}' 'fallback rc=0'
expect_verdict 'executed above selector count falls back' success '{"result":"ok","executed":"3"}' 'fallback rc=0'
expect_verdict 'zero executed falls back' success '{"result":"ok","executed":"0"}' 'fallback rc=0'
expect_verdict 'missing executed falls back' success '{"result":"ok","executed":null}' 'fallback rc=0'
expect_verdict 'non-numeric executed falls back' success '{"result":"ok","executed":"two"}' 'fallback rc=0'
expect_verdict 'success without a verdict file falls back' success - 'fallback rc=0'
expect_verdict 'harness zero-test guard falls back' failure '{"result":"fail","reason":"false-green-0-executed","executed":"0"}' 'fallback rc=0'
expect_verdict 'genuine test failure stays red' failure '{"result":"fail","reason":"tests-failed","executed":"2"}' 'plain rc=1'
expect_verdict 'build failure stays red' failure '{"result":"fail","reason":"build-failed","executed":null}' 'plain rc=1'
expect_verdict 'failure without a verdict stays red' failure - 'plain rc=1'
expect_verdict 'cancelled run stays red' cancelled - 'plain rc=1'


OPS=".github/workflows/ops-suite.yml"
grep -q 'fromJSON' "$OPS" || fail "ops-suite does not derive its matrix from the classified group list"
grep -q 'matrix.shard' "$OPS" || fail "ops-suite has no parallel shard matrix"
grep -q 'SHARD_COUNT' "$OPS" || fail "ops-suite does not pin the shard partition count"
if grep -q 'Run platform-independent ops groups' "$OPS"; then
  fail "ops-suite still runs all Linux groups serially"
fi
# Issue #2064: lab/podcast tests run in the lab-podcast group, so a push that
# only touches lab/podcast must still trigger ops-suite (the PR path is the router).
grep -Fq "      - 'lab/podcast/**'" "$OPS" \
  || fail "ops-suite push paths do not cover lab/podcast/** (lab-podcast group)"

# --- Token scope and liveness ceilings (Issue #2070) -------------------------
# Every workflow pins its own GITHUB_TOKEN scope instead of inheriting the repo
# default (read today, but a settings change would silently widen it), and every
# job that runs steps carries its own timeout. A `uses:` job delegates the
# timeout to the called workflow, but its own permissions are still checked.
# Writes, at workflow or job level, must match an allowlist entry with exactly the
# keys workflow, job (null = workflow-level, else a job name), scope and reason;
# write-all is never allowlistable, and a stale entry is itself a violation.
WRITE_ALLOWLIST="ops/tests/github_workflow_write_allowlist.json"
! compgen -G '.github/workflows/*.yaml' >/dev/null || fail "a .yaml workflow escapes every *.yml guard in this file; rename it to .yml"
workflow_hardening_violations() {
  ruby -e 'require "yaml"; require "json"
    keys = %w[workflow job scope reason]
    allow = JSON.parse(File.read(ARGV.shift))["entries"].each_with_index.select do |e, i|
      e = {} unless e.is_a?(Hash)
      errs = [("missing key(s) #{(keys - e.keys).join(", ")}" if (keys - e.keys).any?),
        ("unknown key(s) #{(e.keys - keys).join(", ")}" if (e.keys - keys).any?)].compact
      errs << "workflow, scope and reason must be non-empty strings" unless errs.any? || %w[workflow scope reason].all? { |k| e[k].is_a?(String) && !e[k].strip.empty? }
      errs << "job must be null (workflow-level) or a non-empty string" unless errs.any? || e["job"].nil? || (e["job"].is_a?(String) && !e["job"].strip.empty?)
      puts("allowlist entry #{i}: #{errs.join("; ")}") if errs.any?
      errs.empty?
    end.map(&:first)
    used = []
    check = lambda do |path, job, perms|
      where = "#{path}: #{job ? "job #{job}" : "top-level"} permissions"
      next puts("#{where} is #{perms.inspect}") unless perms.is_a?(Hash) || perms == "read-all"
      (perms == "read-all" ? {} : perms).each do |scope, value|
        next if %w[read none].include?(value)
        hit = allow.find { |e| [e["workflow"], e["job"], e["scope"]] == [File.basename(path), job, scope] }
        next used << hit if value == "write" && hit
        puts "#{where} #{scope}: #{value.inspect} is not read/none or an allowlisted write"
      end
    end
    ARGV.each do |path|
      y = YAML.load_file(path)
      y.key?("permissions") ? check.(path, nil, y["permissions"]) : puts("#{path}: no top-level permissions")
      (y["jobs"] || {}).each do |name, job|
        check.(path, name, job["permissions"]) if job.key?("permissions")
        next if job.key?("uses")
        puts "#{path}: job #{name} has no timeout-minutes" unless job.key?("timeout-minutes")
      end
    end
    (allow - used).each { |e| puts "allowlist: #{e["workflow"]} #{e["job"] ? "job #{e["job"]}" : "top-level"} #{e["scope"]} matches no write grant" }' "$@"
}
if hardening_report="$(workflow_hardening_violations "$WRITE_ALLOWLIST" .github/workflows/*.yml)"; then
  while IFS= read -r violation; do
    if [[ -n "$violation" ]]; then
      fail "$violation"
    fi
  done <<<"$hardening_report"
else
  fail "workflow hardening checker could not read .github/workflows/*.yml"
fi

# Positive control: the checker must name each defect in a fixture that has
# them (mapped and job-level writes, write-all, invalid or stale allowlist
# entries), and must pass `uses:` jobs, read-only maps and allowlisted writes.
hardening_tmp="$wf_tmp/hardening"
mkdir -p "$hardening_tmp"
cat >"$hardening_tmp/bare.yml" <<'YAML'
on: push
jobs: {steps-job: {steps: [{run: 'true'}]}, reusable-job: {uses: ./.github/workflows/llm-eval.yml}}
YAML
cat >"$hardening_tmp/write-all.yml" <<'YAML'
{on: push, permissions: write-all, jobs: {bounded: {timeout-minutes: 1}}}
YAML
cat >"$hardening_tmp/mixed.yml" <<'YAML'
on: push
permissions: {contents: write, statuses: write, deployments: write}
jobs:
  job-write-all: {timeout-minutes: 1, permissions: write-all}
  job-unlisted: {timeout-minutes: 1, permissions: {pull-requests: write}}
  job-listed: {timeout-minutes: 1, permissions: {issues: write, contents: read}}
  job-read-only: {timeout-minutes: 1, permissions: {contents: read, actions: none}}
  job-read-all: {timeout-minutes: 1, permissions: read-all}
  job-none: {timeout-minutes: 1, permissions: {}}
YAML
# Entries 0-1 are valid grants; 2-8 must not authorize (stale, wrong job, wrong workflow, no reason,
# missing job key, misspelled job key, empty job). 6-7 would otherwise read as job nil = top-level.
cat >"$hardening_tmp/allow.json" <<'JSON'
{"entries": [{"workflow": "mixed.yml", "job": null, "scope": "statuses", "reason": "r"},
  {"workflow": "mixed.yml", "job": "job-listed", "scope": "issues", "reason": "r"},
  {"workflow": "mixed.yml", "job": "job-read-only", "scope": "contents", "reason": "r"},
  {"workflow": "mixed.yml", "job": "job-write-all", "scope": "contents", "reason": "r"},
  {"workflow": "write-all.yml", "job": "job-unlisted", "scope": "pull-requests", "reason": "r"},
  {"workflow": "mixed.yml", "job": "job-unlisted", "scope": "pull-requests", "reason": " "},
  {"workflow": "mixed.yml", "scope": "contents", "reason": "r"},
  {"workflow": "mixed.yml", "jobs": null, "scope": "deployments", "reason": "r"},
  {"workflow": "mixed.yml", "job": "", "scope": "pull-requests", "reason": "r"}]}
JSON
expected_fixture_report="allowlist entry 5: workflow, scope and reason must be non-empty strings
allowlist entry 6: missing key(s) job
allowlist entry 7: missing key(s) job; unknown key(s) jobs
allowlist entry 8: job must be null (workflow-level) or a non-empty string
$hardening_tmp/bare.yml: no top-level permissions
$hardening_tmp/bare.yml: job steps-job has no timeout-minutes
$hardening_tmp/write-all.yml: top-level permissions is \"write-all\"
$hardening_tmp/mixed.yml: top-level permissions contents: \"write\" is not read/none or an allowlisted write
$hardening_tmp/mixed.yml: top-level permissions deployments: \"write\" is not read/none or an allowlisted write
$hardening_tmp/mixed.yml: job job-write-all permissions is \"write-all\"
$hardening_tmp/mixed.yml: job job-unlisted permissions pull-requests: \"write\" is not read/none or an allowlisted write
allowlist: mixed.yml job job-read-only contents matches no write grant
allowlist: mixed.yml job job-write-all contents matches no write grant
allowlist: write-all.yml job job-unlisted pull-requests matches no write grant"
actual_fixture_report="$(workflow_hardening_violations "$hardening_tmp/allow.json" "$hardening_tmp"/{bare,write-all,mixed}.yml 2>&1 || true)"
[[ "$actual_fixture_report" == "$expected_fixture_report" ]] \
  || fail "workflow hardening checker positive control: expected [$expected_fixture_report], got [$actual_fixture_report]"

# Falsification: every real allowlist entry is load-bearing. Dropping any one
# must turn the live check red with exactly that grant.
while IFS=$'\t' read -r index workflow where scope; do
  jq "del(.entries[$index])" "$WRITE_ALLOWLIST" >"$hardening_tmp/drop.json"
  dropped_report="$(workflow_hardening_violations "$hardening_tmp/drop.json" .github/workflows/*.yml 2>&1 || true)"
  grep -Fxq ".github/workflows/$workflow: $where permissions $scope: \"write\" is not read/none or an allowlisted write" <<<"$dropped_report" \
    || fail "dropping allowlist entry $index ($workflow $where $scope) left the live check green: [$dropped_report]"
done < <(jq -r '.entries | to_entries[] | [.key, .value.workflow, (if .value.job then "job \(.value.job)" else "top-level" end), .value.scope] | @tsv' "$WRITE_ALLOWLIST")

# --- Push-to-main runs must never be cancelled by a newer push ----------------
# Merges land every few minutes. A workflow that has a `push` trigger and an
# unconditional `cancel-in-progress: true` cancels every previous main run when
# the next merge lands, so no post-merge run ever completes (ios-quality lost
# its only post-merge iOS health signal this way). Only pull_request runs may
# cancel in progress; push/dispatch runs queue (one running + one pending, a
# newer pending replaces an older pending), so the latest main commit is always
# validated to completion. Workflows without a `push` trigger are out of scope.
push_cancel_violations() {
  ruby -e 'require "yaml"
    ARGV.each do |path|
      y = YAML.load_file(path)
      on = y[true] || y["on"]
      next unless on.is_a?(Hash) && on.key?("push")
      next unless y["concurrency"].is_a?(Hash)
      cancel = y["concurrency"]["cancel-in-progress"]
      puts "#{path}: push-triggered workflow cancels in-progress runs unconditionally" if cancel == true
    end' "$@"
}
live_push_cancel="$(push_cancel_violations .github/workflows/*.yml 2>&1 || true)"
[[ -z "$live_push_cancel" ]] \
  || fail "push-triggered workflow cancels main runs: [$live_push_cancel]"
grep -Fxq "  cancel-in-progress: \${{ github.event_name == 'pull_request' }}" "$IOS" \
  || fail "ios-quality does not restrict cancel-in-progress to pull_request runs"
# Positive control: the checker flags an unconditional cancel next to a push
# trigger and passes the conditional form and a pull_request-only workflow.
cancel_tmp="$wf_tmp/cancel"
mkdir -p "$cancel_tmp"
cat >"$cancel_tmp/push-cancel.yml" <<'YAML'
on: {push: {branches: [main]}}
concurrency: {group: g, cancel-in-progress: true}
jobs: {}
YAML
cat >"$cancel_tmp/push-conditional.yml" <<'YAML'
on: {push: {branches: [main]}}
concurrency: {group: g, cancel-in-progress: "${{ github.event_name == 'pull_request' }}"}
jobs: {}
YAML
cat >"$cancel_tmp/pr-only.yml" <<'YAML'
on: {pull_request: {}}
concurrency: {group: g, cancel-in-progress: true}
jobs: {}
YAML
expected_cancel_report="$cancel_tmp/push-cancel.yml: push-triggered workflow cancels in-progress runs unconditionally"
actual_cancel_report="$(push_cancel_violations "$cancel_tmp"/{push-cancel,push-conditional,pr-only}.yml 2>&1 || true)"
[[ "$actual_cancel_report" == "$expected_cancel_report" ]] \
  || fail "push cancel checker positive control: expected [$expected_cancel_report], got [$actual_cancel_report]"

# --- PR diffs start at the merge base, never at the base branch tip -----------
# `pull_request.base.sha` is main's tip when the run starts, not the PR's fork
# point. Once main has moved past the fork, `git diff BASE HEAD` also contains
# the reverse of every newer main commit, so repo-gate reported whitespace
# errors in files the PR never touched (PR #2291 failed on
# ops/felix_compute_worker.py, which #2285 deleted on main after the fork).
# Any diff that means "this PR's changes" must start from `git merge-base`.
# merge_group workflows are exempt: a queue group's head contains its base, so
# base..head already is the group's change set.
two_point_diff_violations() {
  local file
  for file in "$@"; do
    # Drop `$(git merge-base ...)` operands first: they legitimately mention
    # both SHAs but are the fix, not the defect.
    sed -E 's/\$\(git merge-base [^)]*\)/MERGE_BASE/g' "$file" \
      | grep -nE 'git diff[^|;&]*(\$\{?BASE_SHA\}?"?[[:space:]]+"?\$\{?HEAD_SHA|\$\{?BASE_SHA\}?"?\.\.[^.])' \
      | sed "s|^|${file}:|" || true
  done
}
pr_diff_workflows=()
for workflow_file in .github/workflows/*.yml; do
  grep -Eq '^[[:space:]]*merge_group:' "$workflow_file" || pr_diff_workflows+=("$workflow_file")
done
live_two_point="$(two_point_diff_violations "${pr_diff_workflows[@]}")"
[[ -z "$live_two_point" ]] \
  || fail "PR workflow diffs BASE_SHA against HEAD_SHA directly instead of the merge base: [$live_two_point]"

# Positive control: the checker names each two-point spelling and passes the
# merge-base forms (inline `$(git merge-base ...)`, a variable, three-dot).
tp_tmp="$wf_tmp/two-point"
mkdir -p "$tp_tmp"
cat >"$tp_tmp/bad.yml" <<'YAML'
        run: |
          git diff --check "$BASE_SHA" "$HEAD_SHA"
          git diff --name-only --diff-filter=d "$BASE_SHA" "$HEAD_SHA" -- '*.py'
          git diff --stat ${BASE_SHA} ${HEAD_SHA}
          git diff "$BASE_SHA".."$HEAD_SHA"
YAML
cat >"$tp_tmp/good.yml" <<'YAML'
        run: |
          git diff --check "$(git merge-base "$BASE_SHA" "$HEAD_SHA")" "$HEAD_SHA"
          git diff --check "$merge_base" "$HEAD_SHA"
          git diff "$BASE_SHA"..."$HEAD_SHA"
          git merge-base --is-ancestor "$BASE_SHA" "$HEAD_SHA"
YAML
tp_bad_lines="$(two_point_diff_violations "$tp_tmp/bad.yml" | cut -d: -f2 | tr '\n' ' ')"
[[ "$tp_bad_lines" == '2 3 4 5 ' ]] \
  || fail "two-point diff checker positive control: expected lines [2 3 4 5 ], got [$tp_bad_lines]"
tp_good_report="$(two_point_diff_violations "$tp_tmp/good.yml")"
[[ -z "$tp_good_report" ]] \
  || fail "two-point diff checker flags merge-base forms: [$tp_good_report]"

# Behavior: run the real pr-gate steps against a repository whose base branch
# moved past the PR's fork point (deleting a file whose blank line at EOF is a
# `git diff --check` error, and adding a Python file the PR never touched).
extract_named_step_run() {
  ruby -e 'require "yaml"; y = YAML.load_file(ARGV[0])
    step = y["jobs"][ARGV[1]]["steps"].find { |s| s["name"] == ARGV[2] }
    abort "missing step #{ARGV[2]}" unless step
    puts step["run"]' "$1" "$2" "$3"
}
mb_dir="$wf_tmp/merge-base"
mb_repo="$mb_dir/repo"
mkdir -p "$mb_repo" "$mb_dir/bin"
extract_named_step_run "$PR_GATE" repo-gate "Check repository diff" > "$mb_dir/diff-check.sh"
extract_named_step_run "$PR_GATE" repo-gate "Check changed Python formatting" > "$mb_dir/format.sh"
# `uv` stub: record the arguments instead of downloading and running ruff.
cat >"$mb_dir/bin/uv" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$UV_ARGS_OUT"
SH
chmod +x "$mb_dir/bin/uv"
(
  cd "$mb_repo"
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.invalid GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.invalid
  git init -q -b main
  git config commit.gpgsign false
  git config core.hooksPath /dev/null
  printf 'clean\n' > clean.txt
  printf 'quirk\n\n' > legacy.txt
  printf 'x = 1\n' > old.py
  git add -A
  git commit -q -m fork-point
  git checkout -q -b pr
  printf 'feature\n' > feature.txt
  printf 'y = 2\n' > pr.py
  git add -A
  git commit -q -m pr-change
  git checkout -q -b pr-dirty main
  printf 'trailing  \n' > dirty.txt
  git add -A
  git commit -q -m pr-whitespace-error
  git checkout -q main
  git rm -q legacy.txt old.py
  printf 'z = 3\n' > main_only.py
  git add -A
  git commit -q -m main-moves-on
  git checkout -q -b pr-rebased main
  printf 'w = 4\n' > rebased.py
  git add -A
  git commit -q -m pr-on-top-of-main
)
mb_run() { # <script> <base ref> <head ref> -> step exit status; extra env passes through
  local script="$1" base="$2" head="$3" rc=0
  (
    cd "$mb_repo"
    git checkout -q --detach "$head"
    BASE_SHA="$(git rev-parse "$base")" HEAD_SHA="$(git rev-parse "$head")" bash "$script" >/dev/null 2>&1
  ) || rc=$?
  echo "$rc"
}
mb_rc="$(mb_run "$mb_dir/diff-check.sh" main pr)"
[[ "$mb_rc" == 0 ]] \
  || fail "repo-gate diff check fails a PR that never touched a file main deleted after the fork (exit $mb_rc)"
mb_rc="$(mb_run "$mb_dir/diff-check.sh" main pr-dirty)"
[[ "$mb_rc" != 0 ]] \
  || fail "repo-gate diff check passes a PR that introduces trailing whitespace (positive control)"
mb_py() { # <base ref> <head ref> -> python paths handed to ruff
  local out="$mb_dir/uv-args.$1.$2" rc
  rc="$(UV_ARGS_OUT="$out" PATH="$mb_dir/bin:$PATH" mb_run "$mb_dir/format.sh" "$1" "$2")"
  if [[ "$rc" == 0 && -f "$out" ]]; then
    grep -E '\.py$' "$out" | tr '\n' ' '
  else
    printf 'exit-%s' "$rc"
  fi
}
mb_py_got="$(mb_py main pr)"
[[ "$mb_py_got" == 'pr.py ' ]] \
  || fail "format step lists main's post-fork Python changes for a diverged PR: [$mb_py_got]"
mb_py_got="$(mb_py main pr-rebased)"
[[ "$mb_py_got" == 'rebased.py ' ]] \
  || fail "format step mislists Python paths for a PR already on top of base: [$mb_py_got]"

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
