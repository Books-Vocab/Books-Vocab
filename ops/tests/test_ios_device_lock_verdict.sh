#!/usr/bin/env bash
# Offline contract test for the iOS lock timeout/infrastructure verdict.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../lib/ios_lock_wait.sh
source "$ROOT/ops/lib/ios_lock_wait.sh"
source "$ROOT/ops/lib/ios_test_failure_verdict.sh"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

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

grep -qF 'kg_ios_classify_test_execution' "$ROOT/ops/ios_test.sh" || \
  fail "ios_test.sh does not use the tested verdict classifier"

printf 'PASS: iOS lock timeout is typed infrastructure-unavailable\n'
