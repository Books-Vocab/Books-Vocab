#!/usr/bin/env bash
# ci_scope_router.sh — route only demonstrably affected non-blocking CI suites.
#
# This is deliberately fail-closed: an unclassified path selects every slow
# confidence suite.  It is a policy helper for pr-gate, not a work tracker.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ops/ci_scope_router.sh (--base <commit> --head <commit> | --paths-stdin | --all) [--format json|github-output]

Classify changed paths into the non-blocking backend, ops, and iOS confidence
suites. Unknown paths select every suite so a new runtime surface cannot
silently lose validation.
EOF
}

base=''
head=''
source=''
format='json'

while (($# > 0)); do
  case "$1" in
    --base)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      base="$2"
      shift 2
      ;;
    --head)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      head="$2"
      shift 2
      ;;
    --paths-stdin)
      [[ -z "$source" ]] || { usage >&2; exit 2; }
      source='stdin'
      shift
      ;;
    --all)
      [[ -z "$source" ]] || { usage >&2; exit 2; }
      source='all'
      shift
      ;;
    --format)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      format="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$format" in
  json|github-output) ;;
  *)
    printf 'unsupported format: %s\n' "$format" >&2
    exit 2
    ;;
esac

if [[ -n "$source" && ( -n "$base" || -n "$head" ) ]]; then
  printf 'choose either a commit range or an explicit change source\n' >&2
  usage >&2
  exit 2
fi

backend=false
ops=false
ios=false

select_all() {
  backend=true
  ops=true
  ios=true
}

classify_path() {
  local path="$1"
  [[ -n "$path" ]] || return

  # Router, verdict, and contract-test changes alter either test selection or
  # the meaning of a confidence result. They must receive a complete fan-out.
  case "$path" in
    ops/ci_scope_router.sh|ops/ci_confidence_verdict.sh|ops/tests/test_ci_scope_router.sh|ops/tests/test_ci_confidence_verdict.sh|ops/tests/test_github_workflows.sh|.github/workflows/pr-gate.yml)
      select_all
      return
      ;;
  esac

  # This skill declares the backend ops CLI roster exercised by backend tests.
  # Keep the contract on backend confidence without broadening all agent skills.
  case "$path" in
    .claude/skills/devops/SKILL.md)
      backend=true
      return
      ;;
  esac

  # These scripts are covered by the Linux ops suite but live outside ops/.
  case "$path" in
    devops.sh|start.sh|backend/restart_kg.sh|backend/view_logs.sh|lab/podcast/start.sh|scripts/ios_token_lint.sh|.claude/skills/app-debug/find-polluter.sh|.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh|.claude/skills/ios-simulator-verification/scripts/test_run_ui_evidence.sh)
      ops=true
      return
      ;;
  esac

  case "$path" in
    .github/workflows/backend-quality.yml)
      backend=true
      ops=true
      return
      ;;
    .github/workflows/ops-suite.yml)
      ops=true
      return
      ;;
    .github/workflows/ios-quality.yml)
      ops=true
      ios=true
      return
      ;;
    .github/workflows/*)
      ops=true
      return
      ;;
  esac

  # These files feed the real iOS build/test entrypoints or UI World fixture
  # validation. Keep this closure aligned with ios-quality.yml push.paths.
  case "$path" in
    ios/*)
      ios=true
      return
      ;;
    ops/ios_*.sh|ops/lib/ios_*.sh|ops/lib/signal_traps.sh|ops/lib/project_python.sh|ops/lib/fixture_dataset_env.sh|ops/lib/userland_compat.sh|ops/lib/provenance.py|ops/fixtures/ui_worlds/*|ops/ui_world_manifest.py|ops/review_calendar_clock.py)
      ops=true
      ios=true
      return
      ;;
  esac

  case "$path" in
    backend/*)
      backend=true
      return
      ;;
    ops/*|.claude/*)
      ops=true
      return
      ;;
  esac

  # Documentation and GitHub metadata have their own required checks. They do
  # not justify compiling an unrelated application target.
  case "$path" in
    docs/*|README.md|LICENSE|.github/ISSUE_TEMPLATE/*|.github/pull_request_template.md)
      return
      ;;
  esac

  # A new root/runtime surface has no proven ownership yet. Prefer extra CI to
  # a false-green confidence result.
  select_all
}

case "$source" in
  all)
    select_all
    ;;
  stdin)
    while IFS= read -r path || [[ -n "$path" ]]; do
      classify_path "$path"
    done
    ;;
  '')
    [[ -n "$base" && -n "$head" ]] || { usage >&2; exit 2; }
    git rev-parse --verify "${base}^{commit}" >/dev/null
    git rev-parse --verify "${head}^{commit}" >/dev/null
    while IFS= read -r -d '' path; do
      classify_path "$path"
    done < <(git diff --name-only -z "$base" "$head")
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

case "$format" in
  json)
    printf '{"backend":%s,"ops":%s,"ios":%s}\n' "$backend" "$ops" "$ios"
    ;;
  github-output)
    printf 'backend=%s\nops=%s\nios=%s\n' "$backend" "$ops" "$ios"
    ;;
esac
