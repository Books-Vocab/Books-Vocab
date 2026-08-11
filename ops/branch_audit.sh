#!/usr/bin/env bash
# branch_audit.sh — audit remote branches by commit reachability, with PR status as metadata.
#
# Usage:
#   ./ops/branch_audit.sh
#   ./ops/branch_audit.sh --json
#   ./ops/branch_audit.sh --delete-merged --dry-run
#   ./ops/branch_audit.sh --delete-merged --yes
#
# Exit codes:
#   0 = only safe-delete / open-pr branches
#   2 = at least one orphan-ahead / stale-ahead block
#   3 = at least one merged-pr-but-ahead warning (and no block)

set -euo pipefail

EXIT_OK=0
EXIT_TOOL_ERROR=1
EXIT_BLOCK=2
EXIT_WARN=3
EXIT_USAGE=64

ROOT="${KG_BRANCH_AUDIT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

BASE="origin/main"
REMOTE="origin"
JSON=0
FETCH=1
DELETE_MERGED=0
YES=0
STALE_DAYS="${STALE_DAYS:-30}"

usage() {
  awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
}

die() {
  echo "branch_audit: $*" >&2
  exit "$EXIT_USAGE"
}

need_jq() {
  if ! command -v jq >/dev/null 2>&1; then
    echo "branch_audit: 需要 jq 解析 gh JSON" >&2
    exit "$EXIT_TOOL_ERROR"
  fi
}

json_bool() {
  case "$1" in
    1|true) echo true ;;
    *) echo false ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      [[ -n "${2:-}" ]] || die "--base 需要值"
      BASE="$2"
      shift 2
      ;;
    --remote)
      [[ -n "${2:-}" ]] || die "--remote 需要值"
      REMOTE="$2"
      shift 2
      ;;
    --json)
      JSON=1
      shift
      ;;
    --no-fetch)
      FETCH=0
      shift
      ;;
    --delete-merged)
      DELETE_MERGED=1
      shift
      ;;
    --dry-run)
      YES=0
      shift
      ;;
    --yes)
      YES=1
      shift
      ;;
    --stale-days)
      [[ -n "${2:-}" ]] || die "--stale-days 需要值"
      [[ "$2" =~ ^[0-9]+$ ]] || die "--stale-days 必須是整數"
      STALE_DAYS="$2"
      shift 2
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

need_jq

if [[ "$FETCH" -eq 1 ]]; then
  git fetch --all --prune
fi

git rev-parse --verify "$BASE^{commit}" >/dev/null 2>&1 || die "base 不存在: $BASE"

tmp_json="$(mktemp)"
trap 'rm -f "$tmp_json"' EXIT

now_epoch="$(date +%s)"
warn_count=0
block_count=0
total_count=0

