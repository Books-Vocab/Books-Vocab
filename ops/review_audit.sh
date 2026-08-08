#!/usr/bin/env bash
# review_audit.sh — audit whether commits carry a review receipt or an explicit exemption.
#
# Usage:
#   ./ops/review_audit.sh
#   ./ops/review_audit.sh --base origin/main
#   ./ops/review_audit.sh --rev-range main..HEAD
#   ./ops/review_audit.sh --json
#
# Contract:
#   - reviewed commit:   contains `Reviewed-by: <reviewer>`
#   - exempt commit:     contains `Review-Exempt: <reason>`
#   - allowed exemptions: trivial-typo | rename-only | format-only | generated-snapshot |
#                         single-line-small-file | machine-repair | backlog-grooming
#                         (the last two are CHECKED: ledger paths only)
#   - `single-line-small-file` is also machine-checked: non-merge, at most one added
#     and one deleted line, with no normative wording in the added line. The other
#     four semantic tokens remain trailer-only by design.
#
# Audited repo: $KG_REVIEW_AUDIT_ROOT, else the git toplevel of the CALLER's cwd, else
# the repo this script lives in. The chosen root is always echoed to stderr.
#
# Exit codes:
#   0 = every audited commit is reviewed or validly exempted
#   2 = at least one commit is missing a receipt or carries an invalid exemption

set -euo pipefail

BASE="origin/main"
REV_RANGE=""
JSON=0

usage() {
  awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
}

die() {
  echo "review_audit: $*" >&2
  exit 2
}

need_jq() {
  command -v jq >/dev/null 2>&1 || die "需要 jq 產生 JSON"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      [[ -n "${2:-}" ]] || die "--base 需要值"
      BASE="$2"
      shift 2
      ;;
    --rev-range)
      [[ -n "${2:-}" ]] || die "--rev-range 需要值"
      REV_RANGE="$2"
      shift 2
      ;;
    --json)
      JSON=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown arg: $1"
      ;;
  esac
done

# jq is only used to build the --json payload; a text-mode run must not turn a
# missing jq into a hard failure, or wiring this into the cutover gate would make
# jq a hard dependency of every cutover.
[[ "${JSON:-0}" -eq 1 ]] && need_jq

# Root resolution deliberately sits AFTER argument parsing: `--help` should neither
# chdir nor emit anything, and `usage` reads "$0", which a prior cd can invalidate
# when the script was invoked by a relative path from another directory.
#
# An interface that looks like it takes the caller's cwd and doesn't is one that
# invites wrong calls. This used to cd to the SCRIPT's own repo unconditionally, so
# `( cd elsewhere && review_audit.sh )` silently audited KG's own history — which is
# exactly how test_gate_can_fail.sh's review-receipts red proof came to depend on
# KG's recent commits instead of on its fixture, and rotted green when they all
# gained trailers (IMP-0049). The script's repo remains the last resort so calling it
# from outside any git repo still works.
if [[ -n "${KG_REVIEW_AUDIT_ROOT:-}" ]]; then
  ROOT="$KG_REVIEW_AUDIT_ROOT"
elif ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" && [[ -n "$ROOT" ]]; then
  :
else
  ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fi
cd "$ROOT"
ROOT="$(pwd -P)"
# Never silent: which repo was audited is the one fact that made the wrong answer
# survive undetected, and it costs one line to state.
echo "review_audit: auditing $ROOT" >&2

if [[ -z "$REV_RANGE" ]]; then
  git rev-parse --verify "$BASE^{commit}" >/dev/null 2>&1 || die "base 不存在: $BASE"
  REV_RANGE="$BASE..HEAD"
fi

tmp_json="$(mktemp)"
trap 'rm -f "$tmp_json"' EXIT

block_count=0
ok_count=0
reviewed_count=0
exempt_count=0
missing_count=0
invalid_exemption_count=0

EXEMPTION_NOTE=""
EXEMPTION_FAIL_REASON=""

