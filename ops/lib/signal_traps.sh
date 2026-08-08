#!/usr/bin/env bash
# signal_traps.sh — abort-on-signal semantics for deployment and iOS runners.
# Source-only (no exec bit); bash 3.2 safe; no external dependencies.
#
# WHY THIS EXISTS (IMP-0017)
# `trap cleanup EXIT INT TERM` — one handler bound to three events with no
# re-raise — looks like it aborts the run. It does not. bash runs the handler
# and then RESUMES at the interruption point, so the script finishes its
# remaining work and exits 0. Measured on ops/ios_test.sh under a real SIGTERM:
# rc=0 with the complete normal output, and cleanup executed TWICE (once for the
# signal, once again for EXIT) 18.9 seconds apart.
#
# The counter-intuitive part, measured on /bin/bash 3.2.57 (darwin): a bare
# `trap cleanup EXIT` — no INT/TERM — is ALREADY correct. bash runs the EXIT
# trap on death by an untrapped fatal signal and still dies with 128+N
# (SIGTERM -> rc=143 cleanup×1 no-resume; SIGHUP -> rc=129 cleanup×1 no-resume).
# ADDING `INT TERM` to that same trap is what breaks it: the signal becomes
# "handled", so bash resumes instead of dying. The bug is not a missing handler,
# it is a handler that does not re-raise. (ops/ios_build.sh and
# ops/ios_release.sh use the bare EXIT form and are unaffected.)
#
# Two failures compound in ios_test.sh, and the second is the dangerous one:
#   1. FALSE GREEN — an interrupted run reports success. streaming_command.py
#      terminates a timed-out child with SIGTERM and only escalates to SIGKILL
#      after 5s, which is ample time for the run to finish and report a pass.
#   2. LOCKLESS EXECUTION — cleanup() releases the shared /tmp/kg-ios-build.lock,
#      the per-device lock, and the leased pool simulator, and then the run keeps
#      going. Measured with a real shlock-acquired lock and a real SIGTERM:
#      19.35s in which the lock file was GONE while the process was still ALIVE,
#      i.e. writing shared DerivedData while another agent may hold the lock.
#      Same probe against this lib: 0 such samples, dead 0.71s after the signal.
#
# THE CONTRACT
#   * cleanup runs EXACTLY ONCE, whether the run ends normally or by signal.
#   * on a signal the process DIES with the conventional 128+N status
#     (TERM=143, HUP=129, INT=130) instead of resuming with the locks already
#     released. Dying by re-raising the same signal — rather than `exit N` —
#     keeps the kernel-level "killed by signal N" fact intact for the parent.
#   * an uninterrupted run is untouched: normal exit status, cleanup once.
#   * NOTHING inside the handler may break the two guarantees above. The handler
#     is the last code that runs; a failure in it is unrecoverable and silent.
#     See "THE HANDLER MUST BE UNKILLABLE" below — this is where the first cut
#     of this lib was wrong.
#
# THE HANDLER MUST BE UNKILLABLE
# Callers run under `set -euo pipefail`, and trap handlers INHERIT it. Anything
# in the handler that can fail therefore aborts it before the re-raise, and the
# 128+N contract silently does not happen. Two real ways that bites, both
# measured on bash 3.2.57 against a victim identical but for the handler shape:
#
#   1. THE DIAGNOSTIC. An unguarded `echo "..." >&2` is not safe: fd 2 is not
#      guaranteed writable at abort time — that is precisely when ssh has just
#      dropped. Measured, SIGTERM delivered in every cell:
#        fd 2 closed (2>&-, write fails EBADF)      bare echo -> rc 1   (want 143)
#        fd 2 = pipe whose reader exited (SIGPIPE)  bare echo -> rc 141 (want 143)
#      For SIGHUP the pipe case is strictly WORSE than having no handler at all
#      (129 -> 141), which would have defeated the reason the HUP trap exists.
#      `echo ... >&2 || true` is NOT sufficient: it fixes the EBADF cell but not
#      the pipe cell, because SIGPIPE kills the shell mid-`echo`, before `||`
#      is ever reached (measured: still 141). The write must therefore happen in
#      a SUBSHELL, so SIGPIPE kills the subshell and the handler survives.
#      A subshell also contains a second hazard: when a builtin's write FAILS,
#      bash keeps the bytes in its stdio buffer and flushes them into the NEXT
#      file opened on that fd — so an undelivered diagnostic would otherwise
#      reappear inside whatever file cleanup writes to next.
#
#   2. THE CLEANUP CALL. `[[ -n "$fn" ]] && "$fn"` puts the call at the END of
#      an &&-list, and `set -e` exempts every command in an &&-list EXCEPT that
#      final one. So a cleanup returning non-zero — a stale lockdir, a vanished
#      leased simulator — aborted the handler and the process exited with the
#      cleanup's status (measured: rc=3) instead of 143. Releasing a lock is
#      exactly the kind of thing that fails for real, so the call is made from
#      an `if` body and its status is reported but not allowed to propagate.
#
# HUP is trapped explicitly even though the EXIT-trap fallback above already
# handles it: it buys the `aborted by SIGHUP` diagnostic (ssh drops to the
# standby build host are otherwise silent) and states the contract in the code
# rather than relying on bash's implicit EXIT-on-fatal-signal behaviour. It does
# NOT fix a lock leak — there was none on the HUP path. That diagnostic is the
# ONLY observable difference between having the HUP trap and not having it, so
# it is what the regression suite asserts on (test F3); the exit status alone
# cannot tell the two apart.
#
# Callers must define their cleanup function BEFORE calling
# kg_install_signal_traps, and pass its name. The optional second argument is
# the tag used in the diagnostic, for callers that are not ios_test.sh:
#     cleanup() { ...; }
#     kg_install_signal_traps cleanup            # -> "[ios_test] aborted by ..."
#     kg_install_signal_traps cleanup kg_reconcile
# Regression: ops/tests/test_ios_signal_traps.sh

