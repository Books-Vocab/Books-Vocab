#!/usr/bin/env bash
# Validate the standby launchd S3 backup without mutating host or bucket state.
#
# Production defaults read com.kg.backup and ~/Library/Logs/kg_backup.log.
# Tests can use --fixture/--log, --now, and --job-state so no launchctl or
# production data is touched.
set -euo pipefail

MAX_AGE_SECONDS="${KG_BACKUP_STATUS_MAX_AGE_SECONDS:-129600}"
LOG_PATH="${KG_BACKUP_STATUS_LOG:-${KG_BACKUP_LOG:-$HOME/Library/Logs/kg_backup.log}}"
NOW_EPOCH="${KG_BACKUP_STATUS_NOW_EPOCH:-}"
JOB_STATE="${KG_BACKUP_STATUS_JOB_STATE:-}"

usage() {
  cat <<'USAGE'
Usage: backup_status.sh [options]

Read-only scheduled backup health check.

Options:
  --log PATH          Read this backup log instead of the production default.
  --fixture PATH      Alias for --log, for offline tests.
  --now EPOCH         Use this UTC epoch instead of the current clock.
  --job-state STATE   Use loaded|missing instead of invoking launchctl.
  --help              Show this help.

Environment seams:
  KG_BACKUP_STATUS_LOG, KG_BACKUP_LOG
  KG_BACKUP_STATUS_NOW_EPOCH, KG_BACKUP_STATUS_JOB_STATE
  KG_BACKUP_STATUS_MAX_AGE_SECONDS (default: 129600)
USAGE
}

fail() {
  echo "✗ backup status: $*" >&2
  exit 1
}

is_uint() {
  [[ "$1" =~ ^[0-9]+$ ]]
}

parse_timestamp() {
  local stamp="$1" parsed roundtrip

  if parsed="$(date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "$stamp" '+%s' 2>/dev/null)"; then
    roundtrip="$(date -u -r "$parsed" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null)" || return 1
  elif parsed="$(date -u -d "$stamp" '+%s' 2>/dev/null)"; then
    roundtrip="$(date -u -d "@$parsed" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null)" || return 1
  else
    return 1
  fi

  [[ "$roundtrip" == "$stamp" ]] || return 1
  printf '%s\n' "$parsed"
}

parse_args() {
  while (($#)); do
    case "$1" in
      --log|--fixture)
        (($# >= 2)) || fail "$1 requires PATH"
        LOG_PATH="$2"
        shift 2
        ;;
      --now)
        (($# >= 2)) || fail "--now requires EPOCH"
        NOW_EPOCH="$2"
        shift 2
        ;;
      --job-state)
        (($# >= 2)) || fail "--job-state requires loaded|missing"
        JOB_STATE="$2"
        shift 2
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        fail "unknown option: $1"
        ;;
    esac
  done
}

check_job() {
  case "$JOB_STATE" in
    loaded)
      ;;
    missing)
      fail "launchd job com.kg.backup is not loaded"
      ;;
    "")
      command -v launchctl >/dev/null 2>&1 || fail "launchctl is unavailable"
      launchctl list 2>/dev/null \
        | grep -Eq '(^|[[:space:]])com\.kg\.backup([[:space:]]|$)' \
        || fail "launchd job com.kg.backup is not loaded"
      ;;
    *)
      fail "invalid job state: $JOB_STATE"
      ;;
  esac
}

parse_args "$@"

is_uint "$MAX_AGE_SECONDS" || fail "invalid max age: $MAX_AGE_SECONDS"
(( MAX_AGE_SECONDS > 0 )) || fail "max age must be positive"

if [[ -z "$NOW_EPOCH" ]]; then
  NOW_EPOCH="$(date -u '+%s')"
fi
is_uint "$NOW_EPOCH" || fail "invalid now epoch: $NOW_EPOCH"

check_job
[[ -f "$LOG_PATH" ]] || fail "backup log is missing: $LOG_PATH"
[[ -r "$LOG_PATH" ]] || fail "backup log is not readable: $LOG_PATH"

last_line="$(tail -n 1 "$LOG_PATH" 2>/dev/null)" || fail "cannot read backup log: $LOG_PATH"
[[ -n "$last_line" ]] || fail "backup log has no stable record: $LOG_PATH"

record_re='^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)[[:space:]]exit=([0-9]+)[[:space:]]bytes=([0-9]+)[[:space:]]sha256=([0-9A-Fa-f]{64})[[:space:]]key=data/([0-9]{4}-[0-9]{2}-[0-9]{2})\.tar\.gz$'
[[ "$last_line" =~ $record_re ]] || fail "last backup log record has an invalid format"

timestamp="${BASH_REMATCH[1]}"
exit_code="${BASH_REMATCH[2]}"
bytes="${BASH_REMATCH[3]}"
sha256="${BASH_REMATCH[4]}"
key_date="${BASH_REMATCH[5]}"
timestamp_epoch="$(parse_timestamp "$timestamp")" || fail "timestamp is not parseable: $timestamp"

(( exit_code == 0 )) || fail "last backup exited with rc=$exit_code"
(( bytes > 0 )) || fail "last backup record has non-positive bytes=$bytes"
[[ "${timestamp:0:10}" == "$key_date" ]] || fail "backup key date $key_date does not match timestamp ${timestamp:0:10}"

age_seconds=$(( NOW_EPOCH - timestamp_epoch ))
(( age_seconds >= 0 )) || fail "last backup timestamp is in the future: $timestamp"
(( age_seconds <= MAX_AGE_SECONDS )) \
  || fail "last backup is stale: age=${age_seconds}s max=${MAX_AGE_SECONDS}s"

printf '✓ backup status healthy: job=com.kg.backup timestamp=%s exit=%s bytes=%s sha256=%s key=data/%s.tar.gz age=%ss\n' \
  "$timestamp" "$exit_code" "$bytes" "$sha256" "$key_date" "$age_seconds"
