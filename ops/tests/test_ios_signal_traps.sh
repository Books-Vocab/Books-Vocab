#!/usr/bin/env bash
# test_ios_signal_traps.sh — signal-abort semantics for ops/lib/signal_traps.sh,
# offline / no Xcode.
#
# Regression guards (IMP-0017, mute rc-0 abort, 2026-08-06):
#   1. A signalled run must DIE with the conventional 128+N status. Before this
#      lib, `ops/ios_test.sh` armed `trap cleanup EXIT INT TERM` — one handler,
#      three events, no re-raise — so bash ran cleanup and then RESUMED at the
#      interruption point and exited 0. Measured on the real script under a real
#      SIGTERM: rc=0 with the full normal output.
#   2. cleanup must run EXACTLY ONCE. The old shape ran it twice (once for the
#      signal, once again for EXIT), 18.9s apart.
#   3. The code after the interruption point must NOT execute. That window is
#      the dangerous half: `cleanup()` releases the shared /tmp/kg-ios-build.lock
#      and the leased simulator, so every second of continued execution is a
#      lockless run writing shared DerivedData while another agent believes it
#      holds the lock. Measured with a real shlock-acquired lock: 19.35s with the
#      lock file GONE while the process was still ALIVE.
#   4. An UNinterrupted run must still exit 0 with cleanup run once — this is
#      what falsifies an "always self-kill" or "never run cleanup" fake fix.
#
# WHICH ASSERTION PROVES WHAT (measured, not assumed — bash 3.2.57/darwin):
#   * A2 (SIGTERM) is load-bearing. A3 (SIGHUP) is NOT: a bare `trap cleanup
#     EXIT` already dies 129 with cleanup once under SIGHUP, so A3 stays green
#     even with `trap "kg_on_signal HUP" HUP` deleted from the lib outright
#     (verified by mutation). A3 is kept as a status/cleanup guard only — the
#     assertion that actually pins the explicit HUP handler is F3, which reads
#     the handler's own diagnostic off stderr. Nothing but kg_on_signal can
#     produce that line: bash's implicit EXIT-on-fatal-signal path is silent,
#     and bash's own "Hangup: 1" goes to the HARNESS's stderr, not the victim's.
#   * Section D is a live control: it runs the OLD trap shape through the SAME
#     fixture and requires it to still show rc=0 / cleanup twice / RESUMED. If
#     the fixture ever stops delivering signals (CI timing, a bash change), D
#     goes red instead of A silently going green for the wrong reason.
#   * Section E is the hostile-stderr matrix. It uses REAL unwritable
#     descriptors, never a mock, because the whole defect is that the real
#     condition behaves differently from a simulated one.
#   * F4/F6 prove the process was KILLED BY the signal rather than calling
#     `exit 128+N`. Producer of that string: the harness's own bash, printing a
#     job-status line derived from the kernel wait status when it reaps a
#     WIFSIGNALED child. Measured: present for a real re-raise, ABSENT for an
#     `exit 143` victim — so it discriminates, which plain rc=143 cannot.
#
# COUNTING CLEANUPS — why an exact sentinel and not `wc -l`:
# When a bash builtin's write FAILS, the bytes stay in bash's stdio buffer and
# are flushed into the NEXT file opened on that fd. So in sections E/G the
# handler's diagnostic — which never reached the closed/broken stderr — is
# flushed into $MARKER when cleanup opens it, and `wc -l` would count it as an
# extra cleanup. Measured on bash 3.2.57. RUN_CLEANUPS therefore counts only
# lines equal to the sentinel `cleaned`, which only cleanup() can write.
#
# Deliberately NOT tested:
#   * SIGINT. A background child of a non-interactive shell has SIGINT set to
#     SIG_IGN, so the harness cannot deliver it; the victim just finishes
#     normally and the case would be green for the wrong reason. The lib still
#     installs an INT handler for interactive/foreground use.
#   * A pty whose master was closed (the `ssh -t` drop). Its write fails with an
#     error return, which is the SAME code path as E1/E2's EBADF — the handler
#     either survives a failed write or it does not. Building a real pty here
#     would add a dependency without adding a distinct failure mode.
#
# REGISTERED: `ops/test_ops.sh:54` declares the `ios-signal-traps` group and
# `ops/tests/test_ops_ci_coverage.sh:53` puts it in LINUX_GROUPS, so CI runs
# this file. That wiring landed in the same batch as this header; an earlier
# draft said NOT REGISTERED and was already false by the time it shipped.
# What that means for section B: it guards the ios_test.sh wiring and CI now
# executes it unconditionally, so a future edit reverting that wiring is
# caught by CI, not only by the cutover gate that routes on this path.
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$WORKSPACE/ops/lib/signal_traps.sh"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

