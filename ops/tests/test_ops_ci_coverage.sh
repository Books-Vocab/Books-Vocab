#!/usr/bin/env bash
# Every ops/test_ops.sh group must be explicitly classified as CI-runnable or
# not, with a reason.
#
# 沒有這條，`.github/workflows/ops-suite.yml` 的覆蓋面會靜默腐爛：新增一個 group、
# 忘了加進 CI 清單，那個 group 就永遠只在有人手動跑的時候存在。ops 套件在
# 2026-08-03 之前完全沒有 CI 執行面，代價是 test_ui_quality_gate.sh 紅了數週、
# ui-quality-gate 空轉兩個月，都沒有任何東西發聲。
#
# Usage:
#   ./ops/tests/test_ops_ci_coverage.sh                     # assert classification is total
#   ./ops/tests/test_ops_ci_coverage.sh --print-linux-groups # emit the CI group list

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$WORKSPACE"

# Groups that need nothing beyond python/uv, git, ripgrep and jq.
LINUX_GROUPS=(
  lint-baselines
  injection-lint
  ops-ci-coverage
  ui-token
  plain-deadzone
  ui-quality-plane
  docs-lint
  python-entrypoints
  capability-matrix
  worktree-orchestrator
  script-help
)

# Everything else, each with the reason it cannot run on a linux CI runner.
# A group without a reason is a silent coverage hole, so the reason is required.
EXCLUDED_GROUPS=(
  "ui-quality-gate|its --dataset assertions load a UI World whose assets are absolute local paths (lab/podcast workspaces)"
  "release|drives ops/release.sh against local tags and the iOS pbxproj"
  "ios-release|xcodebuild / Xcode toolchain"
  "ios-ops|xcodebuild + simulator"
  "ios-run-verdict|xcodebuild verdict files"
  "ios-cache-evict|Xcode DerivedData layout"
  "ios-test-discovery|xcodebuild test enumeration"
  "ios-device-files|physical device / libimobiledevice"
  "ios-device-logs|physical device / libimobiledevice"
  "ui-deadcode|IndexStore produced by Xcode"
  "ui-graph|IndexStore produced by Xcode"
  "log-assert|macOS unified logging (/usr/bin/log)"
  "review-probe|macOS simulator instrumentation"
  "review-flip-probe|macOS simulator instrumentation"
  "lldb-forensics|lldb / macOS crash reports"
  "visual-regression|rendered catalog PNGs from a simulator run"
  "catalog-review|rendered catalog PNGs from a simulator run"
  "backup-verify|reaches the production host over ssh"
  "devops|reaches the production host over ssh"
  "deploy-smoke|reaches the production host over ssh"
  "infra-health|reaches the production host over ssh"
  "reconcile|reconciler fixtures assume the deploy host layout"
  "branch-audit|needs an authenticated gh token"
  "review-audit|needs an authenticated gh token"
  "podcast-ops|lab/podcast toolchain + network TTS"
)

if [[ "${1:-}" == "--print-linux-groups" ]]; then
  printf '%s\n' "${LINUX_GROUPS[@]}"
  exit 0
fi

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

# DEFAULT_TESTS is the SoT for what the suite contains.
DECLARED=()
while IFS= read -r line; do DECLARED+=("$line"); done < <(
  awk '/^DEFAULT_TESTS=\(/{flag=1;next} /^\)/{flag=0} flag {gsub(/[[:space:]]/,"");if($0!="")print}' ops/test_ops.sh
)

section "DEFAULT_TESTS is readable"
if [[ "${#DECLARED[@]}" -gt 0 ]]; then
  ok "parsed ${#DECLARED[@]} group(s) from ops/test_ops.sh"
else
  fail_t "parsed 0 groups — the probe is broken, not the classification"
fi

section "every declared group is classified exactly once"
for g in "${DECLARED[@]}"; do
  in_linux=0
  for l in "${LINUX_GROUPS[@]}"; do [[ "$l" == "$g" ]] && in_linux=1; done
  in_excluded=0
  for e in "${EXCLUDED_GROUPS[@]}"; do [[ "${e%%|*}" == "$g" ]] && in_excluded=1; done
  if (( in_linux + in_excluded == 1 )); then
    :
  elif (( in_linux + in_excluded == 0 )); then
    fail_t "$g is unclassified — add it to LINUX_GROUPS or give it an EXCLUDED_GROUPS reason"
  else
    fail_t "$g is in both LINUX_GROUPS and EXCLUDED_GROUPS"
  fi
done
(( fail == 0 )) && ok "all ${#DECLARED[@]} group(s) classified"

section "no classification refers to a group that no longer exists"
for g in "${LINUX_GROUPS[@]}" "${EXCLUDED_GROUPS[@]%%|*}"; do
  found=0
  for d in "${DECLARED[@]}"; do [[ "$d" == "$g" ]] && found=1; done
  (( found == 1 )) || fail_t "$g is classified but not in DEFAULT_TESTS — stale entry"
done
ok "classification contains no stale entries"

echo ""
echo "ops-ci-coverage: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