while IFS= read -r branch; do
  [[ -n "$branch" ]] || continue
  [[ "$branch" == "$REMOTE" ]] && continue
  [[ "$branch" == "$REMOTE/HEAD" ]] && continue
  [[ "$branch" == "$BASE" ]] && continue

  total_count=$((total_count + 1))
  short="${branch#"$REMOTE/"}"
  ahead="$(git rev-list --count "$BASE..$branch")"
  last_epoch="$(git log -1 --format=%ct "$branch")"
  age_days=$(( (now_epoch - last_epoch) / 86400 ))

  pr_json="[]"
  if command -v gh >/dev/null 2>&1; then
    pr_json="$(gh pr list --state all --head "$short" --json number,state,mergedAt,title,url,headRefName,updatedAt 2>/dev/null || printf '[]')"
  fi
  if ! printf '%s' "$pr_json" | jq -e 'type=="array"' >/dev/null 2>&1; then
    pr_json="[]"
  fi

  open_number="$(printf '%s' "$pr_json" | jq -r '[.[] | select(.state=="OPEN")] | .[0].number // empty')"
  open_url="$(printf '%s' "$pr_json" | jq -r '[.[] | select(.state=="OPEN")] | .[0].url // empty')"
  merged_number="$(printf '%s' "$pr_json" | jq -r '[.[] | select((.mergedAt // "") != "" or .state=="MERGED")] | .[0].number // empty')"
  merged_url="$(printf '%s' "$pr_json" | jq -r '[.[] | select((.mergedAt // "") != "" or .state=="MERGED")] | .[0].url // empty')"

  level="ok"
  status="safe-delete"
  note="fully merged -> safe-delete"
  stale=0
  if [[ "$age_days" -ge "$STALE_DAYS" ]]; then
    stale=1
  fi

  if [[ "$ahead" -eq 0 ]]; then
    status="safe-delete"
    level="ok"
    note="fully merged -> safe-delete"
  elif [[ -n "$open_number" ]]; then
    status="open-pr"
    level="ok"
    note="open PR #$open_number, $ahead commits not in $BASE"
  elif [[ -n "$merged_number" ]]; then
    status="merged-pr-but-ahead"
    level="warn"
    note="PR #$merged_number merged but branch has $ahead commits not in $BASE"
    warn_count=$((warn_count + 1))
  elif [[ "$stale" -eq 1 ]]; then
    status="stale-ahead"
    level="block"
    note="stale-ahead age=${age_days}d, no open PR, $ahead commits not in $BASE"
    block_count=$((block_count + 1))
  else
    status="orphan-ahead"
    level="block"
    note="no open PR and $ahead commits not in $BASE"
    block_count=$((block_count + 1))
  fi

  jq -nc \
    --arg branch "$branch" \
    --arg short "$short" \
    --arg base "$BASE" \
    --arg status "$status" \
    --arg level "$level" \
    --arg note "$note" \
    --arg openNumber "$open_number" \
    --arg openUrl "$open_url" \
    --arg mergedNumber "$merged_number" \
    --arg mergedUrl "$merged_url" \
    --argjson ahead "$ahead" \
    --argjson ageDays "$age_days" \
    --argjson stale "$(json_bool "$stale")" \
    '{branch:$branch, shortName:$short, base:$base, status:$status, level:$level, ahead:$ahead, ageDays:$ageDays, stale:$stale, openPrNumber:($openNumber|tonumber? // null), openPrUrl:($openUrl // null), mergedPrNumber:($mergedNumber|tonumber? // null), mergedPrUrl:($mergedUrl // null), note:$note}' \
    >>"$tmp_json"

  if [[ "$JSON" -eq 0 ]]; then
    printf '[branch][%s] %s %s\n' "$level" "$branch" "$note"
    if [[ "$ahead" -gt 0 && "$level" != "ok" ]]; then
      git log --oneline --decorate "$BASE..$branch" | sed 's/^/  /'
    fi
    if [[ "$DELETE_MERGED" -eq 1 && "$status" == "safe-delete" ]]; then
      if [[ "$YES" -eq 1 ]]; then
        git push "$REMOTE" --delete "$short"
        printf '[branch][delete] %s deleted from %s\n' "$branch" "$REMOTE"
      else
        printf '[branch][delete][dry-run] would run: git push %s --delete %s\n' "$REMOTE" "$short"
      fi
    fi
  fi
done < <(git for-each-ref --format='%(refname:short)' "refs/remotes/$REMOTE" | sort)

if [[ "$JSON" -eq 1 ]]; then
  jq -s \
    --arg base "$BASE" \
    --arg remote "$REMOTE" \
    --argjson staleDays "$STALE_DAYS" \
    --argjson deleteMerged "$(json_bool "$DELETE_MERGED")" \
    --argjson dryRun "$(json_bool "$((1 - YES))")" \
    '{
      schema:"kg.branch_audit.v1",
      base:$base,
      remote:$remote,
      staleDays:$staleDays,
      deleteMerged:$deleteMerged,
      dryRun:$dryRun,
      summary:{
        total:length,
        ok:([.[] | select(.level=="ok")] | length),
        warn:([.[] | select(.level=="warn")] | length),
        block:([.[] | select(.level=="block")] | length)
      },
      branches:.
    }' "$tmp_json"
fi

if [[ "$block_count" -gt 0 ]]; then
  exit "$EXIT_BLOCK"
fi
if [[ "$warn_count" -gt 0 ]]; then
  exit "$EXIT_WARN"
fi
exit "$EXIT_OK"
