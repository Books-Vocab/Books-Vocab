#!/usr/bin/env bash
# Offline contract test for the iOS lock timeout/infrastructure verdict.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../lib/ios_lock_wait.sh
source "$ROOT/ops/lib/ios_lock_wait.sh"
source "$ROOT/ops/lib/ios_test_failure_verdict.sh"

# FIFO ticket queue and owner-guarded cleanup are offline contracts.  The
# fixture below replaces macOS shlock so the ordering/race rules are testable
# without starting Xcode or touching a real simulator.

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

for script_name in ios_build.sh ios_test.sh ios_release.sh; do
  grep -qF 'kg_ios_release_shlock_if_owner' "$ROOT/ops/$script_name" || \
    fail "${script_name} does not use owner-guarded lock cleanup"
done

run_timeout_probe() {
  local holder_pid="$1" selector="$2" output rc
  set +e
  output="$({
    KG_IOS_LOCK_HOLDER_PID="$holder_pid"
    KG_IOS_LOCK_WAIT_SECONDS=17
    kg_ios_lock_timeout_die "[probe]" device "$selector" 600
  } 2>&1)"
  rc=$?
  set -e
  printf '%s\n' "$output"
  [[ "$rc" -eq 75 ]] || fail "timeout helper returned rc=$rc, expected 75"
  grep -qF "holderPid=$holder_pid" <<<"$output" || fail "holder pid missing: $output"
  grep -qF "selector=\"$selector\"" <<<"$output" || fail "selector missing: $output"
}

queue_ticket_count() {
  local queue_dir="$1"
  { find "$queue_dir" -maxdepth 1 -type f -name 'ticket-*' -print 2>/dev/null || true; } \
    | wc -l | tr -d ' '
}

wait_for_ticket_count() {
  local queue_dir="$1" expected="$2" count
  for _ in $(seq 1 100); do
    count="$(queue_ticket_count "$queue_dir")"
    if (( count >= expected )); then
      return 0
    fi
    sleep 0.1
  done
  fail "timed out waiting for ${expected} FIFO ticket(s); saw ${count:-0}"
}

