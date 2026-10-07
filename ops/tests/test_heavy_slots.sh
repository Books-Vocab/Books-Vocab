#!/usr/bin/env bash
# test_heavy_slots.sh — contract for ops/lib/heavy_slots.sh, the host-wide slot
# limiter that test_ops.sh applies to heavy groups. Every case runs against a
# private KG_HEAVY_SLOTS_DIR; the real host-wide directory is never touched.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="${KG_HEAVY_SLOTS_LIB_UNDER_TEST:-$ROOT/ops/lib/heavy_slots.sh}"
TMP="$(mktemp -d -t kg_heavy_slots_test_XXXXXX)"
HOLDER_PIDS=""
cleanup() {
  for p in $HOLDER_PIDS; do kill "$p" 2>/dev/null; wait "$p" 2>/dev/null; done
  rm -rf "$TMP"
}
trap cleanup EXIT
PASS=0; FAIL=0
ok(){ echo "  ✓ $*"; PASS=$((PASS+1)); }
bad(){ echo "  ✗ $*"; FAIL=$((FAIL+1)); }

export KG_HEAVY_SLOTS_POLL=0.2
export KG_HEAVY_SLOTS_NOTICE=1
unset KG_HEAVY_SLOT_HELD

# Worker: claims a slot for group "heavy" (or $2); the body records OVERLAP if
# another worker is inside at the same time (mkdir is the overlap detector).
WORKER="$TMP/worker.sh"
cat >"$WORKER" <<'W'
#!/usr/bin/env bash
set -u
source "$1"
HEAVY_TESTS=(heavy)
body() {
  if ! mkdir "$KG_TEST_INSIDE" 2>/dev/null; then echo OVERLAP >>"$KG_TEST_LOG"; return 1; fi
  sleep "${KG_TEST_HOLD:-1}"
  rmdir "$KG_TEST_INSIDE"
  echo DONE >>"$KG_TEST_LOG"
}
heavy_slots_run "${2:-heavy}" body
W
chmod +x "$WORKER"

run_pair() {  # $1=slots -> prints "rc1 rc2"; log in $TMP/log
  : >"$TMP/log"; rm -rf "$TMP/inside" "$TMP/slots"
  export KG_HEAVY_SLOTS_DIR="$TMP/slots" KG_HEAVY_SLOTS="$1" KG_TEST_INSIDE="$TMP/inside" KG_TEST_LOG="$TMP/log"
  "$WORKER" "$LIB" 2>/dev/null & p1=$!
  "$WORKER" "$LIB" 2>/dev/null & p2=$!
  wait "$p1"; r1=$?; wait "$p2"; r2=$?
  echo "$r1 $r2"
}

echo "── serialization"
out="$(run_pair 1)"
if [[ "$out" == "0 0" ]] && ! grep -q OVERLAP "$TMP/log" && [[ "$(grep -c DONE "$TMP/log")" == 2 ]]; then
  ok "KG_HEAVY_SLOTS=1 serializes two concurrent heavy groups"
else bad "KG_HEAVY_SLOTS=1 did not serialize (rc='$out' log=$(tr '\n' ' ' <"$TMP/log"))"; fi

out="$(run_pair 2)"
if grep -q OVERLAP "$TMP/log"; then
  ok "KG_HEAVY_SLOTS=2 lets both run at once (negative control: detector can fire)"
else bad "KG_HEAVY_SLOTS=2 did not overlap (rc='$out'); the serialization case proves nothing"; fi

echo "── stale holders"
export KG_HEAVY_SLOTS_DIR="$TMP/slots2" KG_HEAVY_SLOTS=1 KG_TEST_INSIDE="$TMP/inside2" KG_TEST_LOG="$TMP/log2"
: >"$TMP/log2"
mkdir -p "$KG_HEAVY_SLOTS_DIR/slot.1"
sleep 0 & deadpid=$!; wait "$deadpid"
printf '%s\n%s\n%s\n%s\n' "$deadpid" "" "heavy" "2000-01-01T00:00:00" >"$KG_HEAVY_SLOTS_DIR/slot.1/info"
if KG_TEST_HOLD=0 "$WORKER" "$LIB" 2>"$TMP/err" && grep -q "reclaiming stale" "$TMP/err" && grep -q DONE "$TMP/log2"; then
  ok "dead holder pid is reclaimed"
else bad "dead holder not reclaimed ($(tr '\n' ' ' <"$TMP/err"))"; fi

rm -rf "$KG_HEAVY_SLOTS_DIR"; mkdir -p "$KG_HEAVY_SLOTS_DIR/slot.1"
printf '%s\n%s\n%s\n%s\n' "$$" "Thu Jan  1 00:00:00 1970" "heavy" "2000-01-01T00:00:00" >"$KG_HEAVY_SLOTS_DIR/slot.1/info"
: >"$TMP/log2"
if KG_TEST_HOLD=0 "$WORKER" "$LIB" 2>"$TMP/err" && grep -q "reclaiming stale" "$TMP/err"; then
  ok "live pid with a different start time (pid reuse) is reclaimed"
