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

# Print: <verdict>|<exit-code>|<reason>
# The passthrough result is used for all other xcodebuild outcomes.
kg_ios_classify_test_execution() {
  local exit_code="$1" log_path="$2"
  local infra_exit="${KG_IOS_EXIT_INFRA_UNAVAILABLE:-75}"

  if [[ "$exit_code" -ne 0 ]] && kg_ios_test_keychain_unavailable "$log_path" \
    && ! kg_ios_test_execution_failed "$log_path"; then
    printf 'inconclusive|%s|keychain-unavailable-osstatus-25291\n' "$infra_exit"
  elif kg_ios_test_execution_failed "$log_path"; then
    printf 'fail|1|tests-failed\n'
  else
    printf 'passthrough|%s|\n' "$exit_code"
  fi
}
