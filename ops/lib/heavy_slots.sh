#!/usr/bin/env bash
# heavy_slots.sh — host-wide counting semaphore for heavy ops test groups.
# Source-only (no exec bit); bash 3.2 safe; no external dependencies beyond ps/sleep.
#
# WHY: ~25 concurrent agents each running heavy test groups pushed load to 60-110
# on 10 cores, producing false timing-test failures and timeouts. Worktree-local
# locks cannot see other worktrees; this limiter is host-wide.
#
# Model: KG_HEAVY_SLOTS slot directories (default 3) under KG_HEAVY_SLOTS_DIR
# (default $HOME/Library/Caches/kg/heavy-slots). `mkdir` is the atomic claim. A slot
# holds `info` (pid, process start time, group, claim time). A holder is stale when
# its pid is dead or its start time no longer matches (pid reuse); a stale slot is
# reclaimed under a per-slot mutex with the verdict re-validated inside it (see
# _hs_reclaim), so a late waiter can never evict a live re-claimer.
#
# Never deadlocks: the wait is bounded by KG_HEAVY_SLOTS_WAIT seconds (default 1800).
# On timeout it prints who holds the slots and returns 75 (inconclusive, NOT a pass).
# Re-entrant: a child test_ops.sh under a held slot inherits KG_HEAVY_SLOT_HELD and
# does not claim a second one. KG_HEAVY_SLOTS=0 disables the limiter.
#
# Entry: heavy_slots_run <group> <cmd...> runs <cmd...> under a slot when <group> is
# listed in the HEAVY_TESTS array of the caller, otherwise runs it directly.

_hs_dir() { printf '%s' "${KG_HEAVY_SLOTS_DIR:-$HOME/Library/Caches/kg/heavy-slots}"; }
_hs_max() {
  local n="${KG_HEAVY_SLOTS:-3}"
  case "$n" in ''|*[!0-9]*) n=3 ;; esac
  printf '%s' "$n"
}
_hs_started() { ps -o lstart= -p "$1" 2>/dev/null | sed 's/^ *//;s/ *$//' || true; }

_hs_is_heavy() {
  local g
  for g in ${HEAVY_TESTS[@]+"${HEAVY_TESTS[@]}"}; do
    [[ "$g" == "$1" ]] && return 0
  done
  return 1
}

# stale <slotdir>: 0 when the holder is gone (or never finished writing info).
_hs_stale() {
  local slot="$1" pid="" lstart="" now cur mtime
  if [[ -f "$slot/info" ]]; then
    pid="$(sed -n '1p' "$slot/info" 2>/dev/null || true)"
    lstart="$(sed -n '2p' "$slot/info" 2>/dev/null || true)"
  fi
  if [[ -z "$pid" ]]; then
    # mkdir succeeded but info not written yet: only stale after a grace period.
    now="$(date +%s)"
    # GNU `stat -f` is filesystem status (junk, exit 0): try `-c %Y` first, BSD `-f %m` second.
    mtime="$(stat -c %Y "$slot" 2>/dev/null || stat -f %m "$slot" 2>/dev/null || true)"
    case "$mtime" in ''|*[!0-9]*) mtime="$now" ;; esac
    (( now - mtime > 10 )) && return 0
    return 1
  fi
  kill -0 "$pid" 2>/dev/null || return 0
  cur="$(_hs_started "$pid")"
  [[ -n "$lstart" && -n "$cur" && "$cur" != "$lstart" ]] && return 0
  return 1
}

# reclaim <slotdir>: 0 = this caller removed a stale slot, 1 = nothing removed.
# Staleness is judged by the caller BEFORE this runs, so by now it may be obsolete:
# another waiter may already have reclaimed AND re-claimed the slot with a live
# holder, and a bare `mv` would then evict that live holder (two runners under one
# slot). So reclaim is serialized by a per-slot mutex (`<slot>.reclaim`, mkdir) and the
# verdict is re-validated inside it. Only reclaimers remove a dead holder's slot, so
# under the mutex the re-validated slot cannot change before the mv. A crashed
# reclaimer's mutex records its pid and is itself broken by the same stale test
# (residual risk: only if a reclaimer stalls >10s inside a millisecond section).
_hs_reclaim() {
  local slot="$1" mutex dead rc=1
  mutex="${slot}.reclaim"
  if ! mkdir "$mutex" 2>/dev/null; then
    if [[ -d "$mutex" ]] && _hs_stale "$mutex"; then
      dead="${mutex}.dead.$$.$RANDOM"
      mv "$mutex" "$dead" 2>/dev/null && rm -rf "$dead"
    fi
    return 1  # another reclaimer is working on it; retry on the next pass
  fi
  printf '%s\n%s\n' "$$" "$(_hs_started "$$")" >"$mutex/info"
  if _hs_stale "$slot"; then
    echo "heavy-slots: reclaiming stale $(basename "$slot") (holder gone)" >&2
    dead="${slot}.dead.$$.$RANDOM"
    mv "$slot" "$dead" 2>/dev/null && rm -rf "$dead"
    rc=0
  fi
  rm -rf "$mutex"
  return "$rc"
}