else bad "pid-reuse holder not reclaimed ($(tr '\n' ' ' <"$TMP/err"))"; fi

echo "── stale reclaim race (ABA): N waiters on one dead holder, KG_HEAVY_SLOTS=1"
# Each waiter sleeps a staggered time between "holder is dead" and acting on it, so
# late waiters act on a verdict that the first reclaimer has already made obsolete.
# Without a reclaim mutex + re-validation, a late waiter renames the first
# reclaimer's LIVE slot away and runs concurrently with it (OVERLAP).
STALE_WORKER="$TMP/stale_worker.sh"
cat >"$STALE_WORKER" <<'W'
#!/usr/bin/env bash
set -u
source "$1"
HEAVY_TESTS=(heavy)
eval "$(declare -f _hs_stale | sed '1s/_hs_stale/_hs_stale_orig/')"
_hs_stale() { _hs_stale_orig "$@"; local r=$?; sleep "$KG_TEST_STALE_DELAY"; return $r; }
body() {
  if ! mkdir "$KG_TEST_INSIDE" 2>/dev/null; then echo OVERLAP >>"$KG_TEST_LOG"; return 1; fi
  sleep "${KG_TEST_HOLD:-1}"
  rmdir "$KG_TEST_INSIDE"
  echo DONE >>"$KG_TEST_LOG"
}
heavy_slots_run heavy body
W
chmod +x "$STALE_WORKER"
export KG_HEAVY_SLOTS_DIR="$TMP/slots3" KG_HEAVY_SLOTS=1 KG_TEST_INSIDE="$TMP/inside3" KG_TEST_LOG="$TMP/log3" KG_TEST_HOLD=1
: >"$TMP/log3"; rm -rf "$KG_HEAVY_SLOTS_DIR" "$TMP/inside3"; mkdir -p "$KG_HEAVY_SLOTS_DIR/slot.1"
sleep 0 & deadpid=$!; wait "$deadpid"
printf '%s\n%s\n%s\n%s\n' "$deadpid" "" "heavy" "2000-01-01T00:00:00" >"$KG_HEAVY_SLOTS_DIR/slot.1/info"
wpids=""
for d in 0 0.2 0.4 0.6; do
  KG_TEST_STALE_DELAY="$d" "$STALE_WORKER" "$LIB" 2>/dev/null & wpids="$wpids $!"
done
race_fail=0
for p in $wpids; do wait "$p" || race_fail=1; done
if [[ "$race_fail" == 0 ]] && ! grep -q OVERLAP "$TMP/log3" && [[ "$(grep -c DONE "$TMP/log3")" == 4 ]]; then
  ok "4 lockstep waiters on one dead slot never overlap and all complete"
else bad "stale-reclaim race: rc_fail=$race_fail log=$(tr '\n' ' ' <"$TMP/log3")"; fi
unset KG_TEST_HOLD

echo "── stale detection on GNU-style stat"
# GNU stat treats -f as filesystem status (junk, exit 0) and wants -c %Y for mtime.
# The grace-period branch (slot mkdir'd, info never written) must still age out.
REAL_STAT="$(command -v stat)"
mkdir -p "$TMP/gnubin"
cat >"$TMP/gnubin/stat" <<S
#!/usr/bin/env bash
if [[ "\$1" == -f ]]; then printf '  File: "x"\n    ID: 0 Namelen: 255\n'; exit 0; fi
if [[ "\$1" == -c ]]; then "$REAL_STAT" -c %Y "\$3" 2>/dev/null || "$REAL_STAT" -f %m "\$3"; exit \$?; fi
exec "$REAL_STAT" "\$@"
S
chmod +x "$TMP/gnubin/stat"
export KG_HEAVY_SLOTS_DIR="$TMP/slots4" KG_HEAVY_SLOTS=1 KG_TEST_INSIDE="$TMP/inside4" KG_TEST_LOG="$TMP/log4"
: >"$TMP/log4"; rm -rf "$KG_HEAVY_SLOTS_DIR"; mkdir -p "$KG_HEAVY_SLOTS_DIR/slot.1"
touch -t 200001010000 "$KG_HEAVY_SLOTS_DIR/slot.1"
if PATH="$TMP/gnubin:$PATH" KG_HEAVY_SLOTS_WAIT=5 KG_TEST_HOLD=0 "$WORKER" "$LIB" 2>"$TMP/err" && grep -q DONE "$TMP/log4"; then
  ok "info-less slot older than the grace period is reclaimed under GNU-style stat"
