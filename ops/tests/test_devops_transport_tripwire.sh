#!/usr/bin/env bash
# test_devops_transport_tripwire.sh — devops.sh refuses the REAL transport under KG_OPS_TEST=1.
#
# The last seal after the PATH shim (ops/lib/hermetic_ops_test.sh) and the stub base
# (ops/test_devops.sh): even if a test unsets the seams or runs with a PATH that has no
# shim, devops.sh itself exits 97 before it can run ssh / scp / rsync / curl against the
# production host (P0 2026-10-09, docs/runbook/incidents/2026-10-09-kg-data-deleted-by-test.md).
#
# Everything here is local.  The "real transport" is simulated by an executable file named
# ssh/rsync with NO shebang: the tripwire classifies it as a real binary and must exit 97
# before exec; without the tripwire, bash would try to run it and fail with a different
# status, so the assertion cannot pass by accident.  KG_SERVER points at .invalid.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEVOPS="$ROOT/devops.sh"
# shellcheck source=../lib/hermetic_ops_test.sh
source "$ROOT/ops/lib/hermetic_ops_test.sh"
hermetic_ops_test_init "$ROOT"

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
no() { echo "  ✗ $*"; fail=$((fail+1)); }

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/fakereal" "$T/scriptbin"
export KG_SERVER="kg-test@invalid.invalid"
export KG_OPS_TEST_TRIPWIRE_LOG="$T/tripwire.log"

# A "real" binary stand-in: executable, no `#!` header.
for tool in ssh scp rsync curl; do
  printf 'NOT-A-SCRIPT\n' > "$T/fakereal/$tool"; chmod +x "$T/fakereal/$tool"
done
# A test-owned fake: a script (what every legitimate test stub is).
cat > "$T/scriptbin/ssh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STUB_TRACE"
exit 0
STUB
chmod +x "$T/scriptbin/ssh"
export STUB_TRACE="$T/stub.trace"

# run_devops <env assignments...> -- <devops args...>  → run_rc, run_out
run_devops() {
  # `env` wants all -u options before the NAME=value assignments (BSD env).
  local -a unsets=() sets=()
  while [[ "$1" != "--" ]]; do
    if [[ "$1" == "-u" ]]; then unsets+=(-u "$2"); shift 2; else sets+=("$1"); shift; fi
  done
  shift
  : > "$KG_OPS_TEST_TRIPWIRE_LOG"; : > "$STUB_TRACE"
  run_rc=0
  run_out="$(env ${unsets[@]+"${unsets[@]}"} ${sets[@]+"${sets[@]}"} bash "$DEVOPS" "$@" 2>&1)" || run_rc=$?
}
expect_tripwire() {  # <label> <substring expected in the log line>
  if [[ "$run_rc" -eq 97 ]] && grep -q 'FORBIDDEN (exit 97)' <<<"$run_out" && grep -q "$2" "$KG_OPS_TEST_TRIPWIRE_LOG"; then
    ok "tripwire fires: $1"
  else
    no "tripwire did NOT fire: $1 (rc=$run_rc out=$(tr '\n' ' ' <<<"$run_out"))"
  fi
}

# container-run probes the container through `run_remote … | grep -q true`: the tripwire exits
# 97 inside that pipeline subshell, so the visible status becomes the caller's own error (1).
# The refusal itself (message + log line + nothing executed) is what must hold there.
expect_refused_in_subshell() {  # <label> <log substring>
  if [[ "$run_rc" -ne 0 ]] && grep -q 'FORBIDDEN (exit 97)' <<<"$run_out" && grep -q "$2" "$KG_OPS_TEST_TRIPWIRE_LOG"; then
    ok "tripwire fires (status swallowed by a pipeline subshell, refusal loud + logged): $1"
  else
    no "tripwire did NOT fire: $1 (rc=$run_rc out=$(tr '\n' ' ' <<<"$run_out"))"
  fi
}

