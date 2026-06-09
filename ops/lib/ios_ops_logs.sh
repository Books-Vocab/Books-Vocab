#!/usr/bin/env bash
# ios_ops_logs.sh — sourceable runtime log commands for ios_ops.sh.

cmd_logs() {
  local since="5m" predicate="$DEFAULT_LOG_PREDICATE" limit=200 limit_num json=0 follow=0 limit_explicit=0 simulator=0 device="booted" debug=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --since) since="${2:?--since needs value}"; shift 2 ;;
      --predicate) predicate="${2:?--predicate needs value}"; shift 2 ;;
      --limit) limit="${2:?--limit needs value}"; limit_explicit=1; shift 2 ;;
      --simulator) simulator=1; shift ;;
      --device) device="${2:?--device needs value}"; shift 2 ;;
      --debug) debug=1; shift ;;
      --follow|-f) follow=1; shift ;;
      --json) json=1; shift ;;
      -h|--help) echo "Usage: ./ops/ios_ops.sh logs [--since 5m | --follow] [--predicate <predicate>] [--limit 200] [--simulator [--device booted|<udid>]] [--debug] [--json]"; return 0 ;;
      *) echo "✗ unknown logs option: $1" >&2; return 1 ;;
    esac
  done
  if [[ -z "$limit" || "$limit" == *[!0-9]* ]]; then
    echo "✗ --limit must be a non-negative integer" >&2
    return 1
  fi
  limit_num="$((10#$limit))"
  if (( follow )); then
    # live stream: --limit is a stop-after-N gate (0 = unbounded). --since is N/A.
    local follow_limit=0
    (( limit_explicit )) && follow_limit="$limit_num"
    echo "[ios][logs] follow predicate=$predicate limit=${follow_limit}" >&2
    if (( json )); then
      cmd_logs_follow_json "$predicate" "$follow_limit"
    else
      cmd_logs_follow_text "$predicate" "$follow_limit"
    fi
    return
  fi
  if (( json )); then
    cmd_logs_json "$since" "$predicate" "$limit_num" "$simulator" "$device" "$debug"
    return
  fi
  echo "[ios][logs] since=$since predicate=$predicate simulator=$simulator device=$device debug=$debug" >&2
  cmd_logs_text "$since" "$predicate" "$limit_num" "$simulator" "$device" "$debug"
}

run_log_stream_compact() {
  local predicate="$1"
  if [[ "${KG_IOS_OPS_LOG_FAIL_FIXTURE:-}" == "1" ]]; then
    echo "fixture log failure" >&2
    return 42
  fi
  if [[ "${KG_IOS_OPS_LOG_FIXTURE:-}" == "1" ]]; then
    cat <<'LOG'
2026-06-07 12:00:00.000000+0800 BooksAndVocab[123:456] [com.Max0228.BooksBrowser:sync] sync completed
2026-06-07 12:00:01.000000+0800 BooksAndVocab[123:456] RBSServiceErrorDomain ProcessAssertion noise
2026-06-07 12:00:02.000000+0800 BooksAndVocab[123:456] [com.Max0228.BooksBrowser:reader] reader opened
LOG
    return 0
  fi
  if [[ "${KG_IOS_OPS_LOG_STREAM_FIXTURE:-}" == "1" ]]; then
    # unbounded producer: exercises the real SIGPIPE(141) path when a downstream
    # `head -n` closes the pipe after the limit is reached.
    while :; do
      printf '%s\n' '2026-06-07 12:00:00.000000+0800 BooksAndVocab[123:456] [com.Max0228.BooksBrowser:sync] sync completed'
    done
    return 0
  fi
  /usr/bin/log stream --style compact --predicate "$predicate"
}