[[ -f "$LIB" ]] || { echo "FATAL: $LIB missing"; exit 1; }

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# ── fixture ───────────────────────────────────────────────────────────────────
# Victims with IDENTICAL bodies, differing only in how the traps are armed (the
# lib under test vs. the pre-fix shape) or in how cleanup behaves. All append
# the sentinel `cleaned` to $MARKER from cleanup, and print RESUMED only if
# execution survives the interruption point.
cat >"$TMP/victim_lib.sh" <<EOF
set -euo pipefail
source "$LIB"
cleanup() { echo cleaned >> "\$MARKER"; }
kg_install_signal_traps cleanup
sleep "\$SLEEP"
echo RESUMED
exit 0
EOF

cat >"$TMP/victim_oldshape.sh" <<'EOF'
set -euo pipefail
cleanup() { echo cleaned >> "$MARKER"; }
trap cleanup EXIT INT TERM
sleep "$SLEEP"
echo RESUMED
exit 0
EOF

# Cleanup that reports failure. Releasing a lock can fail for real (a stale NFS
# handle, a vanished lockdir). It must not cost us the re-raise: `set -e` in the
# caller plus an &&-list in the lib would abort the handler at that point.
cat >"$TMP/victim_cleanupfails.sh" <<EOF
set -euo pipefail
source "$LIB"
cleanup() { echo cleaned >> "\$MARKER"; return 3; }
kg_install_signal_traps cleanup
sleep "\$SLEEP"
echo RESUMED
exit 0
EOF

# A non-ios caller: the diagnostic tag must not be hardcoded to [ios_test], or
# the lib cannot be reused by the other scripts carrying this same trap shape.
cat >"$TMP/victim_tagged.sh" <<EOF
set -euo pipefail
source "$LIB"
cleanup() { echo cleaned >> "\$MARKER"; }
kg_install_signal_traps cleanup kg_reconcile
sleep "\$SLEEP"
echo RESUMED
exit 0
EOF

