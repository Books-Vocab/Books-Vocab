#!/usr/bin/env bash
# test_ops.sh — aggregate ops regression tests.
#
# Usage:
#   ./ops/test_ops.sh          # run the full non-ASC ops suite
#   ./ops/test_ops.sh --list   # list available test groups
#   ./ops/test_ops.sh release backup-verify
#   ./ops/test_ops.sh asc      # run App Store Connect offline surface tests

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

DEFAULT_TESTS=(
  release
  ios-release
  backup-verify
  devops
  deploy-smoke
  infra-health
  branch-audit
  converge-board
  review-audit
  capability-matrix
  ui-deadcode
  ui-graph
  log-assert
  python-entrypoints
  ui-token
  plain-deadzone
  ui-quality-plane
  visual-regression
  catalog-review
  docs-lint
  ios-ops
  ios-cache-evict
  review-probe
  review-flip-probe
  lldb-forensics
  ios-device-files
  ios-test-discovery
  chrome-bundle
  chrome-parity-refs
  script-help
  podcast-ops
)

OPTIONAL_TESTS=(
  asc
  release-surfaces
)

usage() {
  awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"
}

list_tests() {
  printf '%s\n' "${DEFAULT_TESTS[@]}"
  printf '%s (optional)\n' "${OPTIONAL_TESTS[@]}"
}

run_one() {
  case "$1" in
    release)            ./ops/test_release.sh ;;
    ios-release)        ./ops/test_ios_release.sh ;;
    backup-verify)      ./ops/tests/test_backup_verify.sh ;;
    devops)
      ./ops/test_devops.sh &&
      "$UV_BIN" run --project backend python -m pytest -q ops/tests/test_ops_edit_batch.py
      ;;
    deploy-smoke)       ./ops/tests/test_deploy_smoke.sh ;;
    infra-health)       ./ops/test_infra_health.sh ;;
    branch-audit)       ./ops/tests/test_branch_audit.sh ;;
    converge-board)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q ops/tests/test_converge_board.py
      ;;
    review-audit)       ./ops/tests/test_review_audit.sh ;;
    capability-matrix)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q ops/tests/test_capability_matrix.py
      ;;
    ui-deadcode)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q ops/tests/test_ui_deadcode.py &&
      ./ops/tests/test_ui_deadcode.sh
      ;;
    ui-graph)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q ops/tests/test_ui_graph.py &&
      ./ops/tests/test_ui_graph.sh
      ;;
    log-assert)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q ops/tests/test_ios_log_assert.py
      ;;
    python-entrypoints) ./ops/tests/test_python_entrypoints.sh ;;
    ui-token)           ./ops/test_ui_token_lint.sh ;;
    plain-deadzone)     ./ops/test_plain_deadzone_lint.sh ;;
    ui-quality-plane)   ./ops/tests/test_ui_quality_plane.sh ;;
    visual-regression)  ./ops/tests/test_visual_regression.sh ;;
    catalog-review)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q \
        ops/tests/test_catalog_review.py \
        ops/tests/test_catalog_review_entry.py
      ;;
    docs-lint)
      ./ops/tests/test_docs_impact.sh
      ./ops/tests/test_docs_registry_coverage.sh
      ./ops/tests/test_docs_lint.sh
      ;;
    ios-ops)
      ./ops/test_ios_ops.sh &&
      "$UV_BIN" run --project backend python -m pytest -q \
        ops/tests/test_ios_diagnostics.py \
        ops/tests/test_ios_coverage.py
      ;;
    ios-cache-evict)    ./ops/tests/test_ios_cache_evict.sh ;;
    review-probe)       ./ops/tests/test_review_probe.sh ;;
    review-flip-probe)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q ops/tests/test_review_flip_probe_report.py
      ;;
    lldb-forensics)     ./ops/tests/test_lldb_crash_forensics.sh ;;
    ios-device-files)   ./ops/tests/test_ios_device_files.sh ;;
    ios-test-discovery) ./ops/test_ios_test_discovery.sh ;;
    chrome-bundle)      ./ops/tests/test_chrome_ext_bundle.sh ;;
    chrome-parity-refs) ./ops/tests/test_chrome_parity_refs.sh ;;
    script-help)        ./ops/tests/test_script_help.sh ;;
    podcast-ops)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q \
        ops/test_podcast_ops.py \
        ops/tests/test_podcast_backfill_disk.py \
        ops/tests/test_podcast_cover_publish.py
      ;;
    asc)
      ./ops/test_asc.sh
      "$UV_BIN" run --python 3.13 --with pytest pytest -q ops/tests/test_asc_text_bundle.py
      ;;
    release-surfaces)
      run_one release
      run_one ios-release
      run_one asc
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
  selected=("${DEFAULT_TESTS[@]}")
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
