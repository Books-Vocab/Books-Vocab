"""Machine contract for the App Review evidence test topology.

The fast ``app-review`` group is an explicit compatibility surface.  This
contract assigns every collected node to exactly one responsibility route so
producer/evaluator/journey/provenance/secret-offline/ASC-reviewer changes can
select a bounded bundle without silently dropping a negative control.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
ROUTE_FILES = (
    "ops/tests/test_app_review_evidence.py",
    "ops/tests/test_app_review_evaluators.py",
    "ops/tests/test_app_review_gate.py",
    "ops/tests/test_asc_reviewer_mirror.py",
    "ops/tests/test_provenance.py",
    "ops/tests/test_reviewer_evidence.py",
)
DISPATCHED_FILES = (*ROUTE_FILES, "ops/tests/test_app_review_test_topology.py")


def _nodes(path: str, *names: str) -> tuple[str, ...]:
    return tuple(f"{path}::{name}" for name in names)


ROUTES = {
    "producer": _nodes(
        "ops/tests/test_app_review_evidence.py",
        "test_anchor_order_evidence_manifest_is_typed_and_does_not_claim_pass",
        "test_producer_runner_reports_progress_on_stderr_and_preserves_json_stdout",
        "test_journey_demo_and_gate_use_named_streaming_runner",
        "test_public_cli_has_no_catalog_or_image_generation_producers",
        "test_checked_spec_requires_manual_final_bundle_not_catalog_output",
        "test_required_evidence_excludes_catalog_artifacts",
        "test_plan_preserves_typed_manual_bundle_authority",
        "test_url_checks_hash_exact_body_and_reject_redirect",
        "test_url_checks_get_hashes_exact_body_and_rejects_redirect_or_error",
        "test_journey_producer_hashes_artifacts_and_emits_exact_contract",
        "test_demo_producer_rejects_fixture_masquerading_as_live_demo",
        "test_public_cli_does_not_accept_caller_supplied_demo_receipts",
        "test_demo_identity_resolver_hash_closes_live_mirror_and_rejects_wrong_fingerprint",
        "test_demo_producer_rejects_missing_or_malformed_identity",
        "test_demo_producer_rejects_spoofed_receipt_identity",
        "test_plan_hard_blocks_missing_producer_and_lists_authority",
        "test_status_does_not_mark_existing_but_invalid_artifact_ready",
    ),
    "evaluator": _nodes(
        "ops/tests/test_app_review_evaluators.py",
        "test_evidence_result_is_frozen_and_claim_tokens_are_immutable",
        "test_journey_evaluator_returns_only_its_claim_tokens",
        "test_journey_evaluator_rejects_stale_or_bad_artifacts_without_shared_state",
        "test_demo_evaluator_fail_closes_fixture_and_account_binding",
        "test_urls_and_attestation_are_independent_result_types",
        "test_url_evaluator_rejects_non_hex_digest",
        "test_claim_reducer_preserves_report_shape_and_flags_missing_surface",
    ),
    "journey": _nodes(
        "ops/tests/test_app_review_evidence.py",
        "test_journey_consumer_blocks_false_green_debug_and_provenance_drift",
        "test_journey_rejects_artifact_outside_workspace",
    ) + _nodes(
        "ops/tests/test_app_review_gate.py",
        "test_unknown_journey_and_fixture_demo_cannot_pass",
        "test_journey_path_hash_target_and_freshness_mismatches_block",
        "test_demo_claim_cannot_self_label_fixture_as_exact_device",
    ),
    "provenance": (
        *_nodes(
            "ops/tests/test_provenance.py",
            "test_sha256_file_matches_known_digest",
            "test_sha256_file_discriminates_one_byte",
            "test_sha256_file_spans_chunk_boundary",
            "test_sha256_file_missing_path_raises",
            "test_logical_tool_path_is_checkout_independent",
            "test_logical_tool_path_keeps_subdirs_under_ops",
            "test_logical_tool_path_uses_last_ops_segment",
            "test_logical_tool_path_without_ops_falls_back_to_name",
            "test_logical_tool_path_resolves_symlinks_on_both_branches",
        ),
        *_nodes(
            "ops/tests/test_app_review_evidence.py",
            "test_attestation_is_bound_to_the_pre_attestation_root",
            "test_demo_consumer_rejects_a_run_built_from_a_dirty_tree",
            "test_demo_consumer_rejects_caller_magic_string_without_ios_owner",
            "test_demo_run_command_contains_only_fingerprint_not_raw_identity",
        ),
        *_nodes(
            "ops/tests/test_app_review_gate.py",
            "test_material_change_invalidates_both_attestations",
            "test_desired_project_sha_must_match_source_commit_blob",
            "test_desired_project_sha_matches_source_commit_blob_after_head_moves_on",
            "test_desired_source_commit_blob_that_cannot_be_read_blocks_instead_of_skipping",
            "test_desired_source_commit_blob_check_blocks_when_git_is_unavailable",
        ),
    ),
    "secret-offline": _nodes(
        "ops/tests/test_app_review_gate.py",
        "test_gate_fails_closed_offline_and_requires_attestations",
        "test_malformed_live_review_secret_is_never_copied_or_serialized",
        "test_unknown_live_audit_top_level_secret_is_never_copied",
        "test_live_outer_closure_cannot_smuggle_unreferenced_secret",
    ),
    "asc-reviewer": (
        *_nodes(
            "ops/tests/test_asc_reviewer_mirror.py",
            "test_live_mirror_pins_reviewer_surface_and_redacts_review_secrets",
            "test_reviewer_username_identity_normalization_matches_ios_contract",
            "test_coherence_diff_reports_current_old4_vs_desired_new5_exactly",
            "test_unknown_or_unready_required_live_evidence_never_passes",
            "test_api_error_fails_closed_without_leaking_detail",
            "test_desired_unknown_manifest_field_never_reaches_live_api",
            "test_cdn_bytes_must_equal_desired_sha256_even_when_source_md5_matches",
            "test_stale_build_and_wrong_screenshot_bytes_never_pass",
            "test_live_bundle_is_hash_closed_and_atomic",
            "test_cli_help_is_read_only_and_self_describing",
        ),
        *_nodes(
            "ops/tests/test_reviewer_evidence.py",
            "test_canonical_json_bytes_are_key_order_and_unicode_stable",
            "test_canonical_json_sha256_is_compact_and_changes_with_content",
        ),
    ),
    "compatibility": _nodes(
        "ops/tests/test_app_review_gate.py",
        "test_gate_rejects_missing_typed_producer",
        "test_online_gate_passes_only_with_fresh_root_bound_evidence",
        "test_phase2_unknown_required_build_state_cannot_hide_behind_pass_verdict",
        "test_phase2_screenshot_order_and_source_checksum_are_reasserted",
        "test_manual_bundle_required_objects_are_not_optional",
        "test_bundle_is_exactly_hash_closed_and_verify_detects_extra",
        "test_cli_verify_never_false_greens_a_hash_valid_blocked_bundle",
        "test_checked_in_2_0_0_spec_is_closed_and_self_describing",
        "test_cli_help_is_read_only_schema_driven_and_self_describing",
        "test_app_review_chain_names_the_same_project_file",
    ),
}

REQUIRED_CONTROLS = {
    "producer": "ops/tests/test_app_review_evidence.py::test_journey_producer_hashes_artifacts_and_emits_exact_contract",
    "evaluator": "ops/tests/test_app_review_evaluators.py::test_journey_evaluator_rejects_stale_or_bad_artifacts_without_shared_state",
    "journey": "ops/tests/test_app_review_gate.py::test_unknown_journey_and_fixture_demo_cannot_pass",
    "provenance": "ops/tests/test_app_review_gate.py::test_desired_source_commit_blob_check_blocks_when_git_is_unavailable",
    "secret-offline": "ops/tests/test_app_review_gate.py::test_malformed_live_review_secret_is_never_copied_or_serialized",
    "asc-reviewer": "ops/tests/test_asc_reviewer_mirror.py::test_live_mirror_pins_reviewer_surface_and_redacts_review_secrets",
    "compatibility": "ops/tests/test_app_review_gate.py::test_online_gate_passes_only_with_fresh_root_bound_evidence",
}

NEGATIVE_CONTROLS = {
    "stale": (
        "ops/tests/test_app_review_evaluators.py::test_journey_evaluator_rejects_stale_or_bad_artifacts_without_shared_state",
        "ops/tests/test_asc_reviewer_mirror.py::test_stale_build_and_wrong_screenshot_bytes_never_pass",
    ),
    "malformed": (
        "ops/tests/test_app_review_evidence.py::test_demo_producer_rejects_missing_or_malformed_identity",
        "ops/tests/test_app_review_gate.py::test_malformed_live_review_secret_is_never_copied_or_serialized",
        "ops/tests/test_app_review_gate.py::test_desired_source_commit_blob_that_cannot_be_read_blocks_instead_of_skipping",
    ),
}


def _collect(path: str | Path) -> tuple[str, ...]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--collect-only",
            str(path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 5:
        raise AssertionError(f"zero-selector collection for {path}")
    assert result.returncode == 0, result.stderr or result.stdout
    nodeids = tuple(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("ops/tests/") and "::" in line
    )
    assert nodeids, f"zero-selector collection for {path}"
    return nodeids


def _base_nodeid(nodeid: str) -> str:
    path, name = nodeid.split("::", 1)
    return f"{path}::{name.split('[', 1)[0]}"


def test_routes_collect_without_zero_selectors_and_have_unique_nodeids():
    collected = Counter()
    for path in ROUTE_FILES:
        collected.update(_collect(path))

    assert collected
    assert all(count == 1 for count in collected.values())

    assigned = Counter(nodeid for nodes in ROUTES.values() for nodeid in nodes)
    assert all(count == 1 for count in assigned.values())
    assert set(assigned) == {_base_nodeid(nodeid) for nodeid in collected}


def test_each_route_has_a_named_positive_or_negative_control():
    assigned = {nodeid: route for route, nodes in ROUTES.items() for nodeid in nodes}
    assert set(REQUIRED_CONTROLS) == set(ROUTES)
    for route, nodeid in REQUIRED_CONTROLS.items():
        assert assigned[nodeid] == route


def test_stale_and_malformed_negative_controls_have_one_route():
    assigned = {nodeid: route for route, nodes in ROUTES.items() for nodeid in nodes}
    controls = [nodeid for nodes in NEGATIVE_CONTROLS.values() for nodeid in nodes]
    assert len(controls) == len(set(controls))
    assert all(nodeid in assigned for nodeid in controls)


def test_app_review_dispatcher_has_one_explicit_owner_per_route_file():
    source = (ROOT / "ops/test_ops.sh").read_text(encoding="utf-8")
    arm = source.split("app-review)", 1)[1].split(";;", 1)[0]
    for path in DISPATCHED_FILES:
        assert arm.count(path) == 1, f"dispatcher ownership drift for {path}"
    assert "ops/tests/*.py" not in arm


def test_collection_probe_rejects_a_real_zero_selector(tmp_path: Path):
    empty = tmp_path / "test_empty_selector.py"
    empty.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="zero-selector"):
        _collect(empty)