# run_victim <victim-file> <signal|""> <sleep-seconds> [stderr-mode]
# stderr-mode: split (default) | closed | deadpipe
#   split    — fd 2 to its own file, so RUN_ERR proves the diagnostic went to
#              STDERR and RUN_OUT proves it did not pollute stdout (ios_test.sh
#              --json must emit a single JSON document on stdout).
#   closed   — `2>&-`. Writes fail EBADF. Real, not simulated.
#   deadpipe — fd 2 is a pipe whose reader has already exited, so writes raise
#              SIGPIPE. Built with process substitution: both pipe ends exist at
#              fork time, so there is no open() race. (A FIFO would block on
#              open-for-write until a reader appears — measured, and the reason
#              this is not a mkfifo.)
# Sets RUN_RC / RUN_CLEANUPS / RUN_OUT / RUN_ERR / RUN_PID / RUN_WAITMSG.
# bash defers a trapped signal until the foreground child (here `sleep`)
# returns, so each signal case costs ≈SLEEP seconds; 2s is enough.
run_victim() {
  local victim="$1" sig="$2" slp="$3" mode="${4:-split}"
  local tag marker out err wmsg pid rc=0
  tag="$(date +%s)-$$-${RANDOM}"
  marker="$TMP/marker.$tag"; out="$TMP/out.$tag"
  err="$TMP/err.$tag";       wmsg="$TMP/wait.$tag"
  : >"$marker"; : >"$out"; : >"$err"; : >"$wmsg"

  case "$mode" in
    split)    MARKER="$marker" SLEEP="$slp" bash "$victim" >"$out" 2>"$err" & ;;
    closed)   MARKER="$marker" SLEEP="$slp" bash "$victim" >"$out" 2>&-     & ;;
    deadpipe) MARKER="$marker" SLEEP="$slp" bash "$victim" >"$out" 2> >(exit 0) & ;;
    *) echo "FATAL: run_victim bad stderr-mode '$mode'" >&2; exit 1 ;;
  esac
  pid=$!
  if [[ -n "$sig" ]]; then
    sleep 0.3
    kill -s "$sig" "$pid" 2>/dev/null || true
  fi
  # `wait` on a job killed by a signal makes bash print "Terminated: 15" /
  # "Hangup: 1" — a job-status line derived from the kernel wait status. Capture
  # it (F4/F6 assert on it) instead of discarding it. LC_ALL=C so a localised
  # bash cannot silently change the wording.
  { LC_ALL=C wait "$pid" || rc=$?; } 2>"$wmsg"

  RUN_RC="$rc"
  RUN_PID="$pid"
  # Exact sentinel, not `wc -l` — see "COUNTING CLEANUPS" in the header.
  RUN_CLEANUPS="$(grep -c '^cleaned$' "$marker" || true)"
  RUN_OUT="$(cat "$out")"
  RUN_ERR="$(cat "$err")"
  RUN_WAITMSG="$(cat "$wmsg")"
}

expect_run() { # <label> <expected-rc> <expected-cleanups> <resumed:yes|no>
  local label="$1" want_rc="$2" want_cleanups="$3" want_resumed="$4"
  local got_resumed=no
  [[ "$RUN_OUT" == *RESUMED* ]] && got_resumed=yes
  [[ "$RUN_RC" == "$want_rc" ]] \
    && ok "$label: exit status $want_rc" \
    || fail_t "$label: exit status $RUN_RC (want $want_rc)"
  [[ "$RUN_CLEANUPS" == "$want_cleanups" ]] \
    && ok "$label: cleanup ran exactly $want_cleanups time(s)" \
    || fail_t "$label: cleanup ran $RUN_CLEANUPS time(s) (want $want_cleanups)"
  [[ "$got_resumed" == "$want_resumed" ]] \
    && ok "$label: resumed-past-interruption=$want_resumed" \
    || fail_t "$label: resumed-past-interruption=$got_resumed (want $want_resumed)"
}

# ── A. lib behaviour ──────────────────────────────────────────────────────────
section "A. lib behaviour"
bash -n "$LIB" && ok "A1 lib syntax" || fail_t "A1 lib syntax"

run_victim "$TMP/victim_lib.sh" TERM 2
expect_run "A2 SIGTERM" 143 1 no

run_victim "$TMP/victim_lib.sh" HUP 2
expect_run "A3 SIGHUP" 129 1 no

run_victim "$TMP/victim_lib.sh" "" 0
expect_run "A4 no signal" 0 1 yes

# ── B. wiring into ops/ios_test.sh ────────────────────────────────────────────
# The grep target is a DIFFERENT file, so the literals below cannot make these
# assertions tautological. Without this section, shipping the lib + test while
# skipping the production edit would still go fully green.
section "B. ops/ios_test.sh wiring"
IOS_TEST="$WORKSPACE/ops/ios_test.sh"
grep -qF 'source "$SCRIPT_DIR/lib/signal_traps.sh"' "$IOS_TEST" \
  && ok "B1 ios_test.sh sources the lib" || fail_t "B1 ios_test.sh does not source the lib"
