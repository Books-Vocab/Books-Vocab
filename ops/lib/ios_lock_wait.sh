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

# The queue is deliberately adjacent to the lock rather than in the repo. A
# worktree may be removed while a caller is waiting, but the machine lock and
# its queue still need to describe the live waiters. Ticket names sort by the
# zero-padded monotonic sequence, so a new waiter cannot bypass a predecessor
# that has already entered the queue.
KG_IOS_LOCK_QUEUE_TICKET=""
KG_IOS_LOCK_QUEUE_GUARD=""
KG_IOS_LOCK_QUEUE_GUARD_MARKER=""
KG_IOS_LOCK_QUEUE_GUARD_TOKEN=""
KG_IOS_LOCK_QUEUE_HEAD=""
KG_IOS_LOCK_SAVED_INT_TRAP=""
KG_IOS_LOCK_SAVED_TERM_TRAP=""
KG_IOS_LOCK_SAVED_HUP_TRAP=""

# kg_ios_release_shlock_if_owner <lock-file> <owner-pid>
# Remove exactly one lock, and only while its contents still name owner-pid.
# Every caller uses this helper in cleanup so a late cleanup cannot delete a
# lock acquired by the next process.
kg_ios_release_shlock_if_owner() {
  local lock_file="$1" owner_pid="$2" observed
  observed="$(cat "$lock_file" 2>/dev/null || true)"
  [[ "$observed" == "$owner_pid" ]] || return 0
  [[ "$(cat "$lock_file" 2>/dev/null || true)" == "$owner_pid" ]] || return 0
  rm -f "$lock_file"
}

kg_ios_lock_queue_release_guard() {
  local guard="${1:-${KG_IOS_LOCK_QUEUE_GUARD:-}}"
  local marker="${2:-${KG_IOS_LOCK_QUEUE_GUARD_MARKER:-}}"
  local token="${3:-${KG_IOS_LOCK_QUEUE_GUARD_TOKEN:-}}" observed
  [[ -n "$guard" && -n "$token" ]] || return 0
  observed="$(cat "$guard" 2>/dev/null || true)"
  [[ "$observed" == "$token" ]] || return 0
  [[ "$(cat "$guard" 2>/dev/null || true)" == "$token" ]] || return 0
  rm -f "$guard"
  [[ -z "$marker" ]] || rm -f "$marker"
}

kg_ios_lock_wait_cleanup_ticket() {
  local ticket="${KG_IOS_LOCK_QUEUE_TICKET:-}"
  [[ -z "$ticket" ]] || rm -f "$ticket" 2>/dev/null || true
  kg_ios_lock_queue_release_guard || true
  KG_IOS_LOCK_QUEUE_TICKET=""
  KG_IOS_LOCK_QUEUE_GUARD=""
  KG_IOS_LOCK_QUEUE_GUARD_MARKER=""
  KG_IOS_LOCK_QUEUE_GUARD_TOKEN=""
  return 0
}

kg_ios_lock_wait_restore_traps() {
  local int_trap="${KG_IOS_LOCK_SAVED_INT_TRAP:-}"
  local term_trap="${KG_IOS_LOCK_SAVED_TERM_TRAP:-}"
  local hup_trap="${KG_IOS_LOCK_SAVED_HUP_TRAP:-}"
  if [[ -n "$int_trap" ]]; then eval "$int_trap"; else trap - INT; fi
  if [[ -n "$term_trap" ]]; then eval "$term_trap"; else trap - TERM; fi
  if [[ -n "$hup_trap" ]]; then eval "$hup_trap"; else trap - HUP; fi
  KG_IOS_LOCK_SAVED_INT_TRAP=""
  KG_IOS_LOCK_SAVED_TERM_TRAP=""
  KG_IOS_LOCK_SAVED_HUP_TRAP=""
  return 0
}

kg_ios_lock_wait_signal() {
  local signal_name="$1" signal_exit="$2"
  kg_ios_lock_wait_cleanup_ticket
  kg_ios_lock_wait_restore_traps
  # Re-deliver the signal after restoring the caller's trap. This preserves
  # ios_test.sh's exactly-once cleanup/re-raise contract; a plain exit here
  # would bypass its signal diagnostic and could change signal semantics.
  kill -s "$signal_name" "$$" 2>/dev/null || true
  exit "$signal_exit"
}

kg_ios_lock_wait_install_traps() {
  KG_IOS_LOCK_SAVED_INT_TRAP="$(trap -p INT 2>/dev/null || true)"
  KG_IOS_LOCK_SAVED_TERM_TRAP="$(trap -p TERM 2>/dev/null || true)"
  KG_IOS_LOCK_SAVED_HUP_TRAP="$(trap -p HUP 2>/dev/null || true)"
  trap 'kg_ios_lock_wait_signal INT 130' INT
  trap 'kg_ios_lock_wait_signal TERM 143' TERM
  trap 'kg_ios_lock_wait_signal HUP 129' HUP
}