else bad "info-less slot not reclaimed under GNU-style stat ($(tr '\n' ' ' <"$TMP/err"))"; fi

echo "── bounded wait, holder report, bypasses"
rm -rf "$KG_HEAVY_SLOTS_DIR"; mkdir -p "$KG_HEAVY_SLOTS_DIR"
sleep 60 & holder=$!; HOLDER_PIDS="$HOLDER_PIDS $holder"
mkdir "$KG_HEAVY_SLOTS_DIR/slot.1"
lstart="$(ps -o lstart= -p "$holder" | sed 's/^ *//;s/ *$//')"
printf '%s\n%s\n%s\n%s\n' "$holder" "$lstart" "worktree" "2000-01-01T00:00:00" >"$KG_HEAVY_SLOTS_DIR/slot.1/info"
KG_HEAVY_SLOTS_WAIT=2 KG_TEST_HOLD=0 "$WORKER" "$LIB" 2>"$TMP/err"; rc=$?
if [[ "$rc" == 75 ]] && grep -q "pid=$holder group=worktree" "$TMP/err" && grep -q "gave up" "$TMP/err"; then
  ok "live holder: waiter names the holder, then gives up with rc=75 (no deadlock)"
else bad "bounded wait wrong rc=$rc err=$(tr '\n' ' ' <"$TMP/err")"; fi
if [[ -d "$KG_HEAVY_SLOTS_DIR/slot.1" ]]; then ok "live holder's slot left intact"; else bad "live holder's slot was stolen"; fi

: >"$KG_TEST_LOG"
if KG_TEST_HOLD=0 "$WORKER" "$LIB" other 2>/dev/null && grep -q DONE "$KG_TEST_LOG"; then
  ok "non-heavy group runs unthrottled while all slots are held"
else bad "non-heavy group was blocked"; fi

if KG_HEAVY_SLOTS=0 KG_TEST_HOLD=0 "$WORKER" "$LIB" 2>/dev/null; then
  ok "KG_HEAVY_SLOTS=0 disables the limiter"
else bad "KG_HEAVY_SLOTS=0 still blocked"; fi

if KG_HEAVY_SLOT_HELD=1 KG_TEST_HOLD=0 "$WORKER" "$LIB" 2>/dev/null; then
  ok "nested run under a held slot does not claim another (no self-deadlock)"
else bad "nested run blocked"; fi

echo "── wiring"
if grep -q 'heavy_slots_run "\$name" run_one "\$name"' "$ROOT/ops/test_ops.sh" \
   && grep -qE '^HEAVY_TESTS=\(' "$ROOT/ops/test_ops.sh"; then
  ok "test_ops.sh dispatcher routes through heavy_slots_run"
else bad "test_ops.sh dispatcher hook missing"; fi
list="$(awk '/^HEAVY_TESTS=\(/{f=1;next} f&&/^\)/{exit} f{print $1}' "$ROOT/ops/test_ops.sh" | tr '\n' ' ')"
if [[ "$list" == "worktree delivery-control docs-lint disk-guard doctor " ]]; then
  ok "heavy list is exactly the agreed five groups"
else bad "heavy list drifted: $list"; fi

echo "── dispatcher end to end (real ./ops/test_ops.sh, slot held by a live pid)"
# $KG_HEAVY_SLOTS_DIR/slot.1 is still held by the live `sleep` holder from above.
export KG_HEAVY_SLOTS=1
KG_HEAVY_SLOTS_WAIT=2 "$ROOT/ops/test_ops.sh" worktree >"$TMP/e2e.out" 2>"$TMP/e2e.err"; rc=$?
if [[ "$rc" == 75 ]] && grep -q "pid=$holder group=worktree" "$TMP/e2e.err" \
   && ! grep -q "worktree passed" "$TMP/e2e.out"; then
  ok "heavy group via test_ops.sh waits, names the holder, exits 75 without running"
else bad "dispatcher hook not effective rc=$rc err=$(tr '\n' ' ' <"$TMP/e2e.err" | cut -c1-300)"; fi
KG_HEAVY_SLOTS_WAIT=2 "$ROOT/ops/test_ops.sh" no-such-group >"$TMP/e2e2.out" 2>"$TMP/e2e2.err"; rc=$?
if [[ "$rc" == 1 ]] && grep -q "unknown test group: no-such-group" "$TMP/e2e2.err" \
   && ! grep -q "heavy-slots:" "$TMP/e2e2.err"; then
  ok "non-heavy group via test_ops.sh reaches run_one unthrottled"
else bad "non-heavy group was throttled or mis-routed rc=$rc err=$(tr '\n' ' ' <"$TMP/e2e2.err" | cut -c1-300)"; fi

echo ""
echo "heavy-slots: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