# The optional trailing word is the diagnostic tag (kg_install_signal_traps
# <cleanup-fn> [tag]); the anchors still exclude comment lines and prose.
grep -qE '^[[:space:]]*kg_install_signal_traps cleanup([[:space:]]+[A-Za-z0-9_.-]+)?[[:space:]]*$' "$IOS_TEST" \
  && ok "B2 ios_test.sh installs the traps via the lib" \
  || fail_t "B2 ios_test.sh has no executable kg_install_signal_traps line"
grep -q 'trap cleanup EXIT INT TERM' "$IOS_TEST" \
  && fail_t "B3 ios_test.sh still arms the resume-after-signal trap shape" \
  || ok "B3 the resume-after-signal trap shape is gone"
bash -n "$IOS_TEST" && ok "B4 ios_test.sh syntax" || fail_t "B4 ios_test.sh syntax"

# ── B'. shared deploy callers use the same source-only library ────────────────
# This is deliberately structural: each caller gets its own cleanup function,
# sources the shared library, installs the traps, and has no resume-after-signal
# trap shape. Behavioural signal probes remain in the library fixture above and
# the real deploy seam is documented as a named manual check in the backlog.
section "B'. shared deploy caller wiring"
SIGNAL_LIB="$WORKSPACE/ops/lib/signal_traps.sh"
[[ -f "$SIGNAL_LIB" ]] && ok "B'1 shared signal library exists" \
  || fail_t "B'1 shared signal library is missing"
for script in "$WORKSPACE/ops/kg_reconcile.sh" "$WORKSPACE/devops.sh" "$WORKSPACE/ops/backup_verify.sh"; do
  name="${script#"$WORKSPACE/"}"
  bash -n "$script" && ok "B' syntax: $name" || fail_t "B' syntax: $name"
  grep -qE '^[^#]*lib/signal_traps\.sh' "$script" \
    && ok "B' source: $name" || fail_t "B' source missing: $name"
  fn="$(sed -n 's/^[[:space:]]*kg_install_signal_traps \([a-z_][a-z0-9_]*\).*/\1/p' "$script" | head -1)"
  if [[ -z "$fn" ]]; then
    fail_t "B' install missing: $name"
  elif grep -qE "^${fn}\(\)" "$script"; then
    ok "B' cleanup function is local: $name"
  else
    fail_t "B' cleanup function $fn is not defined in $name"
  fi
  if grep -qE '^[^#]*trap[^#]*EXIT INT TERM' "$script"; then
    fail_t "B' old EXIT INT TERM trap remains: $name"
  else
    ok "B' old trap shape absent: $name"
  fi
done

# ── C. this file is executable ────────────────────────────────────────────────
# `ops/tests/*.sh` are dispatched as `./ops/tests/<file>`; a 100644 file fails
# with rc=126 and a "Permission denied" that reads like an environment problem.
section "C. self-checks"
[[ -x "$0" ]] && ok "C1 test file has the exec bit" || fail_t "C1 test file is not executable"

# ── D. control: the fixture still discriminates ──────────────────────────────
# Same fixture, pre-fix trap shape. This is what the real ios_test.sh did under
# a real SIGTERM. If this goes green-shaped (rc=143 / 1 cleanup / no RESUMED),
# the fixture has stopped delivering signals and section A means nothing.
section "D. control (pre-fix trap shape must still misbehave)"
run_victim "$TMP/victim_oldshape.sh" TERM 2
expect_run "D1 old shape under SIGTERM" 0 2 yes