kg_ios_lock_queue_create_ticket() {
  local lock_file="$1" owner_pid="$2" queue_dir="$3"
  local guard="$queue_dir/.counter.lock"
  local marker token next ticket_name ticket_path guard_pid guard_token
  : "$lock_file"
  mkdir -p "$queue_dir" || return 1

  while :; do
    token="${owner_pid}.${RANDOM:-0}"
    marker="$queue_dir/.counter-owner-$token"
    if ! printf '%s\n' "$token" >"$marker"; then
      return 1
    fi
    if ln "$marker" "$guard" 2>/dev/null; then
      KG_IOS_LOCK_QUEUE_GUARD="$guard"
      KG_IOS_LOCK_QUEUE_GUARD_MARKER="$marker"
      KG_IOS_LOCK_QUEUE_GUARD_TOKEN="$token"
      next="$(cat "$queue_dir/.next" 2>/dev/null || printf '0')"
      case "$next" in
        ''|*[!0-9]*) next=0 ;;
      esac
      ticket_name="$(printf 'ticket-%020d-%s' "$next" "$owner_pid")"
      ticket_path="$queue_dir/$ticket_name"
      # Persist the next sequence before exposing the ticket. If this process
      # is killed in the gap, the next waiter consumes a harmless sequence gap
      # instead of reusing a sequence that may already be visible.
      if ! printf '%s\n' "$((next + 1))" >"$queue_dir/.next"; then
        kg_ios_lock_wait_cleanup_ticket
        return 1
      fi
      KG_IOS_LOCK_QUEUE_TICKET="$ticket_path"
      if ! printf '%s\n' "$owner_pid" >"$ticket_path"; then
        kg_ios_lock_wait_cleanup_ticket
        return 1
      fi
      kg_ios_lock_queue_release_guard
      KG_IOS_LOCK_QUEUE_GUARD=""
      KG_IOS_LOCK_QUEUE_GUARD_MARKER=""
      KG_IOS_LOCK_QUEUE_GUARD_TOKEN=""
      return 0
    fi
    rm -f "$marker"

    guard_token="$(cat "$guard" 2>/dev/null || true)"
    case "$guard_token" in
      *.*)
        guard_pid="${guard_token%%.*}"
        if [[ "$guard_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$guard_pid" 2>/dev/null; then
          # The owner token may include a random suffix, so re-read and
          # compare its PID component immediately before removal. A live
          # predecessor is never removed from the ticket queue by this path.
          if [[ "$(cat "$guard" 2>/dev/null || true)" == "$guard_token" ]]; then
            rm -f "$guard" || true
          fi
        fi
        ;;
    esac
    sleep 0.05
  done
}

kg_ios_lock_queue_prune_dead_tickets() {
  local queue_dir="$1" ticket_path ticket_pid
  for ticket_path in "$queue_dir"/ticket-*; do
    [[ -f "$ticket_path" ]] || continue
    ticket_pid="$(cat "$ticket_path" 2>/dev/null || true)"
    case "$ticket_pid" in
      ''|*[!0-9]*) continue ;;
    esac
    if ! kill -0 "$ticket_pid" 2>/dev/null; then
      # Re-read before removing so a ticket replacement cannot be mistaken
      # for an abandoned waiter.
      if [[ "$(cat "$ticket_path" 2>/dev/null || true)" == "$ticket_pid" ]]; then
        rm -f "$ticket_path" || true
      fi
    fi
  done
}

kg_ios_lock_queue_refresh_head() {
  local queue_dir="$1" ticket_path
  KG_IOS_LOCK_QUEUE_HEAD=""
  for ticket_path in "$queue_dir"/ticket-*; do
    [[ -f "$ticket_path" ]] || continue
    if [[ -z "$KG_IOS_LOCK_QUEUE_HEAD" || "$ticket_path" < "$KG_IOS_LOCK_QUEUE_HEAD" ]]; then
      KG_IOS_LOCK_QUEUE_HEAD="$ticket_path"
    fi
  done
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
  local timeout_mode="${7:-pre-sleep}" queue_dir="${lock_file}.queue"
  local waited=0 previous_waited holder_pid
  KG_IOS_LOCK_WAIT_SECONDS=0
  KG_IOS_LOCK_HOLDER_PID=""
  KG_IOS_LOCK_QUEUE_TICKET=""
  KG_IOS_LOCK_QUEUE_GUARD=""
  KG_IOS_LOCK_QUEUE_GUARD_MARKER=""
  KG_IOS_LOCK_QUEUE_GUARD_TOKEN=""
  kg_ios_lock_wait_install_traps
  if ! kg_ios_lock_queue_create_ticket "$lock_file" "$owner_pid" "$queue_dir"; then
    kg_ios_lock_wait_cleanup_ticket
    kg_ios_lock_wait_restore_traps
    return 1
  fi

  while :; do
    kg_ios_lock_queue_prune_dead_tickets "$queue_dir"
    kg_ios_lock_queue_refresh_head "$queue_dir"
    if [[ "$KG_IOS_LOCK_QUEUE_HEAD" == "$KG_IOS_LOCK_QUEUE_TICKET" ]] && \
      shlock -f "$lock_file" -p "$owner_pid"; then
      kg_ios_lock_wait_cleanup_ticket
      kg_ios_lock_wait_restore_traps
      KG_IOS_LOCK_WAIT_SECONDS="$waited"
      return 0
    fi
    holder_pid="$(cat "$lock_file" 2>/dev/null || true)"
    KG_IOS_LOCK_HOLDER_PID="$holder_pid"
    if [[ "$KG_IOS_LOCK_QUEUE_HEAD" == "$KG_IOS_LOCK_QUEUE_TICKET" && \
      -n "$holder_pid" ]] && ! kill -0 "$holder_pid" 2>/dev/null; then
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
      kg_ios_lock_wait_cleanup_ticket
      kg_ios_lock_wait_restore_traps
      return 1
    fi
    previous_waited="$waited"
    sleep "$poll"
    waited=$((waited + poll))
    kg_ios_lock_wait_heartbeat "$prefix" "$kind" "$waited" "$previous_waited" "$holder_pid"
    if [[ "$timeout_mode" == post-sleep ]] && (( waited >= timeout )); then
      KG_IOS_LOCK_WAIT_SECONDS="$waited"
      kg_ios_lock_wait_cleanup_ticket
      kg_ios_lock_wait_restore_traps
      return 1
    fi
  done
}
