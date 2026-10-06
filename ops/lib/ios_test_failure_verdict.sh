#!/usr/bin/env bash
# Shared, sourceable classification for the final ios_test.sh log verdict.
# Keep this pure so offline tests can exercise the exact production predicate.

kg_ios_test_keychain_unavailable() {
  local log_path="$1"
  grep -qF -- '-25291' "$log_path" 2>/dev/null
}

kg_ios_test_execution_failed() {
  local log_path="$1"
  grep -qE '^\*\* TEST( EXECUTE)? FAILED' "$log_path" 2>/dev/null
}

kg_ios_test_runner_startup_unavailable() {
  local log_path="$1"
  # These simulator service errors happen before XCTest can execute a test;
  # classify them as infrastructure evidence so callers do not charge the
  # product with a test failure or wait for the full XCTest allowance.
  grep -qE 'DTServiceHubClient failed to bless service hub|unable to connect to com\.apple\.instruments\.deviceservice\.lockdown' "$log_path" 2>/dev/null
}

# Print: <verdict>|<exit-code>|<reason>
# The passthrough result is used for all other xcodebuild outcomes.
kg_ios_classify_test_execution() {
  local exit_code="$1" log_path="$2"
  local infra_exit="${KG_IOS_EXIT_INFRA_UNAVAILABLE:-75}"

  if kg_ios_test_execution_failed "$log_path"; then
    printf 'fail|1|tests-failed\n'
  elif [[ "$exit_code" -ne 0 ]] && kg_ios_test_runner_startup_unavailable "$log_path"; then
    printf 'inconclusive|%s|test-runner-startup-unavailable\n' "$infra_exit"
  elif [[ "$exit_code" -ne 0 ]] && kg_ios_test_keychain_unavailable "$log_path"; then
    printf 'inconclusive|%s|keychain-unavailable-osstatus-25291\n' "$infra_exit"
  else
    printf 'passthrough|%s|\n' "$exit_code"
  fi
}