# $1 = token, $2 = the commit's file list, one path per line.
#
# Most tokens are claims about the *nature* of a diff that this script cannot
# check — it takes the author's word. `machine-repair` and `backlog-grooming` are
# deliberately not two of those: the former is claimed by
# `worktree_orchestrate.py`'s post-landing ledger repair, while the latter is for
# a human/agent grooming batch. Both are held to the same path constraint. A token
# that a machine emits and no machine checks is just a wider hole in the review gate.
#
# Pure bash, no jq: text mode must keep working without jq (that is why `need_jq`
# only fires for `--json`), and a decision path that needs a tool the surrounding
# contract says is optional is a gate that fails open on the machines that lack it.
is_allowed_exemption() {
  local token="$1" files="$2" line stray=""
  EXEMPTION_NOTE=""
  case "$token" in
    trivial-typo|rename-only|format-only|generated-snapshot|single-line-small-file)
      return 0
      ;;
    machine-repair|backlog-grooming)
      # An EMPTY file list is refused, not waved through. It is what an empty commit
      # produces, and what an unreadable diff produces — "nothing to object to" and
      # "could not look" are the same string here, and treating the second as the
      # first is the failure mode this whole gate exists to prevent.
      if [[ -z "${files//[[:space:]]/}" ]]; then
        EXEMPTION_NOTE="$token over a commit with no files — an empty or unreadable diff is not evidence that nothing needs review"
        return 1
      fi
      while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        # git quotes paths with spaces or non-ASCII bytes; a quoted path can never
        # equal an unquoted literal, so it lands in `stray` and blocks. Refusing to
        # classify a name you cannot read is the correct direction to fail.
        if [[ "$line" =~ ^docs/runbook/backlog/[^/]+\.json$ ]]; then
          continue
        fi
        stray+="${stray:+, }$line"
      done <<<"$files"
      if [[ -z "$stray" ]]; then
        return 0
      fi
      EXEMPTION_NOTE="$token only covers the backlog ledger (docs/runbook/backlog/*.json); this commit also touches: $stray"
      return 1
      ;;
    *)
      return 1
      ;;
  esac
}

# `single-line-small-file` has an objective shape, so the exemption must prove that
# shape instead of trusting the trailer. The other four semantic tokens remain
# self-asserted: a shell script cannot reliably decide whether a typo, rename,
# formatting-only, or generated snapshot claim is true.
single_line_exemption_holds() {
  local sha="$1" parents added deleted a d added_lines

  parents="$(git rev-list --parents -n 1 "$sha" | wc -w)"
  [[ "$parents" -le 2 ]] || { EXEMPTION_FAIL_REASON="merge commit"; return 1; }

  added=0
  deleted=0
  while IFS=$'\t' read -r a d _; do
    [[ -n "$a" ]] || continue
    if [[ "$a" == "-" || "$d" == "-" ]]; then
      EXEMPTION_FAIL_REASON="binary change"
      return 1
    fi
    added=$((added + a))
    deleted=$((deleted + d))
  done < <(git show --numstat --format= "$sha")

  # A one-line edit is +1/-1, so bound each side rather than their sum.
  if [[ "$added" -gt 1 || "$deleted" -gt 1 ]]; then
    EXEMPTION_FAIL_REASON="+${added}/-${deleted} lines, not a single line"
    return 1
  fi

  added_lines="$(git show --unified=0 --format= "$sha" | grep '^+' | grep -v '^+++' || true)"
  # Use a herestring rather than `grep -q` in a pipeline: under pipefail, an early
  # match can SIGPIPE its producer and turn a real match into a false green.
  if grep -Eq '必須|禁止|不得|一律|通則|規則|規範|應該|應當|MUST|NEVER|ALWAYS' <<<"$added_lines"; then
    EXEMPTION_FAIL_REASON="normative wording in the added line"
    return 1
  fi
  return 0
}

