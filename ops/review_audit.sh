#!/usr/bin/env bash
# review_audit.sh — audit one external reviewer/control-plane manifest.
#
# The manifest is evidence from an external connector.  This script deliberately
# does not inspect ops/task_registry.py, local PIDs, or a commit message: a local
# subprocess is not evidence about a multi_agent_v1 target.
#
# Usage:
#   ./ops/review_audit.sh --manifest <path> [--kind <kind>] [--json]
#
# Kinds are inferred from the required fields when --kind is omitted:
#   wait-interrupt   target_id + request/returned_status steps
#   review-capacity  reviewer_id + dispatch_status/queue_transition steps
#   external-agent   target_id + transition/fail_closed steps
#
# Exit codes:
#   0 = manifest is structurally verified
#   1 = audit tool error
#   2 = manifest is missing, malformed, or fails the contract
#   64 = invalid command-line usage

set -euo pipefail

EXIT_OK=0
EXIT_TOOL_ERROR=1
EXIT_BLOCK=2
EXIT_USAGE=64

MANIFEST=""
KIND=""
JSON=0

usage() {
  sed -n '2,24p' "$0" | sed 's/^# \?//'
}

die_usage() {
  echo "review_audit: $*" >&2
  exit "$EXIT_USAGE"
}

if ! command -v jq >/dev/null 2>&1; then
  echo "review_audit: jq is required for manifest validation" >&2
  exit "$EXIT_TOOL_ERROR"
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest)
      [[ -n "${2:-}" ]] || die_usage "--manifest requires a path"
      MANIFEST="$2"
      shift 2
      ;;
    --kind)
      [[ -n "${2:-}" ]] || die_usage "--kind requires a value"
      KIND="$2"
      shift 2
      ;;
    --json)
      JSON=1
      shift
      ;;
    -h|--help)
      usage
      exit "$EXIT_OK"
      ;;
    *)
      die_usage "unknown argument: $1"
      ;;
  esac
done

[[ -n "$MANIFEST" ]] || die_usage "--manifest is required"

status="block"
reason=""
resolved_kind="$KIND"

if [[ ! -f "$MANIFEST" ]]; then
  reason="manifest does not exist: $MANIFEST"
elif ! jq -e . "$MANIFEST" >/dev/null 2>&1; then
  reason="manifest is not valid JSON: $MANIFEST"
else
  if [[ -z "$resolved_kind" ]]; then
    resolved_kind="$(jq -r '
      if ((.target_id? | type) == "string") and
         any(.steps[]?; ((type == "object") and has("request"))) then
        "wait-interrupt"
      elif ((.reviewer_id? | type) == "string") and
           any(.steps[]?; ((type == "object") and has("dispatch_status"))) then
        "review-capacity"
      elif ((.target_id? | type) == "string") and
           any(.steps[]?; ((type == "object") and has("transition"))) then
        "external-agent"
      else
        "unknown"
      end
    ' "$MANIFEST")"
  fi

  valid_common=1
  if ! jq -e '
    (.status == "verified") and
    (.steps | type == "array") and
    ((.steps | length) >= 1)
  ' "$MANIFEST" >/dev/null 2>&1; then
    valid_common=0
    reason="status must be verified and steps must be a non-empty array"
  fi

  # A manifest must not smuggle local process identity in as external evidence.
  # Keys are checked recursively; evidence_path values remain opaque connector
  # references and are not interpreted as repo-local proof.
  if [[ "$valid_common" -eq 1 ]] && ! jq -e '
    [.. | objects | keys[]? |
      test("(^|_)(pid|pgid|process_id)$|task_registry"; "i")] |
    all(.[]; . == false)
  ' "$MANIFEST" >/dev/null 2>&1; then
    valid_common=0
    reason="manifest uses local PID/task-registry fields instead of opaque API evidence"
  fi

  if [[ "$valid_common" -eq 1 ]]; then
    case "$resolved_kind" in
      wait-interrupt)
        if ! jq -e '
          ((.target_id | type) == "string") and
          (.target_id | length > 0) and
          ((.steps | length) >= 2) and
          all(.steps[];
            (type == "object") and
            ((.request | type) == "string") and
            ((.request | length) > 0) and
            ((.returned_status | type) == "string") and
            ((.returned_status | length) > 0) and
            ((.evidence_path | type) == "string") and
            ((.evidence_path | length) > 0)
          )
        ' "$MANIFEST" >/dev/null 2>&1; then
          reason="wait-interrupt manifest lacks target, request, returned status, or evidence"
        else
          status="pass"
        fi
        ;;
      review-capacity)
        if ! jq -e '
          ((.reviewer_id | type) == "string") and
          (.reviewer_id | length > 0) and
          all(.steps[];
            (type == "object") and
            ((.dispatch_status | type) == "string") and
            ((.dispatch_status | length) > 0) and
            ((.queue_transition | type) == "string") and
            ((.queue_transition | length) > 0) and
            ((.evidence_path | type) == "string") and
            ((.evidence_path | length) > 0)
          )
        ' "$MANIFEST" >/dev/null 2>&1; then
          reason="review-capacity manifest lacks reviewer, dispatch, queue, or evidence"
        else
          status="pass"
        fi
        ;;
      external-agent)
        if ! jq -e '
          ((.target_id | type) == "string") and
          (.target_id | length > 0) and
          all(.steps[];
            (type == "object") and
            ((.transition | type) == "string") and
            ((.transition | length) > 0) and
            ((.fail_closed | type) == "boolean") and
            ((.evidence_path | type) == "string") and
            ((.evidence_path | length) > 0)
          )
        ' "$MANIFEST" >/dev/null 2>&1; then
          reason="external-agent manifest lacks target, transition, fail-closed flag, or evidence"
        else
          status="pass"
        fi
        ;;
      *)
        reason="cannot infer a supported external manifest kind"
        ;;
    esac
  fi
fi

if [[ "$JSON" -eq 1 ]]; then
  jq -n \
    --arg manifest "$MANIFEST" \
    --arg kind "$resolved_kind" \
    --arg status "$status" \
    --arg reason "$reason" \
    '{schema:"kg.review_audit.v1", manifest:$manifest, kind:$kind,
      status:$status, reason:(if $reason == "" then null else $reason end)}'
else
  if [[ "$status" == "pass" ]]; then
    echo "[review][ok] $resolved_kind manifest verified: $MANIFEST"
  else
    echo "[review][block] ${reason:-manifest failed closed}"
  fi
fi

if [[ "$status" == "pass" ]]; then
  exit "$EXIT_OK"
fi
exit "$EXIT_BLOCK"