test_fifo_ticket_queue_and_abandoned_waiter() {
  local fixture fake_bin waiter lock events queue_dir
  local holder_pid holder_pid_2 first_waiter second_waiter
  fixture="$(mktemp -d "${TMPDIR:-/tmp}/kg-ios-lock-fixture.XXXXXX")"
  fake_bin="$fixture/bin"
  waiter="$fixture/waiter.sh"
  lock="$fixture/shared.lock"
  events="$fixture/events.log"
  queue_dir="${lock}.queue"
  mkdir -p "$fake_bin"

  cat >"$fake_bin/shlock" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
lock_file=""
owner_pid=""
while (($#)); do
  case "$1" in
    -f) lock_file="$2"; shift 2 ;;
    -p) owner_pid="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "$lock_file" && -n "$owner_pid" ]]
if [[ -d "${lock_file}.claim" ]]; then
  exit 1
fi
if [[ -f "$lock_file" ]]; then
  held_pid="$(cat "$lock_file" 2>/dev/null || true)"
  if [[ "$held_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$held_pid" 2>/dev/null; then
    rm -f "$lock_file"
  else
    exit 1
  fi
fi
if mkdir "${lock_file}.claim" 2>/dev/null; then
  printf '%s\n' "$owner_pid" >"$lock_file"
  rmdir "${lock_file}.claim"
  exit 0
fi
exit 1
EOF
  chmod +x "$fake_bin/shlock"

  cat >"$waiter" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
lib_dir="$1"
lock_file="$2"
events_file="$3"
label="$4"
timeout="${5:-20}"
source "$lib_dir/ios_lock_wait.sh"
if kg_ios_wait_for_shlock "[fixture]" "$label" "$lock_file" "$$" "$timeout" 1 post-sleep; then
  printf '%s\n' "$label" >>"$events_file"
  sleep 0.1
  kg_ios_release_shlock_if_owner "$lock_file" "$$"
else
  exit 1
fi
EOF
  chmod +x "$waiter"

  sleep 30 &
  holder_pid=$!
  printf '%s\n' "$holder_pid" >"$lock"
  PATH="$fake_bin:$PATH" "$waiter" "$ROOT/ops/lib" "$lock" "$events" A &
  first_waiter=$!
  wait_for_ticket_count "$queue_dir" 1
  PATH="$fake_bin:$PATH" "$waiter" "$ROOT/ops/lib" "$lock" "$events" B &
  second_waiter=$!
  wait_for_ticket_count "$queue_dir" 2
  kill "$holder_pid" 2>/dev/null || true
  wait "$holder_pid" 2>/dev/null || true
  wait "$first_waiter"
  wait "$second_waiter"
  [[ "$(tr '\n' ' ' <"$events")" == "A B " ]] || \
    fail "FIFO acquisition order drifted: $(tr '\n' ' ' <"$events")"

  lock="$fixture/timeout.lock"
  queue_dir="${lock}.queue"
  sleep 30 &
  holder_pid_2=$!
  printf '%s\n' "$holder_pid_2" >"$lock"
  PATH="$fake_bin:$PATH" "$waiter" "$ROOT/ops/lib" "$lock" "$events" timeout 1 &
  first_waiter=$!
  wait_for_ticket_count "$queue_dir" 1
  wait "$first_waiter" 2>/dev/null && fail "timeout waiter unexpectedly acquired lock" || true
  [[ "$(queue_ticket_count "$queue_dir")" == "0" ]] || \
    fail "timeout waiter left a FIFO ticket behind"
  kill "$holder_pid_2" 2>/dev/null || true
  wait "$holder_pid_2" 2>/dev/null || true

  lock="$fixture/abandoned.lock"
  queue_dir="${lock}.queue"
  sleep 30 &
  holder_pid_2=$!
  printf '%s\n' "$holder_pid_2" >"$lock"
  PATH="$fake_bin:$PATH" "$waiter" "$ROOT/ops/lib" "$lock" "$events" abandoned &
  first_waiter=$!
  wait_for_ticket_count "$queue_dir" 1
  kill "$first_waiter" 2>/dev/null || true
  wait "$first_waiter" 2>/dev/null || true
  [[ "$(queue_ticket_count "$queue_dir")" == "0" ]] || \
    fail "signal-aborted waiter left a FIFO ticket behind"
  PATH="$fake_bin:$PATH" "$waiter" "$ROOT/ops/lib" "$lock" "$events" survivor &
  second_waiter=$!
  wait_for_ticket_count "$queue_dir" 1
  kill "$holder_pid_2" 2>/dev/null || true
  wait "$holder_pid_2" 2>/dev/null || true
  wait "$second_waiter"
  grep -qF 'survivor' "$events" || fail "survivor did not pass an abandoned waiter"

  lock="$fixture/owner-guard.lock"
  sleep 30 &
  holder_pid_2=$!
  printf '%s\n' "$holder_pid_2" >"$lock"
  kg_ios_release_shlock_if_owner "$lock" "$$"
  [[ "$(cat "$lock")" == "$holder_pid_2" ]] || fail "non-owner removed a live lock"
  kg_ios_release_shlock_if_owner "$lock" "$holder_pid_2"
  [[ ! -e "$lock" ]] || fail "owner cleanup did not release its lock"
  kill "$holder_pid_2" 2>/dev/null || true
  wait "$holder_pid_2" 2>/dev/null || true
  rm -rf "$fixture"
}

live_output="$(run_timeout_probe "$$" "iPhone 17 Pro Max")"
grep -qF 'holderCmd=' <<<"$live_output" || fail "live holder command missing: $live_output"

dead_output="$(run_timeout_probe 99999999 "dead-device")"
grep -qF 'holderCmd=unknown' <<<"$dead_output" || fail "dead holder was not named unknown: $dead_output"

for function_name in acquire_build_lock acquire_test_device_lock; do
  body="$(sed -n "/^${function_name}() {/,/^}/p" "$ROOT/ops/ios_test.sh")"
  [[ -n "$body" ]] || fail "could not extract $function_name"
  grep -qF 'kg_ios_lock_timeout_die' <<<"$body" || \
    fail "$function_name does not use the infrastructure timeout helper"
  ! grep -qF 'exit 1' <<<"$body" || \
    fail "$function_name still has a bare exit 1 timeout path"
done

for script_name in ios_build.sh ios_release.sh; do
  timeout_body="$(sed -n '/^if ! kg_ios_wait_for_shlock/,/^fi/p' "$ROOT/ops/$script_name")"
  [[ -n "$timeout_body" ]] || fail "could not extract $script_name timeout path"
  grep -qF 'kg_ios_lock_timeout_die' <<<"$timeout_body" || \
    fail "$script_name timeout path does not use the infrastructure helper"
  ! grep -qF 'exit 1' <<<"$timeout_body" || \
    fail "$script_name still has a bare exit 1 timeout path"
done

run_verdict_case() {
  local name="$1" exit_code="$2" log_contents="$3" expected="$4" log_path actual
  log_path="$(mktemp "${TMPDIR:-/tmp}/kg-ios-verdict.XXXXXX")"
  printf '%s\n' "$log_contents" >"$log_path"
  actual="$(kg_ios_classify_test_execution "$exit_code" "$log_path")"
  rm -f "$log_path"
  [[ "$actual" == "$expected" ]] || \
    fail "$name: expected '$expected', got '$actual'"
}

run_verdict_case \
  "test failure wins over intentional keychain OSStatus" \
  65 $'Keychain save failed: OSStatus -25291\n** TEST EXECUTE FAILED **' \
  'fail|1|tests-failed'
run_verdict_case \
  "short test failure marker remains a test failure" \
  65 $'Keychain save failed: OSStatus -25291\n** TEST FAILED **' \
  'fail|1|tests-failed'
run_verdict_case \
  "keychain-only failure is infrastructure-unavailable" \
  65 $'Keychain save failed: OSStatus -25291' \
  'inconclusive|75|keychain-unavailable-osstatus-25291'

run_verdict_case \
  "service-hub startup failure is infrastructure-unavailable" \
  1 $'DTServiceHubClient failed to bless service hub\nunable to connect to com.apple.instruments.deviceservice.lockdown' \
  'inconclusive|75|test-runner-startup-unavailable'
run_verdict_case \
  "test failure still wins over service-hub startup text" \
  65 $'DTServiceHubClient failed to bless service hub\n** TEST EXECUTE FAILED **' \
  'fail|1|tests-failed'
run_verdict_case \
  "unrelated xcode failure remains passthrough" \
  65 'xcodebuild: an unrelated compiler error' \
  'passthrough|65|'

grep -qF 'kg_ios_classify_test_execution' "$ROOT/ops/ios_test.sh" || \
  fail "ios_test.sh does not use the tested verdict classifier"
grep -qF 'kg_ios_test_runner_startup_unavailable "$TMPOUT"' "$ROOT/ops/ios_test.sh" || \
  fail "ios_test.sh does not stop on known runner startup failure"

test_fifo_ticket_queue_and_abandoned_waiter

printf 'PASS: iOS lock timeout is typed infrastructure-unavailable\n'