echo "── KG_OPS_TEST=1: real transports are refused (exit 97) ──"
# 1. ssh seam unset — the exact shape of the incident (no stub transport).
run_devops KG_OPS_TEST=1 -u KG_SSH_CMD -- run "echo hi"
expect_tripwire "run with KG_SSH_CMD unset" 'tripwire ssh seam=<unset>'
[[ ! -s "$STUB_TRACE" ]] && ok "nothing executed after the tripwire" || no "something ran after the tripwire"
# 2. ssh seam names the real ssh binary.
run_devops KG_OPS_TEST=1 "KG_SSH_CMD=$T/fakereal/ssh -T -o BatchMode=yes" -- run "echo hi"
expect_tripwire "KG_SSH_CMD names a real ssh binary" "tripwire ssh seam=$T/fakereal/ssh"
# 2b. wrappers must not hide the real binary from the classifier (#2922): env / sh -c / bash -c.
run_devops KG_OPS_TEST=1 "KG_SSH_CMD=env $T/fakereal/ssh -T host" -- run "echo hi"
expect_tripwire "KG_SSH_CMD=env <real ssh>" "tripwire ssh seam=env $T/fakereal/ssh"
run_devops KG_OPS_TEST=1 "KG_SSH_CMD=/usr/bin/env -u FOO BAR=1 $T/fakereal/ssh host" -- run "echo hi"
expect_tripwire "KG_SSH_CMD=/usr/bin/env -u FOO BAR=1 <real ssh>" "tripwire ssh seam=/usr/bin/env"
run_devops KG_OPS_TEST=1 "KG_SSH_CMD=sh -c $T/fakereal/ssh" -- run "echo hi"
expect_tripwire "KG_SSH_CMD=sh -c <real ssh>" "tripwire ssh seam=sh -c"
run_devops KG_OPS_TEST=1 "KG_SSH_CMD=bash -lc $T/fakereal/ssh" -- run "echo hi"
expect_tripwire "KG_SSH_CMD=bash -lc <real ssh>" "tripwire ssh seam=bash -lc"
run_devops KG_OPS_TEST=1 "KG_SSH_CMD=env nohup $T/fakereal/ssh host" -- run "echo hi"
expect_tripwire "KG_SSH_CMD=env nohup <real ssh>" "tripwire ssh seam=env nohup"
run_devops KG_OPS_TEST=1 "KG_SSH_CMD=env FOO=1 $T/scriptbin/ssh stubhost" -- run "echo hi"
if [[ "$run_rc" -eq 0 ]] && grep -qx 'stubhost echo hi' "$STUB_TRACE"; then
  ok "env-wrapped script stub is still allowed (positive control for the unwrapping)"
else
  no "env-wrapped script stub refused (rc=$run_rc out=$run_out)"
fi
# 2c. the refusal text must not advise a fix that cannot work: with the seam unset the tripwire
# always fires, so "put a fake ssh earlier in PATH" is wrong advice.
run_devops KG_OPS_TEST=1 -u KG_SSH_CMD -- run "echo hi"
if grep -q 'KG_SSH_CMD' <<<"$run_out" && ! grep -qi 'earlier in PATH' <<<"$run_out"; then
  ok "refusal message points at the seam and does not advise a PATH-only fake"
else
  no "refusal message advises something that does not work: $(tr '\n' ' ' <<<"$run_out")"
