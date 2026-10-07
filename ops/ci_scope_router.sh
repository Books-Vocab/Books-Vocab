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

The iOS suite additionally carries ios_mode=full|targeted. Targeted is admitted
only for exactly one changed top-level ios/BooksAndVocabUITests/*UITests.swift
file whose `ios_test.sh --ui --list --file` discovery returns fully qualified
Target/Suite/Method selectors; every other input stays ios_mode=full with an
empty ios_selectors. KG_CI_IOS_SELECTOR_DISCOVERY overrides the discovery
command for contract tests only.
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

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DISCOVERY="${KG_CI_IOS_SELECTOR_DISCOVERY:-$ROOT/ops/ios_test.sh}"

backend=false
ops=false
ios=false
path_count=0
single_path=''
ios_mode=full
ios_selectors=''

select_all() {
  backend=true
  ops=true
  ios=true
}

classify_path() {
  local path="$1"
  [[ -n "$path" ]] || return
  path_count=$((path_count + 1))
  single_path="$path"

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

  # lab/podcast tests run in the Linux ops suite (lab-podcast group, Issue #2064);
  # the rest of lab/ keeps routing fail-closed.
  case "$path" in
    lab/podcast/*)
      ops=true
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

# Targeted iOS admission. Every failure path returns non-zero and leaves the
# default ios_mode=full / empty selectors untouched (fail-closed).
discover_targeted_selectors() {
  local path="$1" base out line suite_method selectors='' count=0 header_count=''
  base="${path##*/}"

  [[ "$path" =~ ^ios/BooksAndVocabUITests/[A-Za-z0-9_+.-]+UITests\.swift$ ]] || return 1
  case "$(printf '%s' "$base" | tr '[:upper:]' '[:lower:]')" in
    *fixture*|*helper*|*page*|*support*) return 1 ;;
  esac
  [[ -f "$ROOT/$path" && ! -L "$ROOT/$path" ]] || return 1

  out="$(cd "$ROOT" && "$DISCOVERY" --ui --list --file "$path" 2>/dev/null)" || return 1
  [[ -n "$out" ]] || return 1

  while IFS= read -r line; do
    # Only fully qualified method selectors (plus ios_test.sh's own single
    # "matched N tests" header); anything else (suite-only, unknown target,
    # blank/noise line) rejects the whole discovery.
    if [[ "$line" =~ ^-only-testing:BooksAndVocabUITests/([A-Za-z0-9_]+/[A-Za-z0-9_]+)$ ]]; then
      suite_method="${BASH_REMATCH[1]}"
      selectors="${selectors:+$selectors }$suite_method"
      count=$((count + 1))
    elif [[ "$line" =~ ^\[ios_test\]\ matched\ ([0-9]+)\ tests?\ in\ file\  && -z "$header_count" ]]; then
      header_count="${BASH_REMATCH[1]}"
    else
      return 1
    fi
  done <<<"$out"

  [[ -n "$selectors" ]] || return 1
  # A header that disagrees with the selector lines means discovery is not
  # self-consistent; do not trust either side.
  [[ -z "$header_count" || "$header_count" -eq "$count" ]] || return 1
  ios_selectors="$selectors"
  ios_mode=targeted
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

if [[ "$source" != all && "$ios" == true && "$backend" == false && "$ops" == false && "$path_count" -eq 1 ]]; then
  discover_targeted_selectors "$single_path" || { ios_mode=full; ios_selectors=''; }
fi

case "$format" in
  json)
    jq -cn --argjson backend "$backend" --argjson ops "$ops" --argjson ios "$ios" \
      --arg mode "$ios_mode" --arg selectors "$ios_selectors" \
      '{backend:$backend,ops:$ops,ios:$ios,ios_mode:$mode,ios_selectors:$selectors}'
    ;;
  github-output)
    printf 'backend=%s\nops=%s\nios=%s\nios_mode=%s\nios_selectors=%s\n' \
      "$backend" "$ops" "$ios" "$ios_mode" "$ios_selectors"
    ;;
esac
