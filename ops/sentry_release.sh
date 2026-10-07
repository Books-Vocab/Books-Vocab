#!/usr/bin/env bash
# sentry_release.sh — best-effort Sentry release integration for deploys and iOS releases.
#
# Usage:
#   ops/sentry_release.sh check [--json]
#       Read-only: which config keys are present (never their values), API URL
#       validity, pinned sentry-cli version, uploader availability.
#   ops/sentry_release.sh record-backend --sha <40-hex> [--environment production] [--name <who>]
#       Create release kg-backend@<sha> for SENTRY_PROJECT_BACKEND, finalize it
#       (dateReleased) and record a deploy for the environment.
#   ops/sentry_release.sh upload-dsyms <dir>
#       Upload the .dSYM bundles under <dir> (an archive's dSYMs/) to
#       SENTRY_PROJECT_IOS with the pinned sentry-cli.
#
# Exit: 0 done, 3 SKIP (config missing / nothing to upload), 1 failed.
# Callers on a release or deploy path MUST treat every non-zero exit as
# non-fatal: this tool never blocks a deploy or a release.
#
# Output: progress and SKIP/failure lines go to stderr only; stdout carries
# nothing except `check --json`. The auth token never reaches argv or output:
# curl reads it from a stdin config, sentry-cli from SENTRY_AUTH_TOKEN.
#
# Config: process env wins over ~/.secrets/sentry.env (override the path with
# SENTRY_ENV_FILE). Keys: SENTRY_AUTH_TOKEN (scope project:releases),
# SENTRY_ORG, SENTRY_PROJECT_BACKEND, SENTRY_PROJECT_IOS, SENTRY_API_URL
# (default https://sentry.io/api/0). Same contract as the read tool
# ops/sentry_api.py; the file is parsed as KEY=VALUE lines, never sourced.
#
# Time bounds: every HTTP call has --connect-timeout/--max-time
# (KG_SENTRY_HTTP_CONNECT_TIMEOUT, default 5; KG_SENTRY_HTTP_TIMEOUT, default
# 10) and the first failure stops the sequence; the dSYM upload is killed after
# KG_SENTRY_DSYM_TIMEOUT seconds (default 300).
#
# Seams (tests): KG_SENTRY_CURL (curl binary), KG_SENTRY_CLI (uploader binary,
# replaces `uvx --from sentry-cli==<pin> sentry-cli`).
#
# Bash 3.2 compatible: the felix reconciler runs under launchd's /bin/bash.

set -uo pipefail

# Pinned uploader. Installed on demand by uvx from PyPI's official sentry-cli
# wheels (published by Sentry), so every machine runs the same binary. Bump
# deliberately; `check` reports it.
SENTRY_CLI_VERSION="3.8.0"
DEFAULT_API_URL="https://sentry.io/api/0"
ENV_FILE="${SENTRY_ENV_FILE:-$HOME/.secrets/sentry.env}"
CURL="${KG_SENTRY_CURL:-curl}"
CONNECT_TIMEOUT="${KG_SENTRY_HTTP_CONNECT_TIMEOUT:-5}"
MAX_TIME="${KG_SENTRY_HTTP_TIMEOUT:-10}"
DSYM_TIMEOUT="${KG_SENTRY_DSYM_TIMEOUT:-300}"
CONFIG_KEYS="SENTRY_AUTH_TOKEN SENTRY_ORG SENTRY_PROJECT_BACKEND SENTRY_PROJECT_IOS SENTRY_API_URL"

usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "$0"; }
say()   { printf '[sentry-release] %s\n' "$*" >&2; }
skip()  { printf '[sentry-release] SKIP: %s\n' "$*" >&2; exit 3; }
die()   { printf '[sentry-release] FAILED: %s\n' "$*" >&2; exit 1; }

# The in-flight response temp file (see `request`) is removed on every exit
# path, including a TERM/INT/HUP that lands while curl is running.
REQUEST_TMP=""
cleanup() { [[ -z "$REQUEST_TMP" ]] || rm -f "$REQUEST_TMP"; }
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