# ── E. hostile stderr: a failed diagnostic must not take the handler down ─────
# The handler's first act is to announce itself on fd 2. Under `set -e` — which
# ops/ios_test.sh sets and trap handlers inherit — an unguarded write that FAILS
# aborts the handler before `trap - EXIT` and the re-raise, so the process never
# dies with 128+N. Both conditions below are what an ssh drop to the standby
# build host actually leaves behind, and docs/sop/ios.md maps the resulting
# rc=1 to "test failure" — a diagnostic naming the wrong cause.
section "E. hostile stderr (fd 2 genuinely unwritable)"
run_victim "$TMP/victim_lib.sh" TERM 2 closed
expect_run "E1 SIGTERM, stderr closed (2>&-)" 143 1 no

run_victim "$TMP/victim_lib.sh" HUP 2 closed
expect_run "E2 SIGHUP, stderr closed (2>&-)" 129 1 no

run_victim "$TMP/victim_lib.sh" TERM 2 deadpipe
expect_run "E3 SIGTERM, stderr = pipe with no reader" 143 1 no

run_victim "$TMP/victim_lib.sh" HUP 2 deadpipe
expect_run "E4 SIGHUP, stderr = pipe with no reader" 129 1 no

# ── F. the diagnostic and the re-raise are real, not decorative ───────────────
section "F. diagnostic and re-raise"
run_victim "$TMP/victim_lib.sh" TERM 2
[[ "$RUN_ERR" == *"aborted by SIGTERM pid=$RUN_PID"* ]] \
  && ok "F1 handler announced SIGTERM on stderr, in the signalled process" \
  || fail_t "F1 no 'aborted by SIGTERM pid=$RUN_PID' on stderr (got: ${RUN_ERR:-<empty>})"
[[ "$RUN_OUT" != *"aborted by"* ]] \
  && ok "F2 the diagnostic stayed off stdout" \
  || fail_t "F2 the diagnostic leaked onto stdout (breaks --json)"
[[ "$RUN_WAITMSG" == *[Tt]erminated* ]] \
  && ok "F4 process was KILLED BY SIGTERM, not exit 143" \
  || fail_t "F4 no kernel signal-death evidence; an 'exit 143' fake would look identical in rc alone"

run_victim "$TMP/victim_lib.sh" HUP 2
# This — not A3 — is what pins `trap "kg_on_signal HUP" HUP` in the lib. Delete
# that trap and bash's implicit EXIT-on-fatal-signal still yields 129/cleanup×1,
# but it is silent, so this assertion goes red.
[[ "$RUN_ERR" == *"aborted by SIGHUP pid=$RUN_PID"* ]] \
  && ok "F3 explicit HUP handler ran (its diagnostic is the only producer)" \
  || fail_t "F3 no 'aborted by SIGHUP pid=$RUN_PID' on stderr (got: ${RUN_ERR:-<empty>})"
[[ "$RUN_WAITMSG" == *[Hh]angup* ]] \
  && ok "F6 process was KILLED BY SIGHUP, not exit 129" \
  || fail_t "F6 no kernel signal-death evidence for SIGHUP"

run_victim "$TMP/victim_tagged.sh" TERM 2
[[ "$RUN_ERR" == *"[kg_reconcile] aborted by SIGTERM"* ]] \
  && ok "F5 diagnostic tag is caller-supplied, so the lib is reusable" \
  || fail_t "F5 tag not honoured (got: ${RUN_ERR:-<empty>})"

# ── G. a cleanup that FAILS must not cost the re-raise ────────────────────────
# `[[ -n "$fn" ]] && "$fn"` makes the cleanup call the final command of an
# &&-list, which `set -e` does NOT exempt. A cleanup returning non-zero then
# aborts the handler and the process exits with the cleanup's status instead of
# 128+N — the same class of silent failure as section E.
section "G. failing cleanup"
run_victim "$TMP/victim_cleanupfails.sh" TERM 2
expect_run "G1 SIGTERM with cleanup returning 3" 143 1 no

run_victim "$TMP/victim_cleanupfails.sh" "" 0
expect_run "G2 clean run with cleanup returning 3" 0 1 yes

echo ""
echo "passed: $pass  failed: $fail"
[[ $fail -eq 0 ]]
