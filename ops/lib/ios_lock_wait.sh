#!/usr/bin/env bash
# Shared visible-progress contract for the iOS shlock spin-waits.

# Typed exit used when a caller could not acquire a shared machine resource.
# This is deliberately distinct from a test/build failure: callers can report
# infrastructure-unavailable without charging the branch with a code verdict.
KG_IOS_EXIT_INFRA_UNAVAILABLE=75

# The spin loops poll every 3s. A 15s cadence stays safely inside the 20s
# visibility ceiling even if one poll is delayed slightly.
KG_IOS_LOCK_HEARTBEAT_SECONDS=15

# kg_ios_lock_wait_heartbeat <prefix> <kind> <elapsed-seconds> <previous-seconds> <holder-pid>
# Emits exactly once when the caller crosses each heartbeat boundary. The
# waiting process is the current shell; holder liveness is observational only.
kg_ios_lock_wait_heartbeat() {
  local prefix="$1" kind="$2" elapsed="$3" previous="$4" holder_pid="${5:-}"
  local holder_display="${holder_pid:-unknown}" holder_alive="unknown"

  (( elapsed / KG_IOS_LOCK_HEARTBEAT_SECONDS > previous / KG_IOS_LOCK_HEARTBEAT_SECONDS )) || return 0

  case "$holder_pid" in
    ''|*[!0-9]*) ;;
    *)
      if kill -0 "$holder_pid" 2>/dev/null; then
        holder_alive=true
      else
        holder_alive=false
      fi
      ;;
  esac

  printf '%s phase=lock-wait kind=%s elapsed=%ss pid=%s alive=true holderPid=%s holderAlive=%s\n' \
    "$prefix" "$kind" "$elapsed" "$$" "$holder_display" "$holder_alive"
}

# kg_ios_lock_timeout_die <prefix> <kind> <selector> <timeout-seconds>
# Emit a machine-readable, human-debuggable lock timeout and terminate the
# caller with the typed infrastructure-unavailable status. The holder command
# is best-effort: a stale/dead PID is evidence worth naming, not a reason to
# make the timeout path itself fail while collecting diagnostics.
kg_ios_lock_timeout_die() {
  local prefix="${1:-[ios]}" kind="${2:-lock}" selector="${3:-unknown}"
  local timeout="${4:-unknown}" holder_pid="${KG_IOS_LOCK_HOLDER_PID:-unknown}"
  local waited="${KG_IOS_LOCK_WAIT_SECONDS:-0}" holder_cmd="unknown"

  case "$holder_pid" in
    ''|unknown|*[!0-9]*) holder_pid="unknown" ;;
    *)
      holder_cmd="$(ps -o command= -p "$holder_pid" 2>/dev/null \
        | tr '\n' ' ' | sed 's/[[:space:]]*$//' || true)"
      [[ -n "$holder_cmd" ]] || holder_cmd="unknown"
      ;;
  esac

  printf '%s error: timed out after %ss waiting for %s lock selector="%s" holderPid=%s holderCmd=%s waitedSeconds=%s infrastructure=unavailable rc=%s\n' \
    "$prefix" "$timeout" "$kind" "$selector" "$holder_pid" "$holder_cmd" "$waited" "$KG_IOS_EXIT_INFRA_UNAVAILABLE" >&2
  exit "$KG_IOS_EXIT_INFRA_UNAVAILABLE"
}

# kg_ios_wait_for_shlock <prefix> <kind> <lock-file> <owner-pid> <timeout-seconds> <poll-seconds> [timeout-mode]
# On success, leaves the lock owned by owner-pid and exports observational
# result fields in KG_IOS_LOCK_WAIT_SECONDS / KG_IOS_LOCK_HOLDER_PID. On timeout
# it returns 1; the caller owns its command-specific error and exit behavior.
kg_ios_wait_for_shlock() {
  local prefix="$1" kind="$2" lock_file="$3" owner_pid="$4" timeout="$5" poll="$6"
  local timeout_mode="${7:-pre-sleep}"
  local waited=0 previous_waited holder_pid
  KG_IOS_LOCK_WAIT_SECONDS=0
  KG_IOS_LOCK_HOLDER_PID=""

  while ! shlock -f "$lock_file" -p "$owner_pid"; do
    holder_pid="$(cat "$lock_file" 2>/dev/null || true)"
    KG_IOS_LOCK_HOLDER_PID="$holder_pid"
    if [[ -n "$holder_pid" ]] && ! kill -0 "$holder_pid" 2>/dev/null; then
      # Steal only the exact dead PID we observed. Another waiter may have
      # replaced the lock between our read and this ownership re-check.
      if [[ "$(cat "$lock_file" 2>/dev/null || true)" == "$holder_pid" ]]; then
        printf '%s stale lock kind=%s holderPid=%s alive=false; stealing\n' \
          "$prefix" "$kind" "$holder_pid"
        rm -f "$lock_file"
      fi
      continue
    fi
    if [[ "$timeout_mode" == pre-sleep ]] && (( waited >= timeout )); then
      KG_IOS_LOCK_WAIT_SECONDS="$waited"
      return 1
    fi
    previous_waited="$waited"
    sleep "$poll"
    waited=$((waited + poll))
    kg_ios_lock_wait_heartbeat "$prefix" "$kind" "$waited" "$previous_waited" "$holder_pid"
    if [[ "$timeout_mode" == post-sleep ]] && (( waited >= timeout )); then
      KG_IOS_LOCK_WAIT_SECONDS="$waited"
      return 1
    fi
  done

  KG_IOS_LOCK_WAIT_SECONDS="$waited"
  return 0
}