fi
# 3. the tripwire is reached through the other remote surfaces too.
run_devops KG_OPS_TEST=1 -u KG_SSH_CMD -- container-run "ls"
expect_refused_in_subshell "container-run" 'tripwire ssh'
run_devops KG_OPS_TEST=1 -u KG_SSH_CMD -- status
expect_tripwire "status" 'tripwire ssh'
run_devops KG_OPS_TEST=1 -u KG_SSH_CMD -- ssh
expect_tripwire "interactive ssh command" 'tripwire ssh seam=<unset>'
# 4. scp: push-env with no scp seam.
printf 'K=v\n' > "$T/env.file"
run_devops KG_OPS_TEST=1 -u KG_SCP_CMD -- push-env "$T/env.file"
expect_tripwire "push-env with KG_SCP_CMD unset" 'tripwire scp seam=<unset>'
# 5. rsync: backup with a real-looking rsync first in PATH.
run_devops KG_OPS_TEST=1 "PATH=$T/fakereal:$PATH" "BACKUP_DIR=$T/backups" -- backup
expect_tripwire "backup with a real rsync on PATH" "tripwire rsync seam=rsync"
# 6. curl smoke: verify_post_deploy with a real curl.
rc=0
out="$(env KG_OPS_TEST=1 "PATH=$T/fakereal:$PATH" KG_SSH_CMD=/usr/bin/true DEVOPS_SOURCE_ONLY=1 \
  bash -c 'source "$1"; verify_post_deploy 0123456789abcdef0123456789abcdef01234567' _ "$DEVOPS" 2>&1)" || rc=$?
[[ "$rc" -eq 97 ]] && grep -q 'FORBIDDEN (exit 97)' <<<"$out" \
  && ok "tripwire fires: post-deploy smoke with a real curl" \
  || no "smoke curl tripwire: rc=$rc out=$out"

echo "── harmless seams still work under KG_OPS_TEST=1 ──"
# /usr/bin/true is not a transport; a script stub named ssh is a test-owned fake.
run_devops KG_OPS_TEST=1 KG_SSH_CMD=/usr/bin/true -- run "echo hi"
[[ "$run_rc" -eq 0 ]] && ok "KG_SSH_CMD=/usr/bin/true is allowed" || no "KG_SSH_CMD=/usr/bin/true refused (rc=$run_rc: $run_out)"
run_devops KG_OPS_TEST=1 "KG_SSH_CMD=$T/scriptbin/ssh stubhost" -- run "echo hi"
if [[ "$run_rc" -eq 0 ]] && grep -qx 'stubhost echo hi' "$STUB_TRACE"; then
  ok "a script stub named ssh is allowed and receives the remote command"
else
  no "script stub refused or not called (rc=$run_rc trace=$(cat "$STUB_TRACE"))"
fi
# With the PATH shim in front, an unset seam never reaches anything either: tripwire first.
run_devops KG_OPS_TEST=1 -u KG_SSH_CMD "PATH=$KG_OPS_SHIM_DIR:$PATH" -- run "echo hi"
expect_tripwire "shim on PATH + seam unset (tripwire wins over the shim)" 'tripwire ssh seam=<unset>'

echo "── KG_OPS_TEST unset: normal operator behavior is unchanged ──"
# No tripwire: devops.sh builds the real ssh argv and execs `ssh` from PATH.  Here PATH
# resolves `ssh` to a recording script, so nothing leaves the machine.
run_devops -u KG_OPS_TEST -u KG_SSH_CMD "PATH=$T/scriptbin:/usr/bin:/bin" -- run "echo hi"
if [[ "$run_rc" -eq 0 ]] \
   && grep -qx -- "-T -o StrictHostKeyChecking=accept-new -o BatchMode=yes kg-test@invalid.invalid echo hi" "$STUB_TRACE"; then
  ok "without KG_OPS_TEST the real ssh argv is built and executed (no tripwire)"
else
  no "operator path changed (rc=$run_rc trace=$(cat "$STUB_TRACE") out=$run_out)"
fi
[[ ! -s "$KG_OPS_TEST_TRIPWIRE_LOG" ]] && ok "tripwire log stays empty when KG_OPS_TEST is unset" || no "tripwire fired without KG_OPS_TEST"
run_devops KG_OPS_TEST=0 -u KG_SSH_CMD "PATH=$T/scriptbin:/usr/bin:/bin" -- run "echo hi"
[[ "$run_rc" -eq 0 ]] && ok "KG_OPS_TEST=0 is not the tripwire switch" || no "KG_OPS_TEST=0 triggered the tripwire (rc=$run_rc)"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ "$fail" -eq 0 ]]