# Secrets must not reach a `bash -x` trace. file_value and cfg only ever run
# inside $( ) subshells, so their `set +x` cannot leak out; code that holds the
# token in the main shell goes through `quiet`, which restores the caller's
# xtrace state afterwards.
quiet() {
  local xt=0 rc
  case $- in *x*) xt=1 ;; esac
  set +x
  "$@"; rc=$?
  (( xt )) && set -x
  return $rc
}

# Dotenv-style value, identical to ops/sentry_api.py `_env_value` (the two
# parsers read one file; ops/tests/test_sentry_release.sh runs one input table
# through both): a quoted value ends at its first closing quote and keeps any
# `#` inside; an unquoted one (an unterminated quote counts as unquoted) loses
# everything from the first `#` that follows whitespace. Prints the value.
env_value() {
  set +x
  local value rest quote
  value="$(trim "$1")"
  quote="${value:0:1}"
  if [[ "$quote" == \" || "$quote" == \' ]]; then
    rest="${value:1}"
    if [[ "$rest" == *"$quote"* ]]; then
      printf '%s' "${rest%%"$quote"*}"
      return 0
    fi
  fi
  trim "${value%%[[:space:]]#*}"
}

# Last `KEY=VALUE` (optionally `export KEY=VALUE`) for $1 in the file, parsed
# like ops/sentry_api.py `_read_env_file`: only a literal `export ` prefix, `#`
# lines skipped, split at the first `=`.
file_value() {
  set +x
  local key="$1" line name found=""
  [[ -r "$ENV_FILE" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="$(trim "$line")"
    [[ -n "$line" && "$line" != '#'* ]] || continue
    case "$line" in 'export '*) line="$(trim "${line#export }")" ;; esac
    [[ "$line" == *=* ]] || continue
    name="$(trim "${line%%=*}")"
    [[ "$name" == "$key" ]] || continue
    found="$(env_value "${line#*=}")"
  done < "$ENV_FILE"
  printf '%s' "$found"
}

cfg() {
  set +x
  local key="$1" value="${!1:-}"
  [[ -n "$value" ]] || value="$(file_value "$key")"
  printf '%s' "$value"
}

# Normalised .../api/0 base; non-zero for anything that is not https (or
# loopback http), or that carries userinfo, query or fragment.
api_base() {
  local raw scheme rest host hostname path=""
  raw="$(cfg SENTRY_API_URL)"
  [[ -n "$raw" ]] || raw="$DEFAULT_API_URL"
  [[ "$raw" == *://* ]] || return 1
  case "$raw" in *[?#@[:space:]]*) return 1 ;; esac
  scheme="${raw%%://*}"
  rest="${raw#*://}"
  host="${rest%%/*}"
  [[ "$rest" == */* ]] && path="/${rest#*/}"
  [[ -n "$host" ]] || return 1
  case "$host" in
    \[*) hostname="${host%%]*}]" ;;
    *) hostname="${host%%:*}" ;;
  esac
  case "$scheme" in
    https) ;;
    http) case "$hostname" in localhost|127.0.0.1|\[::1\]) ;; *) return 1 ;; esac ;;
    *) return 1 ;;
  esac
  while [[ "$path" == */ ]]; do path="${path%/}"; done
  case "$path" in
    */api/0) ;;
    */api) path="$path/0" ;;
    *) path="$path/api/0" ;;
  esac
  printf '%s://%s%s' "$scheme" "$host" "$path"
}

