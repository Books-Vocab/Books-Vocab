#!/usr/bin/env bash
# test_ci_apt_install.sh — ops/ci_apt_install.sh survives a slow apt mirror
# (issue #2167) without ever touching the real apt-get, sudo, timeout or sleep.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/ops/ci_apt_install.sh"

TMP="$(mktemp -d -t kg_ci_apt_install_XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

failures=0
pass() { printf '✓ %s\n' "$1"; }
fail() { printf '✗ %s\n' "$1" >&2; failures=$((failures + 1)); }

# Stubs record every call to one ordered log. apt-get install exits 137 (the
# SIGKILL signature from the issue) until FAKE_APT_OK_ON-th install call.
BIN="$TMP/bin"
mkdir -p "$BIN"
cat >"$BIN/sudo" <<'EOF'
#!/usr/bin/env bash
echo "sudo $*" >>"$FAKE_LOG"
exec "$@"
EOF
cat >"$BIN/timeout" <<'EOF'
#!/usr/bin/env bash
echo "timeout $*" >>"$FAKE_LOG"
while [[ "${1:-}" == -* ]]; do shift; done
shift # duration
exec "$@"
EOF
cat >"$BIN/sleep" <<'EOF'
#!/usr/bin/env bash
echo "sleep $*" >>"$FAKE_LOG"
EOF
cat >"$BIN/apt-get" <<'EOF'
#!/usr/bin/env bash
echo "apt-get $*" >>"$FAKE_LOG"
case " $* " in
  *" install "*)
    n=$(( $(cat "$FAKE_COUNTER" 2>/dev/null || echo 0) + 1 ))
    echo "$n" >"$FAKE_COUNTER"
    if (( n < ${FAKE_APT_OK_ON:-1} )); then exit 137; fi
    ;;
  *" update "*) [[ -z "${FAKE_UPDATE_FAILS:-}" ]] || exit 100 ;;
esac
exit 0
EOF
chmod +x "$BIN"/*

CASE=0
run_case() {
  # run_case <name> <FAKE_APT_OK_ON> [packages...]; sets rc, OUT, ERR, LOG
  CASE=$((CASE + 1))
  local name="$1" ok_on="$2"; shift 2
  export FAKE_LOG="$TMP/log.$CASE" FAKE_COUNTER="$TMP/count.$CASE"
  : >"$FAKE_LOG"
  rc=0
  PATH="$BIN:$PATH" FAKE_APT_OK_ON="$ok_on" \
    "$SCRIPT" "$@" >"$TMP/out.$CASE" 2>"$TMP/err.$CASE" || rc=$?
  OUT="$(cat "$TMP/out.$CASE")"
  ERR="$(cat "$TMP/err.$CASE")"
  LOG="$(cat "$FAKE_LOG")"
}

line_of() { { grep -En -- "$1" <<<"$LOG" || true; } | sed -n "${2}p" | cut -d: -f1; }
count_in_log() { grep -Ec -- "$1" <<<"$LOG" || true; }

[[ -x "$SCRIPT" ]] || { fail "ops/ci_apt_install.sh missing or not executable"; exit 1; }

# 1. nothing missing -> no apt/sudo/timeout call at all
run_case "no-packages" 1
if [[ "$rc" == 0 && -z "$LOG" ]]; then pass "no packages: exit 0 and zero apt/sudo/timeout calls"
else fail "no packages: rc=$rc log=[$LOG]"; fi

# 2. healthy mirror: one attempt, no update, no sleep
run_case "first-try" 1 ripgrep jq
if [[ "$rc" == 0 && "$(count_in_log '^apt-get .*install')" == 1 \
   && "$(count_in_log '^apt-get .*update')" == 0 && "$(count_in_log '^sleep')" == 0 ]]; then
  pass "first attempt success: one install, no update, no sleep"
else fail "first attempt success: rc=$rc log=[$LOG]"; fi

# 3. success on the 2nd attempt, with update + backoff in between
run_case "second-try" 2 ripgrep jq
install_n="$(count_in_log '^apt-get .*install')"
update_n="$(count_in_log '^apt-get .*update')"
sleep_n="$(count_in_log '^sleep')"
first_install_line="$(line_of '^apt-get .*install' 1)"
update_line="$(line_of '^apt-get .*update' 1)"
second_install_line="$(line_of '^apt-get .*install' 2)"
if [[ "$rc" == 0 && "$install_n" == 2 && "$update_n" == 1 && "$sleep_n" == 1 \
   && "$first_install_line" -lt "$update_line" && "$update_line" -lt "$second_install_line" ]]; then
  pass "second attempt success: install, backoff + update, install, exit 0"
else fail "second attempt success: rc=$rc install=$install_n update=$update_n sleep=$sleep_n log=[$LOG]"; fi

# 4. every attempt fails -> bounded attempts, non-zero, clear ::error:: with packages
run_case "all-fail" 99 ripgrep jq sqlite3
install_n="$(count_in_log '^apt-get .*install')"
update_n="$(count_in_log '^apt-get .*update')"
if [[ "$rc" != 0 && "$install_n" == 3 && "$update_n" == 2 ]]; then
  pass "all attempts fail: exactly 3 installs, 2 updates (none after the last), non-zero exit"
else fail "all attempts fail: rc=$rc install=$install_n update=$update_n log=[$LOG]"; fi
if grep -q '^::error::' <<<"$ERR$OUT" && grep -q 'ripgrep jq sqlite3' <<<"$ERR$OUT" \
   && grep -q '3 attempts' <<<"$ERR$OUT"; then
  pass "all attempts fail: ::error:: names the packages and the attempt count"
else fail "all attempts fail: missing clear ::error:: message; out=[$OUT] err=[$ERR]"; fi
if [[ "$rc" != 137 ]]; then pass "all attempts fail: exit is a deliberate status, not the bare 137"
else fail "all attempts fail: leaked bare 137"; fi

# 5. a failing apt-get update must not mask the retry
FAKE_UPDATE_FAILS=1 run_case "update-fails" 2 jq
if [[ "$rc" == 0 && "$(count_in_log '^apt-get .*install')" == 2 ]]; then
  pass "update failure between attempts is tolerated"
else fail "update failure between attempts aborted the retry loop: rc=$rc log=[$LOG]"; fi

# 6. every apt invocation is hard-bounded and uses Acquire::Retries
run_case "bounds" 99 jq
unbounded="$(grep -E '^sudo apt-get' <<<"$LOG" || true)"
if [[ -z "$unbounded" ]] \
   && [[ "$(count_in_log '^sudo timeout .*apt-get')" == 5 ]] \
   && ! grep -E '^sudo timeout' <<<"$LOG" | grep -Evq 'timeout (--[a-z-]+=[^ ]+ )+[0-9]+s apt-get'; then
  pass "every apt-get call runs under sudo timeout --kill-after and an explicit duration"
else fail "apt-get call without a hard timeout: log=[$LOG]"; fi
if [[ "$(count_in_log '^apt-get .*Acquire::Retries=3')" == 5 ]]; then
  pass "every apt-get call sets Acquire::Retries=3"
else fail "Acquire::Retries=3 missing on some apt-get call: log=[$LOG]"; fi

if (( failures > 0 )); then
  printf 'ci_apt_install: %d failure(s)\n' "$failures" >&2
  exit 1
fi
printf 'ci_apt_install: PASS\n'