heavy_slots_holders() {
  local dir slot pid group since
  dir="$(_hs_dir)"
  for slot in "$dir"/slot.*; do
    [[ -d "$slot" && "$slot" != *.dead.* && "$slot" != *.reclaim ]] || continue
    pid="$(sed -n '1p' "$slot/info" 2>/dev/null || true)"
    group="$(sed -n '3p' "$slot/info" 2>/dev/null || true)"
    since="$(sed -n '4p' "$slot/info" 2>/dev/null || true)"
    printf '  %s held by pid=%s group=%s since=%s\n' "$(basename "$slot")" "${pid:-?}" "${group:-?}" "${since:-?}"
  done
}

# heavy_slots_try <group>: one pass over the slots; 0 = claimed (HEAVY_SLOT_PATH set).
heavy_slots_try() {
  local group="$1" dir max i slot
  dir="$(_hs_dir)"
  max="$(_hs_max)"
  mkdir -p "$dir" 2>/dev/null || return 1
  for ((i = 1; i <= max; i++)); do
    slot="$dir/slot.$i"
    if mkdir "$slot" 2>/dev/null; then
      printf '%s\n%s\n%s\n%s\n' "$$" "$(_hs_started "$$")" "$group" "$(date '+%Y-%m-%dT%H:%M:%S')" >"$slot/info"
      HEAVY_SLOT_PATH="$slot"
      return 0
    fi
    if _hs_stale "$slot"; then
      if _hs_reclaim "$slot" && mkdir "$slot" 2>/dev/null; then
        printf '%s\n%s\n%s\n%s\n' "$$" "$(_hs_started "$$")" "$group" "$(date '+%Y-%m-%dT%H:%M:%S')" >"$slot/info"
        HEAVY_SLOT_PATH="$slot"
        return 0
      fi
    fi
  done
  return 1
}

heavy_slots_release() {
  if [[ -n "${HEAVY_SLOT_PATH:-}" ]]; then
    # Only remove a slot we still own (it may have been reclaimed if we were stalled).
    if [[ "$(sed -n '1p' "$HEAVY_SLOT_PATH/info" 2>/dev/null || true)" == "$$" ]]; then
      rm -rf "$HEAVY_SLOT_PATH"
    fi
    HEAVY_SLOT_PATH=""
  fi
}

# heavy_slots_acquire <group>: blocks (bounded). 0 = claimed, 75 = wait timed out.
heavy_slots_acquire() {
  local group="$1" wait_s poll start last_msg now
  wait_s="${KG_HEAVY_SLOTS_WAIT:-1800}"
  poll="${KG_HEAVY_SLOTS_POLL:-1}"
  start="$SECONDS"
  last_msg=-1000
  while ! heavy_slots_try "$group"; do
    now="$SECONDS"
    if (( now - start >= wait_s )); then
      echo "heavy-slots: gave up after ${wait_s}s waiting for a slot (KG_HEAVY_SLOTS=$(_hs_max)); group '$group' NOT run (rc=75). Holders:" >&2
      heavy_slots_holders >&2
      return 75
    fi
    if (( now - last_msg >= ${KG_HEAVY_SLOTS_NOTICE:-30} )); then
      echo "heavy-slots: '$group' waiting for a slot ($(( now - start ))s/${wait_s}s, limit KG_HEAVY_SLOTS=$(_hs_max)). Holders:" >&2
      heavy_slots_holders >&2
      last_msg="$now"
    fi
    sleep "$poll"
  done
  trap heavy_slots_release EXIT
  return 0
}

heavy_slots_run() {
  local group="$1" rc
  shift
  if [[ "$(_hs_max)" -eq 0 || -n "${KG_HEAVY_SLOT_HELD:-}" ]] || ! _hs_is_heavy "$group"; then
    "$@"
    return $?
  fi
  heavy_slots_acquire "$group" || return $?
  KG_HEAVY_SLOT_HELD=1 "$@"
  rc=$?
  heavy_slots_release
  return "$rc"
}
