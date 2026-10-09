#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
RUNNER="${KG_EXPECTED_FAIL_RUNNER:-./ops/test_ops.sh}"

runner_tool_error() {
  echo "✗ expected-fail runner tool error: $1" >&2
  exit 2
}

if [[ ! -f "$RUNNER" || ! -x "$RUNNER" ]]; then
  runner_tool_error "not an executable file: $RUNNER"
fi

groups=()
if [[ -n "${KG_EXPECTED_FAIL_GROUPS+x}" ]]; then
  # Test seam: lets the harness be falsified with a fixture list.
  read -r -a groups <<<"$KG_EXPECTED_FAIL_GROUPS"
else
  probe_out="$(./ops/tests/test_ops_ci_coverage.sh --print-mac-groups)" ||
    {
      echo "✗ 探針壞了：--print-mac-groups 非零退出，不是分類表" >&2
      exit 2
    }
  while IFS= read -r group; do
    [[ -n "$group" ]] && groups+=("$group")
  done <<<"$probe_out"
fi

if (( ${#groups[@]} == 0 )); then
  echo "expected-fail: 0 條排除（沒有 macOS-only group 需要在 Linux 證偽）"
  exit 0
fi

survived=()
for group in "${groups[@]}"; do
  runner_out="$("$RUNNER" "$group" 2>&1)"
  runner_status=$?

  case "$runner_status" in
  0)
    survived+=("$group")
    echo "  ✗ macOS-only group $group 在 Linux runner 通過" >&2
    ;;
  126|127)
    # Shell reserves these for an executable that could not be launched.
    runner_tool_error "failed to launch for group $group (exit=$runner_status)"
    ;;
  64|75)
    # 64 = unknown group arm, 75 = inconclusive (lock/disk wait): neither proves the group fails.
    runner_tool_error "inconclusive for group $group (exit=$runner_status)"
    ;;
  *)
    if [[ "$runner_out" == *"unknown test group"* ]]; then
      runner_tool_error "unknown test group: $group"
    fi
    echo "  ✓ macOS-only group $group 在 Linux runner 如預期失敗"
    ;;
  esac
done

if (( ${#survived[@]} > 0 )); then
  echo "✗ 這些 macOS-only group 在 Linux runner 通過：${survived[*]}" >&2
  echo "  這是假設不是判決——group 也可能因為別的原因通過。請在此平台實查，若確實可在 Linux 執行就移入 LINUX_GROUPS。" >&2
  exit 1
fi

echo "expected-fail: ${#groups[@]} 條排除全部如預期失敗"