while IFS= read -r sha; do
  [[ -n "$sha" ]] || continue

  subject="$(git show -s --format=%s "$sha")"
  body="$(git show -s --format=%B "$sha")"
  reviewed_by="$(printf '%s\n' "$body" | sed -n 's/^Reviewed-by:[[:space:]]*//p' | tail -n 1)"
  review_exempt="$(printf '%s\n' "$body" | sed -n 's/^Review-Exempt:[[:space:]]*//p' | tail -n 1)"

  # `--no-renames` and `--diff-merges=first-parent` are not cosmetic. Measured, both
  # as ways past the checked `machine-repair` exemption below:
  #   * a rename of `secret.txt` into the ledger directory prints only the NEW name,
  #     so a commit that moved an arbitrary file in read as ledger-only;
  #   * `git show --name-only` on a MERGE prints nothing at all, so an evil merge
  #     read as a commit that touched no files.
  files_raw="$(
    git show --pretty='' --name-only --no-renames --diff-merges=first-parent "$sha" \
      | sed '/^$/d'
  )"
  files_json='[]'
  if [[ "$JSON" -eq 1 ]]; then
    files_json="$(printf '%s\n' "$files_raw" | sed '/^$/d' | jq -R . | jq -s 'map(select(length > 0))')"
  fi

  status=""
  level="ok"
  note=""

  if [[ -n "$reviewed_by" ]]; then
    status="reviewed"
    note="Reviewed-by: $reviewed_by"
    reviewed_count=$((reviewed_count + 1))
    ok_count=$((ok_count + 1))
  elif [[ -n "$review_exempt" ]]; then
    EXEMPTION_FAIL_REASON=""
    if is_allowed_exemption "$review_exempt" "$files_raw" \
       && { [[ "$review_exempt" != "single-line-small-file" ]] || single_line_exemption_holds "$sha"; }; then
      status="exempt"
      note="Review-Exempt: $review_exempt"
      exempt_count=$((exempt_count + 1))
      ok_count=$((ok_count + 1))
    else
      status="invalid-exemption"
      level="block"
      if [[ -n "$EXEMPTION_FAIL_REASON" ]]; then
        note="invalid Review-Exempt: $review_exempt ($EXEMPTION_FAIL_REASON)"
      else
        note="invalid Review-Exempt: $review_exempt${EXEMPTION_NOTE:+ — $EXEMPTION_NOTE}"
      fi
      invalid_exemption_count=$((invalid_exemption_count + 1))
      block_count=$((block_count + 1))
    fi
  else
    status="missing-review"
    level="block"
    note="missing Reviewed-by or Review-Exempt trailer"
    missing_count=$((missing_count + 1))
    block_count=$((block_count + 1))
  fi

  jq -nc \
    --arg commit "$sha" \
    --arg subject "$subject" \
    --arg status "$status" \
    --arg level "$level" \
    --arg note "$note" \
    --arg reviewedBy "$reviewed_by" \
    --arg reviewExempt "$review_exempt" \
    --argjson files "$files_json" \
    '{
      commit:$commit,
      shortSha:($commit[0:8]),
      subject:$subject,
      status:$status,
      level:$level,
      note:$note,
      trailers:{
        reviewedBy:($reviewedBy // null),
        reviewExempt:($reviewExempt // null)
      },
      files:$files
    }' >>"$tmp_json"

  if [[ "$JSON" -eq 0 ]]; then
    printf '[review][%s] %s %s\n' "$level" "$sha" "$subject"
    printf '  %s\n' "$note"
  fi
done < <(git rev-list --reverse "$REV_RANGE")

if [[ "$JSON" -eq 1 ]]; then
  jq -s \
    --arg base "$BASE" \
    --arg revRange "$REV_RANGE" \
    '{
      schema:"kg.review_audit.v1",
      base:($base | select(length > 0)),
      revRange:$revRange,
      summary:{
        total:length,
        ok:([.[] | select(.level=="ok")] | length),
        block:([.[] | select(.level=="block")] | length),
        reviewed:([.[] | select(.status=="reviewed")] | length),
        exempt:([.[] | select(.status=="exempt")] | length),
        missing:([.[] | select(.status=="missing-review")] | length),
        invalidExemption:([.[] | select(.status=="invalid-exemption")] | length)
      },
      commits:.
    }' "$tmp_json"
fi

if [[ "$block_count" -gt 0 ]]; then
  exit 2
fi
exit 0
