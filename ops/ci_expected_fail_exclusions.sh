#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
RUNNER="${KG_EXPECTED_FAIL_RUNNER:-./ops/test_ops.sh}"

groups=()
while IFS= read -r group; do
  [[ -n "$group" ]] && groups+=("$group")
done < <(./ops/tests/test_ops_ci_coverage.sh --print-excluded-groups)

if (( ${#groups[@]} == 0 )); then
  echo "✗ 解析不到任何排除 group——探針壞了，不是排除表" >&2
  exit 2
fi

survived=()
for group in "${groups[@]}"; do
  if "$RUNNER" "$group" >/dev/null 2>&1; then
    survived+=("$group")
    echo "  ✗ $group 竟然通過" >&2
  else
    echo "  ✓ $group 如預期失敗"
  fi
done

if (( ${#survived[@]} > 0 )); then
  echo "✗ 這些排除在本平台竟然通過：${survived[*]}" >&2
  echo "  這是假設不是判決——group 也可能因為別的原因通過。請在此平台實查，若確實不需被排除就收進 LINUX_GROUPS。" >&2
  exit 1
fi

echo "expected-fail: ${#groups[@]} 條排除全部如預期失敗"
