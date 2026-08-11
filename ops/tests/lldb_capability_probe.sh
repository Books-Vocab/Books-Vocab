#!/usr/bin/env bash
# Bounded capability probe for the real lldb-forensics runtime.
#
# Exit status is deliberately not a test verdict:
#   0 = lldb can launch and run the probe inferior
#   2 = unavailable/denied/timeout (the coverage gate must declare a skip)
#   1 = probe implementation/tool execution failure
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../lib/review_probe_lib.sh
. "$REPO/ops/lib/review_probe_lib.sh"

TIMEOUT="${KG_LLDB_CAPABILITY_TIMEOUT:-10}"
XCRUN="${KG_XCRUN_BIN:-xcrun}"
TARGET="${KG_LLDB_CAPABILITY_TARGET:-/usr/bin/false}"
LOG="${KG_LLDB_CAPABILITY_LOG:-${TMPDIR:-/tmp}/kg-lldb-capability.$$.log}"

if ! command -v "$XCRUN" >/dev/null 2>&1; then
  printf 'lldb-capability status=unavailable reason=missing-xcrun log=%s\n' "$LOG" >&2
  exit 2
fi
if [[ ! -x "$TARGET" ]]; then
  printf 'lldb-capability status=unavailable reason=missing-target target=%s log=%s\n' "$TARGET" "$LOG" >&2
  exit 2
fi

"$XCRUN" lldb -b -k quit "$TARGET" -o run >"$LOG" 2>&1 </dev/null &
pid=$!
kg_probe_wait_pid "$pid" "$TIMEOUT" "lldb-capability"
wait_rc=$?

if [[ "$wait_rc" -eq 3 ]]; then
  printf 'lldb-capability status=timeout reason=probe-timeout timeout=%ss log=%s\n' "$TIMEOUT" "$LOG" >&2
  exit 2
fi

if grep -Eiq 'attach failed|not allowed to attach|not permitted to attach|permission denied' "$LOG"; then
  printf 'lldb-capability status=denied reason=attach-policy rc=%s log=%s\n' "$wait_rc" "$LOG" >&2
  exit 2
fi

if [[ "$wait_rc" -ne 0 ]]; then
  printf 'lldb-capability status=unavailable reason=lldb-exit rc=%s log=%s\n' "$wait_rc" "$LOG" >&2
  exit 2
fi

printf 'lldb-capability status=ready reason=attach-and-run log=%s\n' "$LOG"
exit 0