KG_SIGNAL_CLEANUP_FN=""
KG_SIGNAL_CLEANUP_DONE=0
KG_SIGNAL_TAG="ios_test"

# kg_signal_note <message...>
# Write a diagnostic that CANNOT take the caller down, however broken fd 2 is.
# The subshell absorbs SIGPIPE (dead reader) and contains the stdio buffer of a
# failed write; `|| true` absorbs a non-zero status (EBADF, EIO on a closed pty)
# under `set -e`. Always returns 0. See "THE HANDLER MUST BE UNKILLABLE".
kg_signal_note() {
  ( echo "$*" >&2 ) || true
  return 0
}

# Idempotent cleanup gate. Bound to EXIT and called from the signal path, so it
# must tolerate being reached twice, and must not propagate a cleanup failure:
# on the signal path that would cost us the re-raise, and on the normal path it
# would turn a passing run red on a lock-release hiccup. The failure is reported
# instead of swallowed.
kg_run_cleanup_once() {
  if [[ "$KG_SIGNAL_CLEANUP_DONE" -eq 1 ]]; then
    return 0
  fi
  KG_SIGNAL_CLEANUP_DONE=1
  if [[ -n "$KG_SIGNAL_CLEANUP_FN" ]]; then
    local crc=0
    "$KG_SIGNAL_CLEANUP_FN" || crc=$?
    if [[ "$crc" -ne 0 ]]; then
      kg_signal_note "[$KG_SIGNAL_TAG] cleanup ${KG_SIGNAL_CLEANUP_FN}() exited $crc"
    fi
  fi
  return 0
}

# kg_on_signal <SIGNAME>
# Announce, clean up once, disarm, then re-raise the same signal at default
# disposition so the process dies with 128+N. The trailing `exit` is a
# belt-and-braces fallback for the (unreachable in practice) case where the
# re-raise does not terminate us.
kg_on_signal() {
  local sig="$1"
  kg_signal_note "[$KG_SIGNAL_TAG] aborted by SIG$sig pid=$$"
  kg_run_cleanup_once
  trap - EXIT "$sig"
  kill -s "$sig" "$$"
  exit $(( 128 + $(kill -l "$sig") ))
}

# kg_install_signal_traps <cleanup-function-name> [diagnostic-tag]
kg_install_signal_traps() {
  KG_SIGNAL_CLEANUP_FN="${1:?cleanup function required}"
  KG_SIGNAL_TAG="${2:-ios_test}"
  KG_SIGNAL_CLEANUP_DONE=0
  trap kg_run_cleanup_once EXIT
  trap "kg_on_signal INT" INT
  trap "kg_on_signal TERM" TERM
  trap "kg_on_signal HUP" HUP
}
