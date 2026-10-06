#!/usr/bin/env bash
# Keep the GitHub Actions ops-suite classification total and unambiguous.
#
# The test dispatcher is the source of truth for available groups. This file only
# answers which groups can run on the Linux Actions runner; it is not a second test
# router and it does not describe product work.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

LINUX_GROUPS=(
  backup-verify devops deploy-smoke infra-health disk-guard reconcile branch-audit
  exit-code-contract worktree delivery-control capability-matrix context-routing ui-token plain-deadzone
  ui-deadcode ui-graph log-assert python-entrypoints
  lint-baselines injection-lint ui-fixture-lint ops-ci-coverage
  ui-quality-plane ui-quality-gate review-card-golden docs-lint gen-ios-baseline
  github-workflows
  ios-signal-traps ios-install-provenance ios-run-verdict ios-device-lock
  ios-cache-evict review-flip-probe ios-device-files ios-device-logs ios-test-discovery
  userland-portability script-help install-hooks lib-sourcing podcast-ops
  streaming-command app-review demo-data catalog-agent uitest-contact-sheet
  ios-release sim-pool-disposable review-probe
  sentry-tool
)

# These groups are intentionally executed by ci_expected_fail_exclusions.sh on
# Linux.  Keep this list at three: the contract test uses it as the expected
# platform-failure surface.
MAC_GROUPS=(
  release ios-ops lldb-forensics
)

# Native macOS groups run in their own macOS job and must not be treated as an
# expected Linux failure.  They still belong to the complete classification.
MAC_NATIVE_GROUPS=(
  ios-sentry-wiring
)

declared_groups() {
  awk '
    /^DEFAULT_TESTS=\(/ { inside=1; next }
    inside && /^\)/ { inside=0; next }
    inside { sub(/#.*/, ""); gsub(/[[:space:]]/, ""); if ($0 != "") print }
  ' ops/test_ops.sh
}

contains() {
  local needle="$1"; shift
  local item
  for item in "$@"; do [[ "$item" == "$needle" ]] && return 0; done
  return 1
}

declared=()
while IFS= read -r group; do
  [[ -n "$group" ]] && declared+=("$group")
done < <(declared_groups)
MAC_ALL_GROUPS=("${MAC_GROUPS[@]}" "${MAC_NATIVE_GROUPS[@]}")
all=("${LINUX_GROUPS[@]}" "${MAC_ALL_GROUPS[@]}")
failed=0

for group in "${declared[@]}"; do
  if ! contains "$group" "${all[@]}"; then
    echo "✗ unclassified ops test group: $group" >&2
    failed=1
  fi
done
for group in "${all[@]}"; do
  if ! contains "$group" "${declared[@]}"; then
    echo "✗ classified group is absent from ops/test_ops.sh: $group" >&2
    failed=1
  fi
done

for group in "${LINUX_GROUPS[@]}"; do
  if contains "$group" "${MAC_ALL_GROUPS[@]}"; then
    echo "✗ group appears in both Linux and macOS classifications: $group" >&2
    failed=1
  fi
done
for group in "${MAC_GROUPS[@]}"; do
  if contains "$group" "${MAC_NATIVE_GROUPS[@]}"; then
    echo "✗ group appears in both expected-fail and native macOS classifications: $group" >&2
    failed=1
  fi
done

if [[ "${1:-}" == "--print-linux-groups" ]]; then
  (( failed == 0 )) || exit 1
  printf '%s\n' "${LINUX_GROUPS[@]}"
  exit 0
fi
if [[ "${1:-}" == "--print-mac-groups" ]]; then
  (( failed == 0 )) || exit 1
  printf '%s\n' "${MAC_GROUPS[@]}"
  exit 0
fi
if (( failed != 0 )); then
  exit 1
fi
echo "✓ ${#declared[@]} ops test groups classified (${#LINUX_GROUPS[@]} Linux, ${#MAC_GROUPS[@]} macOS expected-fail, ${#MAC_NATIVE_GROUPS[@]} native macOS)"