run_log_stream_ndjson() {
  local predicate="$1"
  if [[ "${KG_IOS_OPS_LOG_FAIL_FIXTURE:-}" == "1" ]]; then
    echo "fixture log failure" >&2
    return 42
  fi
  if [[ "${KG_IOS_OPS_LOG_FIXTURE:-}" == "1" ]]; then
    cat <<'NDJSON'
{"timestamp":"2026-06-07 12:00:00.000000+0800","eventType":"logEvent","processID":123,"subsystem":"com.Max0228.BooksBrowser","category":"sync","eventMessage":"sync completed","senderImagePath":"/tmp/BooksAndVocab"}
{"timestamp":"2026-06-07 12:00:01.000000+0800","eventType":"logEvent","processID":123,"subsystem":"","category":"","eventMessage":"RBSServiceErrorDomain ProcessAssertion noise","senderImagePath":"/System/Library/Frameworks/RunningBoardServices.framework/RunningBoardServices"}
{"timestamp":"2026-06-07 12:00:02.000000+0800","eventType":"activityCreateEvent","processID":123,"subsystem":"com.Max0228.BooksBrowser","category":"reader","eventMessage":"reader opened","senderImagePath":"/tmp/BooksAndVocab"}
NDJSON
    return 0
  fi
  if [[ "${KG_IOS_OPS_LOG_STREAM_FIXTURE:-}" == "1" ]]; then
    while :; do
      printf '%s\n' '{"timestamp":"2026-06-07 12:00:00.000000+0800","eventType":"logEvent","processID":123,"subsystem":"com.Max0228.BooksBrowser","category":"sync","eventMessage":"sync completed","senderImagePath":"/tmp/BooksAndVocab"}'
    done
    return 0
  fi
  /usr/bin/log stream --style ndjson --predicate "$predicate"
}

# Stream live compact logs, filtering framework noise. limit>0 stops after N lines.
# Runs in a subshell so `set +o pipefail` stays local (this is a sourceable lib).
# Subshell exit status carries PIPESTATUS[0] (the producer's rc).
cmd_logs_follow_text() {
  local predicate="$1" limit="$2" rc=0
  (
    set +o pipefail
    if (( limit > 0 )); then
      run_log_stream_compact "$predicate" | grep --line-buffered -vE "$LOG_NOISE_REGEX" | head -n "$limit"
    else
      run_log_stream_compact "$predicate" | grep --line-buffered -vE "$LOG_NOISE_REGEX"
    fi
    exit "${PIPESTATUS[0]}"
  ) || rc=$?
  # Propagate real `log stream` failures; SIGPIPE (head closed) is benign.
  # rc is PIPESTATUS[0] (producer); grep no-match lives in PIPESTATUS[1] and is dropped.
  if (( rc != 0 && rc != 141 )); then
    return "$rc"
  fi
  return 0
}