valid_slug()  { local re='^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$'; [[ "$1" =~ $re ]]; }
valid_token() { local re='^[A-Za-z0-9._~+/=-]+$'; [[ ${#1} -ge 8 && ${#1} -le 512 && "$1" =~ $re ]]; }  # macOS RE_DUP_MAX=255
valid_label() { local re='^[A-Za-z0-9._@:-]{1,64}$'; [[ "$1" =~ $re ]]; }

# Resolve and validate the shared config, or SKIP naming exactly what is wrong.
# Sets TOKEN, ORG, PROJECT, BASE. $1 = which project key the subcommand needs.
load_config() {
  local project_key="$1" missing=() key
  TOKEN="$(cfg SENTRY_AUTH_TOKEN)"
  ORG="$(cfg SENTRY_ORG)"
  PROJECT="$(cfg "$project_key")"
  for key in SENTRY_AUTH_TOKEN SENTRY_ORG "$project_key"; do
    [[ -n "$(cfg "$key")" ]] || missing+=("$key")
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    skip "missing ${missing[*]} (env or $ENV_FILE); see docs/sop/deploy.md §Sentry"
  fi
  valid_token "$TOKEN" || skip "SENTRY_AUTH_TOKEN has unexpected characters (value not shown)"
  valid_slug "$ORG" || skip "SENTRY_ORG is not a valid slug"
  valid_slug "$PROJECT" || skip "$project_key is not a valid slug"
  BASE="$(api_base)" || skip "SENTRY_API_URL must be https (or loopback http) without userinfo/query"
}

# request <label> <method> <url> <json body> <accepted codes...>
request() {
  local label="$1" method="$2" url="$3" body="$4"; shift 4
  local tmp code rc=0 detail accepted xt=0
  tmp="$(mktemp "${TMPDIR:-/tmp}/kg_sentry_release.XXXXXX")" || return 1
  REQUEST_TMP="$tmp"
  case $- in *x*) xt=1 ;; esac
  set +x   # the token is in this pipeline; keep it out of any bash -x trace
  code="$(printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" \
    | "$CURL" -K - -sS -o "$tmp" -w '%{http_code}' \
        --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" \
        -X "$method" -H 'Content-Type: application/json' \
        --data-binary "$body" "$url" 2>/dev/null)" || rc=$?
  (( xt )) && set -x
  detail="$(head -c 300 "$tmp" 2>/dev/null | tr -d '\r\n')"
  rm -f "$tmp"
  REQUEST_TMP=""
  if (( rc != 0 )); then
    say "$label: curl exit $rc (network or ${MAX_TIME}s time bound) on $method $url"
    return 1
  fi
  for accepted in "$@"; do
    [[ "$code" == "$accepted" ]] && return 0
  done
  say "$label: HTTP $code on $method $url: ${detail:-<empty body>}"
  return 1
}

cmd_record_backend() {
  local sha="" environment="production" name="" sha_re='^[0-9a-f]{40}$'
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --sha) sha="${2:-}"; shift 2 ;;
      --environment) environment="${2:-}"; shift 2 ;;
      --name) name="${2:-}"; shift 2 ;;
      *) die "record-backend: unknown argument $1" ;;
    esac
  done
  [[ "$sha" =~ $sha_re ]] \
    || skip "release name is kg-backend@<full 40-char sha>; got '${sha}' (deploy must write the full sha)"
  valid_label "$environment" || skip "invalid --environment"
  [[ -n "$name" ]] || name="$(hostname -s 2>/dev/null || echo deploy)"
  valid_label "$name" || name="deploy"
  quiet load_config SENTRY_PROJECT_BACKEND

  local version="kg-backend@$sha" encoded="kg-backend%40$sha" now releases
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  releases="$BASE/organizations/$ORG/releases"
  say "recording $version → $environment (org=$ORG project=$PROJECT)"
  request "create release" POST "$releases/" \
    "{\"version\":\"$version\",\"ref\":\"$sha\",\"projects\":[\"$PROJECT\"],\"dateReleased\":\"$now\"}" \
    200 201 208 || die "release $version not created"
  # A release can already exist unfinalized: Sentry creates one implicitly when
  # the first event tagged with it arrives, which can precede this call.
  request "finalize release" PUT "$releases/$encoded/" "{\"dateReleased\":\"$now\"}" \
    200 || die "release $version not finalized"
  request "record deploy" POST "$releases/$encoded/deploys/" \
    "{\"environment\":\"$environment\",\"name\":\"$name\",\"dateFinished\":\"$now\"}" \
    200 201 || die "deploy of $version to $environment not recorded"
  say "ok: $version finalized, deploy recorded for $environment"
}

