#!/usr/bin/env bash
# test_ios_signal_traps.sh — signal-abort semantics for ops/lib/ios_signal_traps.sh,
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
# A2 is the load-bearing assertion, not A3. Measured on bash 3.2.57/darwin: a
# bare `trap cleanup EXIT` already dies 129 with cleanup once under SIGHUP, so
# A3 passes even against the pre-fix shape — only the TERM case discriminates.
# A3 pins the explicit HUP handler in place; it does not prove the fix.
#
# Section D is a live control: it runs the OLD trap shape through the SAME
# fixture and requires it to still show rc=0 / cleanup twice / RESUMED. If the
# fixture ever stops delivering signals (CI timing, a bash change), D goes red
# instead of A silently going green for the wrong reason.
#
# Deliberately NOT tested: SIGINT. A background child of a non-interactive shell
# has SIGINT set to SIG_IGN, so the harness cannot deliver it; the victim just
# finishes normally and the case would be green for the wrong reason. The lib
# still installs an INT handler for interactive/foreground use.
#
# NOT REGISTERED YET: `ops/test_ops.sh` and `ops/tests/test_ops_ci_coverage.sh`
# are owned by another change this round, so this file has no `ios-signal-traps`
# group yet. Run it directly (`./ops/tests/test_ios_signal_traps.sh`) until the
# group is wired up.
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$WORKSPACE/ops/lib/ios_signal_traps.sh"

pass=0; fail=0
ok()     { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

[[ -f "$LIB" ]] || { echo "FATAL: $LIB missing"; exit 1; }

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# ── fixture ───────────────────────────────────────────────────────────────────
# Two victims with IDENTICAL bodies, differing only in how the traps are armed:
# the lib under test vs. the pre-fix shape. Both append to $MARKER from cleanup
# and print RESUMED only if execution survives the interruption point.
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

# run_victim <victim-file> <signal|""> <sleep-seconds>
# Sets RUN_RC / RUN_CLEANUPS / RUN_OUT.
# bash defers a trapped signal until the foreground child (here `sleep`)
# returns, so each signal case costs ≈SLEEP seconds; 2s is enough.
run_victim() {
  local victim="$1" sig="$2" slp="$3"
  local tag marker out pid rc=0
  tag="$(date +%s)-$$-${RANDOM}"
  marker="$TMP/marker.$tag"; out="$TMP/out.$tag"
  : >"$marker"; : >"$out"

  MARKER="$marker" SLEEP="$slp" bash "$victim" >"$out" 2>&1 &
  pid=$!
  if [[ -n "$sig" ]]; then
    sleep 0.3
    kill -s "$sig" "$pid" 2>/dev/null || true
  fi
  # `wait` on a signalled job makes bash print "Terminated: 15" / "Hangup: 1" to
  # stderr. Cosmetic; drop it so the report stays readable.
  { wait "$pid" || rc=$?; } 2>/dev/null

  RUN_RC="$rc"
  RUN_CLEANUPS="$(wc -l <"$marker" | tr -d ' ')"
  RUN_OUT="$(cat "$out")"
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
grep -qF 'source "$SCRIPT_DIR/lib/ios_signal_traps.sh"' "$IOS_TEST" \
  && ok "B1 ios_test.sh sources the lib" || fail_t "B1 ios_test.sh does not source the lib"
grep -qE '^[[:space:]]*kg_install_signal_traps cleanup[[:space:]]*$' "$IOS_TEST" \
  && ok "B2 ios_test.sh installs the traps via the lib" \
  || fail_t "B2 ios_test.sh has no executable kg_install_signal_traps line"
grep -q 'trap cleanup EXIT INT TERM' "$IOS_TEST" \
  && fail_t "B3 ios_test.sh still arms the resume-after-signal trap shape" \
  || ok "B3 the resume-after-signal trap shape is gone"
bash -n "$IOS_TEST" && ok "B4 ios_test.sh syntax" || fail_t "B4 ios_test.sh syntax"

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

echo ""
echo "passed: $pass  failed: $fail"
[[ $fail -eq 0 ]]
