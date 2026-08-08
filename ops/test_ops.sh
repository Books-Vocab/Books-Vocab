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
  reconcile
  branch-audit
  worktree-orchestrator
  backlog
  review-audit
  capability-matrix
  ui-deadcode
  ui-graph
  log-assert
  python-entrypoints
  ui-token
  plain-deadzone
  lint-baselines
  injection-lint
  ui-fixture-lint
  ops-ci-coverage
  gate-can-fail
  ui-quality-plane
  ui-quality-gate
  visual-regression
  catalog-review
  catalog-scene-expectations
  docs-lint
  gen-ios-baseline
  ios-signal-traps
  sim-pool-disposable
  ios-ops
  ios-run-verdict
  ios-cache-evict
  review-probe
  review-flip-probe
  lldb-forensics
  ios-device-files
  ios-device-logs
  ios-test-discovery
  script-help
  lib-sourcing
  podcast-ops
  # ── IMP-20260805-947062：以下 4 個 group 收編原本對每個 group 都不可達的 19 支
  #    測試檔。反向覆蓋由 ops/tests/test_ops_ci_coverage.sh 的
  #    「every tracked test file is reachable from some group」把關——新增測試檔
  #    卻忘了註冊，那段會指名它並回非零。
  streaming-command
  app-review
  demo-data
  catalog-render
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
      # IMP-20260805-947062：devops_kg_safe.sh 的 transport retarget 契約測試，
      # 主體與 test_devops.sh 同源（都測 wrapper），先前不屬於任何 group。
      ./ops/tests/test_devops_safe_lightsail_guard.sh &&
      "$UV_BIN" run --project backend python -m pytest -q ops/tests/test_ops_edit_batch.py
      ;;
    deploy-smoke)       ./ops/tests/test_deploy_smoke.sh ;;
    infra-health)       ./ops/test_infra_health.sh ;;
    reconcile)          ./ops/tests/test_kg_reconcile.sh ;;
    branch-audit)       ./ops/tests/test_branch_audit.sh ;;
    worktree-orchestrator)
      "$UV_BIN" run --no-project --python 3.13 --with pytest pytest -q \
        ops/tests/test_worktree_orchestrate.py \
        ops/tests/test_worktree_registry.py \
        ops/tests/test_worktree_state.py
      ;;
    backlog)
      # Both files are stdlib-only on purpose, so they run under the same
      # --no-project sandbox as the cutover gate uses.
      "$UV_BIN" run --no-project --python 3.13 --with pytest pytest -q \
        ops/tests/test_backlog.py \
        ops/tests/test_backlog_migration.py
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
    lint-baselines)     ./ops/tests/test_lint_baselines.sh ;;
    injection-lint)     ./ops/tests/test_injection_lint.sh ;;
    ui-fixture-lint)    ./ops/tests/test_ui_fixture_lint.sh ;;
    ops-ci-coverage)    ./ops/tests/test_ops_ci_coverage.sh ;;
    gate-can-fail)      ./ops/tests/test_gate_can_fail.sh ;;
    ui-quality-plane)   ./ops/tests/test_ui_quality_plane.sh ;;
    ui-quality-gate)    ./ops/tests/test_ui_quality_gate.sh ;;
    visual-regression)  ./ops/tests/test_visual_regression.sh ;;
    catalog-review)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q \
        ops/tests/test_catalog_review.py \
        ops/tests/test_catalog_review_entry.py
      ;;
    catalog-scene-expectations)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q \
        ops/tests/test_catalog_scene_expectations.py
      ;;
    docs-lint)
      ./ops/tests/test_docs_impact.sh
      ./ops/tests/test_docs_registry_coverage.sh
      ./ops/tests/test_docs_lint.sh
      ./ops/tests/test_docs_lint_generated_check.sh
      ;;
    gen-ios-baseline)
      ./ops/tests/test_gen_ios_baseline.sh
      ;;
    ios-signal-traps)
      ./ops/tests/test_ios_signal_traps.sh
      ;;
    sim-pool-disposable)
      ./ops/tests/test_ios_ops_sim_pool_disposable.sh
      ;;
    ios-ops)
      ./ops/test_ios_ops.sh &&
      ./ops/tests/test_ios_ops_release_heartbeat.sh &&
      "$UV_BIN" run --project backend python -m pytest -q \
        ops/tests/test_ios_diagnostics.py \
        ops/tests/test_ios_coverage.py
      ;;
    ios-run-verdict)    ./ops/tests/test_ios_run_verdict.sh ;;
    ios-cache-evict)    ./ops/tests/test_ios_cache_evict.sh ;;
    review-probe)       ./ops/tests/test_review_probe.sh ;;
    review-flip-probe)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q ops/tests/test_review_flip_probe_report.py
      ;;
    # 真 lldb 那支必須排第一：ops-ci-coverage 的證偽器靠「遮蔽 xcrun → 這個 group 必死」
    # 認定它的 bin-xcode 相依，而 timeout 守衛用假 lldb、遮蔽 xcrun 也照樣綠。
    lldb-forensics)
      ./ops/tests/test_lldb_crash_forensics.sh &&
      ./ops/tests/test_lldb_forensics_timeout.sh
      ;;
    ios-device-files)   ./ops/tests/test_ios_device_files.sh ;;
    ios-device-logs)    ./ops/tests/test_ios_device_logs.sh ;;
    ios-test-discovery) ./ops/test_ios_test_discovery.sh ;;
    script-help)        ./ops/tests/test_script_help.sh ;;
    lib-sourcing)       ./ops/tests/test_lib_sourcing.sh ;;
    podcast-ops)
      "$UV_BIN" run --python 3.13 --with pytest pytest -q \
        ops/test_podcast_ops.py \
        ops/tests/test_podcast_backfill_disk.py \
        ops/tests/test_podcast_cover_publish.py \
        ops/tests/test_podcast_preview_backfill.py
      ;;
    # ── IMP-20260805-947062 收編的 4 個 group ────────────────────────────────
    # 全部跑在 backlog case 那個 --no-project sandbox 裡：這 18 支只 import stdlib
    # ＋ pytest，逐支實測過不需要 --project backend。
    streaming-command)
      # 鐵律 5 heartbeat 契約唯一的 [machine] 守衛，先前從不執行。
      "$UV_BIN" run --no-project --python 3.13 --with pytest pytest -q \
        ops/tests/test_streaming_command.py
      ;;
    app-review)
      "$UV_BIN" run --no-project --python 3.13 --with pytest pytest -q \
        ops/tests/test_app_review_evidence.py \
        ops/tests/test_app_review_gate.py \
        ops/tests/test_reviewer_evidence.py \
        ops/tests/test_asc_reviewer_mirror.py \
        ops/tests/test_provenance.py
      ;;
    demo-data)
      "$UV_BIN" run --no-project --python 3.13 --with pytest pytest -q \
        ops/tests/test_demo_ios_emitter.py \
        ops/tests/test_demo_ios_spec_emitter.py \
        ops/tests/test_shape_history.py \
        ops/tests/test_apply_curation.py \
        ops/tests/test_capture_profile.py \
        ops/tests/test_ui_world_manifest.py \
        ops/tests/test_uitest_flow_matrix.py \
        ops/tests/test_uitest_review_page.py
      ;;
    catalog-render)
      "$UV_BIN" run --no-project --python 3.13 --with pytest pytest -q \
        ops/tests/test_catalog_appearance_proof.py \
        ops/tests/test_contact_sheet.py \
        ops/tests/test_frame_catalog.py \
        ops/tests/test_render_fit.py
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
