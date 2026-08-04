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
#   - allowed exemptions: trivial-typo | rename-only | format-only | generated-snapshot | single-line-small-file
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

is_allowed_exemption() {
  case "$1" in
    trivial-typo|rename-only|format-only|generated-snapshot|single-line-small-file)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

while IFS= read -r sha; do
  [[ -n "$sha" ]] || continue

  subject="$(git show -s --format=%s "$sha")"
  body="$(git show -s --format=%B "$sha")"
  reviewed_by="$(printf '%s\n' "$body" | sed -n 's/^Reviewed-by:[[:space:]]*//p' | tail -n 1)"
  review_exempt="$(printf '%s\n' "$body" | sed -n 's/^Review-Exempt:[[:space:]]*//p' | tail -n 1)"

  files_json="$(
    git show --pretty='' --name-only "$sha" \
      | sed '/^$/d' \
      | jq -R . \
      | jq -s 'map(select(length > 0))'
  )"

  status=""
  level="ok"
  note=""

  if [[ -n "$reviewed_by" ]]; then
    status="reviewed"
    note="Reviewed-by: $reviewed_by"
    reviewed_count=$((reviewed_count + 1))
    ok_count=$((ok_count + 1))
  elif [[ -n "$review_exempt" ]]; then
    if is_allowed_exemption "$review_exempt"; then
      status="exempt"
      note="Review-Exempt: $review_exempt"
      exempt_count=$((exempt_count + 1))
      ok_count=$((ok_count + 1))
    else
      status="invalid-exemption"
      level="block"
      note="invalid Review-Exempt: $review_exempt"
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
