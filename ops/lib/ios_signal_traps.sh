#!/usr/bin/env bash
# ios_signal_traps.sh — abort-on-signal semantics for the iOS runner scripts.
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
#
# HUP is trapped explicitly even though the EXIT-trap fallback above already
# handles it: it buys the `aborted by SIGHUP` diagnostic (ssh drops to the
# standby build host are otherwise silent) and states the contract in the code
# rather than relying on bash's implicit EXIT-on-fatal-signal behaviour. It does
# NOT fix a lock leak — there was none on the HUP path.
#
# Callers must define their cleanup function BEFORE calling
# kg_install_signal_traps, and pass its name:
#     cleanup() { ...; }
#     kg_install_signal_traps cleanup
# Regression: ops/tests/test_ios_signal_traps.sh

KG_SIGNAL_CLEANUP_FN=""
KG_SIGNAL_CLEANUP_DONE=0

# Idempotent cleanup gate. Bound to EXIT and called from the signal path, so it
# must tolerate being reached twice. `[[ ... ]] && cmd` mid-function does not
# trip `set -e` — it is not the final command of the function.
kg_run_cleanup_once() {
  [[ "$KG_SIGNAL_CLEANUP_DONE" -eq 1 ]] && return 0
  KG_SIGNAL_CLEANUP_DONE=1
  [[ -n "$KG_SIGNAL_CLEANUP_FN" ]] && "$KG_SIGNAL_CLEANUP_FN"
  return 0
}

# kg_on_signal <SIGNAME>
# Announce, clean up once, disarm, then re-raise the same signal at default
# disposition so the process dies with 128+N. The trailing `exit` is a
# belt-and-braces fallback for the (unreachable in practice) case where the
# re-raise does not terminate us.
kg_on_signal() {
  local sig="$1"
  echo "[ios_test] aborted by SIG$sig pid=$$" >&2
  kg_run_cleanup_once
  trap - EXIT "$sig"
  kill -s "$sig" "$$"
  exit $(( 128 + $(kill -l "$sig") ))
}

# kg_install_signal_traps <cleanup-function-name>
kg_install_signal_traps() {
  KG_SIGNAL_CLEANUP_FN="${1:?cleanup function required}"
  KG_SIGNAL_CLEANUP_DONE=0
  trap kg_run_cleanup_once EXIT
  trap "kg_on_signal INT" INT
  trap "kg_on_signal TERM" TERM
  trap "kg_on_signal HUP" HUP
}