# bounded <seconds> <cmd...>: run in its own process group, kill the whole
# group (uvx and the sentry-cli it spawns) once the bound is exceeded.
bounded() {
  local secs="$1"; shift
  local pid ticks=0 limit=$(( secs * 5 ))
  set -m
  "$@" </dev/null &
  pid=$!
  set +m
  while kill -0 "$pid" 2>/dev/null; do
    if (( ticks >= limit )); then
      say "uploader exceeded the ${secs}s time bound; terminating process group $pid"
      # One stderr-silenced group: the shell reports a signalled job
      # ("Terminated: 15") wherever it first reaps it, not only at `wait`.
      {
        kill -TERM -- "-$pid" || kill -TERM "$pid"
        sleep 1
        kill -KILL -- "-$pid" || true
        wait "$pid"
      } 2>/dev/null
      return 124
    fi
    sleep 0.2
    ticks=$(( ticks + 1 ))
  done
  { wait "$pid"; } 2>/dev/null
}

cmd_upload_dsyms() {
  local dir="${1:-}" rc=0 cli=()
  [[ -n "$dir" && -d "$dir" ]] || skip "dSYM directory not found: ${dir:-<none>}"
  find "$dir" -maxdepth 2 -type d -name '*.dSYM' 2>/dev/null | grep -q . \
    || skip "no .dSYM bundles under $dir (check DEBUG_INFORMATION_FORMAT=dwarf-with-dsym)"
  quiet load_config SENTRY_PROJECT_IOS
  if [[ -n "${KG_SENTRY_CLI:-}" ]]; then
    cli=("$KG_SENTRY_CLI")
  elif command -v uvx >/dev/null 2>&1; then
    cli=(uvx --from "sentry-cli==$SENTRY_CLI_VERSION" sentry-cli)
  else
    skip "uvx not on PATH (needed for the pinned sentry-cli==$SENTRY_CLI_VERSION)"
  fi
  say "uploading dSYMs from $dir → $ORG/$PROJECT (sentry-cli $SENTRY_CLI_VERSION, bound ${DSYM_TIMEOUT}s)"
  (
    set +x
    export SENTRY_AUTH_TOKEN="$TOKEN" SENTRY_URL="${BASE%/api/0}"
    bounded "$DSYM_TIMEOUT" "${cli[@]}" debug-files upload \
      --org "$ORG" --project "$PROJECT" --type dsym "$dir" >&2
  ) || rc=$?
  case "$rc" in
    0) say "ok: dSYMs uploaded" ;;
    124) die "dSYM upload killed by the ${DSYM_TIMEOUT}s time bound" ;;
    *) die "dSYM upload failed (uploader exit $rc)" ;;
  esac
}

cmd_check() {
  local json=0 key present file_state="missing" api="valid" uploader="missing" sep=""
  [[ "${1:-}" == "--json" ]] && json=1
  [[ -r "$ENV_FILE" ]] && file_state="present"
  api_base >/dev/null || api="invalid"
  if [[ -n "${KG_SENTRY_CLI:-}" ]]; then uploader="override"
  elif command -v uvx >/dev/null 2>&1; then uploader="uvx"; fi
  if (( json == 1 )); then
    printf '{"schema":"kg.sentry.release.check.v1","env_file":"%s","keys":{' "$file_state"
    for key in $CONFIG_KEYS; do
      present=false; [[ -n "$(cfg "$key")" ]] && present=true
      printf '%s"%s":%s' "$sep" "$key" "$present"; sep=","
    done
    printf '},"api_url":"%s","uploader":"%s","sentry_cli":"%s"}\n' "$api" "$uploader" "$SENTRY_CLI_VERSION"
    return 0
  fi
  printf 'env file: %s (%s)\n' "$ENV_FILE" "$file_state"
  for key in $CONFIG_KEYS; do
    present=missing; [[ -n "$(cfg "$key")" ]] && present=set
    printf '%-24s %s\n' "$key" "$present"
  done
  printf 'api url: %s\nuploader: %s (sentry-cli %s)\n' "$api" "$uploader" "$SENTRY_CLI_VERSION"
}

main() {
  case "${1:-}" in
    check) shift; quiet cmd_check "$@" ;;
    record-backend) shift; cmd_record_backend "$@" ;;
    upload-dsyms) shift; cmd_upload_dsyms "$@" ;;
    -h|--help|help) usage ;;
    *) usage >&2; exit 2 ;;
  esac
}

# Sourced (by ops/tests/test_sentry_release.sh) only to reach the parsers; run
# normally the script dispatches as before.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
