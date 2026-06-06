#!/usr/bin/env bash
# test_ops.sh — aggregate non-ASC ops regression tests.
#
# Usage:
#   ./ops/test_ops.sh          # run the full non-ASC ops suite
#   ./ops/test_ops.sh --list   # list available test groups
#   ./ops/test_ops.sh release backup-verify

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    UV_BIN="$HOME/.local/bin/uv"
  else
    UV_BIN="uv"
  fi
fi

ALL_TESTS=(
  release
  backup-verify
  devops
  deploy-smoke
  infra-health
  python-entrypoints
  ui-token
  docs-lint
  ios-test-discovery
  chrome-bundle
  podcast-ops
)

usage() {
  awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
}

list_tests() {
  printf '%s\n' "${ALL_TESTS[@]}"
}

run_one() {
  case "$1" in
    release)            ./ops/test_release.sh ;;
    backup-verify)      ./ops/tests/test_backup_verify.sh ;;
    devops)             ./ops/test_devops.sh ;;
    deploy-smoke)       ./ops/tests/test_deploy_smoke.sh ;;
    infra-health)       ./ops/test_infra_health.sh ;;
    python-entrypoints) ./ops/tests/test_python_entrypoints.sh ;;
    ui-token)           ./ops/test_ui_token_lint.sh ;;
    docs-lint)
      ./ops/tests/test_docs_impact.sh
      ./ops/tests/test_docs_registry_coverage.sh
      ./ops/tests/test_docs_lint.sh
      ;;
    ios-test-discovery) ./ops/test_ios_test_discovery.sh ;;
    chrome-bundle)      ./ops/tests/test_chrome_ext_bundle.sh ;;
    podcast-ops)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q \
        ops/test_podcast_ops.py \
        ops/tests/test_podcast_backfill_disk.py \
        ops/tests/test_podcast_cover_publish.py
      ;;
    *) return 64 ;;
  esac
}

selected=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --list)
      list_tests
      exit 0
      ;;
    -*)
      echo "✗ unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      selected+=("$1")
      shift
      ;;
  esac
done

if [[ "${#selected[@]}" -eq 0 ]]; then
  selected=("${ALL_TESTS[@]}")
fi

passed=0
failed=0
failed_names=()
start_all=$SECONDS

for name in "${selected[@]}"; do
  echo ""
  echo "════════ $name ════════"
  start=$SECONDS
  set +e
  run_one "$name"
  rc=$?
  set -e
  elapsed=$((SECONDS - start))
  if [[ "$rc" -eq 0 ]]; then
    echo "✓ $name passed (${elapsed}s)"
    passed=$((passed + 1))
  elif [[ "$rc" -eq 64 ]]; then
    echo "✗ unknown test group: $name" >&2
    failed=$((failed + 1))
    failed_names+=("$name")
  else
    echo "✗ $name failed rc=$rc (${elapsed}s)" >&2
    failed=$((failed + 1))
    failed_names+=("$name")
  fi
done

echo ""
echo "════════ summary ════════"
echo "passed groups: $passed"
echo "failed groups: $failed"
echo "elapsed: $((SECONDS - start_all))s"
if [[ "$failed" -gt 0 ]]; then
  printf 'failed: %s\n' "${failed_names[*]}" >&2
  exit 1
fi