# Stream live ndjson logs as one filtered JSON object per line. limit>0 stops after N.
cmd_logs_follow_json() {
  local predicate="$1" limit="$2" rc=0
  (
    set +o pipefail
    run_log_stream_ndjson "$predicate" \
      | jq -c --unbuffered --arg schema "kg.ios.log-stream.v1" --arg noise "$LOG_NOISE_REGEX" '
          def message: (.eventMessage // .formatString // "");
          select((message | test($noise)) | not)
          | {
              schema:$schema,
              timestamp:(.timestamp // null),
              eventType:(.eventType // null),
              processID:(.processID // null),
              subsystem:(.subsystem // null),
              category:(.category // null),
              message:message,
              sender:(.senderImagePath // null)
            }
        ' \
      | { if (( limit > 0 )); then head -n "$limit"; else cat; fi; }
    exit "${PIPESTATUS[0]}"
  ) || rc=$?
  if (( rc != 0 && rc != 141 )); then
    return "$rc"
  fi
  return 0
}

run_log_show_compact() {
  local since="$1" predicate="$2" simulator="${3:-0}" device="${4:-booted}" debug="${5:-0}"
  if [[ "${KG_IOS_OPS_LOG_FAIL_FIXTURE:-}" == "1" ]]; then
    echo "fixture log failure" >&2
    return 42
  fi
  if [[ "${KG_IOS_OPS_LOG_FIXTURE:-}" == "1" ]]; then
    cat <<'LOG'
2026-06-07 12:00:00.000000+0800 BooksAndVocab[123:456] [com.Max0228.BooksBrowser:sync] sync completed
2026-06-07 12:00:01.000000+0800 BooksAndVocab[123:456] RBSServiceErrorDomain ProcessAssertion noise
2026-06-07 12:00:02.000000+0800 BooksAndVocab[123:456] [com.Max0228.BooksBrowser:reader] reader opened
LOG
    return 0
  fi
  local args=(log show --style compact --last "$since" --predicate "$predicate")
  if (( debug )); then
    args=(log show --debug --info --style compact --last "$since" --predicate "$predicate")
  fi
  if (( simulator )); then
    xcrun simctl spawn "$device" "${args[@]}"
  else
    /usr/bin/"${args[@]}"
  fi
}

cmd_logs_text() {
  local since="$1" predicate="$2" limit="$3" simulator="${4:-0}" device="${5:-booted}" debug="${6:-0}" tmp err rc
  tmp="$(mktemp)"
  err="$(mktemp)"
  if run_log_show_compact "$since" "$predicate" "$simulator" "$device" "$debug" >"$tmp" 2>"$err"; then
    rc=0
  else
    rc=$?
  fi
  if (( rc != 0 )); then
    cat "$err" >&2
    rm -f "$tmp" "$err"
    return "$rc"
  fi
  rm -f "$err"
  grep -vE "$LOG_NOISE_REGEX" "$tmp" | head -n "$limit" || true
  rm -f "$tmp"
}

run_log_show_ndjson() {
  local since="$1" predicate="$2" simulator="${3:-0}" device="${4:-booted}" debug="${5:-0}"
  if [[ "${KG_IOS_OPS_LOG_FAIL_FIXTURE:-}" == "1" ]]; then
    echo "fixture log failure" >&2
    return 42
  fi
  if [[ "${KG_IOS_OPS_LOG_FIXTURE:-}" == "1" ]]; then
    cat <<'NDJSON'
{"timestamp":"2026-06-07 12:00:00.000000+0800","eventType":"logEvent","processID":123,"subsystem":"com.Max0228.BooksBrowser","category":"sync","eventMessage":"sync completed","senderImagePath":"/tmp/BooksAndVocab"}
{"timestamp":"2026-06-07 12:00:01.000000+0800","eventType":"logEvent","processID":123,"subsystem":"","category":"","eventMessage":"RBSServiceErrorDomain ProcessAssertion noise","senderImagePath":"/System/Library/Frameworks/RunningBoardServices.framework/RunningBoardServices"}
{"timestamp":"2026-06-07 12:00:02.000000+0800","eventType":"activityCreateEvent","processID":123,"subsystem":"com.Max0228.BooksBrowser","category":"reader","eventMessage":"reader opened","senderImagePath":"/tmp/BooksAndVocab"}
NDJSON
    return 0
  fi
  local args=(log show --style ndjson --last "$since" --predicate "$predicate")
  if (( debug )); then
    args=(log show --debug --info --style ndjson --last "$since" --predicate "$predicate")
  fi
  if (( simulator )); then
    xcrun simctl spawn "$device" "${args[@]}"
  else
    /usr/bin/"${args[@]}"
  fi
}

cmd_logs_json() {
  local since="$1" predicate="$2" limit="$3" simulator="${4:-0}" device="${5:-booted}" debug="${6:-0}" generated_at tmp err rc
  generated_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  tmp="$(mktemp)"
  err="$(mktemp)"
  if run_log_show_ndjson "$since" "$predicate" "$simulator" "$device" "$debug" >"$tmp" 2>"$err"; then
    rc=0
  else
    rc=$?
  fi
  if (( rc != 0 )); then
    cat "$err" >&2
    rm -f "$tmp" "$err"
    return "$rc"
  fi
  rm -f "$err"
  jq -s \
    --arg schema "kg.ios.logs.v1" \
    --arg generatedAt "$generated_at" \
    --arg since "$since" \
    --arg predicate "$predicate" \
    --arg source "$(logs_show_source "$simulator" "$device" "$debug" "ndjson")" \
    --arg noise "$LOG_NOISE_REGEX" \
    --argjson limit "$limit" \
    '
      def message: (.eventMessage // .formatString // "");
      . as $raw
      | ($raw | map(select((message | test($noise)) | not))) as $filtered
      | {
          schema:$schema,
          generatedAt:$generatedAt,
          since:$since,
          predicate:$predicate,
          limit:$limit,
          source:$source,
          summary:{
            rawCount:($raw | length),
            filteredCount:(($raw | length) - ($filtered | length)),
            emittedCount:($filtered[0:$limit] | length),
            byEventType:(
              reduce $filtered[] as $event
                ({}; ($event.eventType // "unknown") as $key | .[$key] = ((.[$key] // 0) + 1))
            )
          },
          entries:(
            $filtered[0:$limit]
            | map({
                timestamp:(.timestamp // null),
                eventType:(.eventType // null),
                processID:(.processID // null),
                subsystem:(.subsystem // null),
                category:(.category // null),
                message:message,
                sender:(.senderImagePath // null)
              })
          )
        }
    ' "$tmp"
  local rc=$?
  rm -f "$tmp"
  return "$rc"
}

logs_show_source() {
  local simulator="$1" device="$2" debug="$3" style="$4" args="log show"
  if (( debug )); then
    args="$args --debug --info"
  fi
  args="$args --style $style"
  if (( simulator )); then
    printf 'xcrun simctl spawn %s %s' "$device" "$args"
  else
    printf '/usr/bin/%s' "$args"
  fi
}
