"""Focused lifecycle, ownership, and claim group for registry tests.

The historical registry collector remains the compatibility source for these
tests.  Re-exporting the selected functions gives the dispatcher a precise
ownership path while keeping the old node names available to callers that
still collect ``test_worktree_registry.py`` directly.
"""

from __future__ import annotations

import test_worktree_registry as legacy


pytestmark = legacy.pytestmark

_NAMES = (
    "test_usage_errors_return_contract_code_for_root_and_subparser_typos",
    "test_work_mode_contract_is_explicit_and_legacy_records_remain_readable",
    "test_register_list_resolve_roundtrip",
    "test_direct_scope_and_codex_thread_owner_roundtrip",
    "test_one_codex_thread_can_bind_multiple_active_worktrees",
    "test_hand_back_stamps_the_checked_out_tip",
    "test_hand_back_refuses_when_recorded_worktree_is_on_the_wrong_branch",
    "test_register_collapses_cross_match_no_two_active_share_a_path",
    "test_register_same_branch_moving_worktrees_leaves_one_active",
    "test_ledger_lock_is_mutually_exclusive",
    "test_parallel_registers_do_not_lose_writes",
    "test_missing_worktree_without_repo_root_does_not_guess_base",
    "test_resolve_missing_record_is_usage_error",
    "test_resolve_rejects_bad_status",
    "test_list_json_reports_live_state_for_active",
    "test_a_ticket_already_held_by_an_active_worktree_is_refused",
    "test_a_losing_claim_leaves_the_ledger_exactly_as_it_found_it",
    "test_the_ledger_writers_are_the_ones_main_serializes",
    "test_exactly_one_of_many_simultaneous_claimants_wins",
    "test_resolving_the_record_is_what_frees_the_ticket",
    "test_a_worktree_re_registering_does_not_collide_with_itself",
    "test_re_registering_without_a_claim_flag_keeps_the_claim",
    "test_delegated_register_flag_is_explicit_three_state",
    "test_exclusive_register_refuses_an_existing_branch_or_path_instead_of_upserting_it",
    "test_a_handed_back_source_can_be_reserved_by_only_one_integration",
    "test_source_reservation_requires_a_live_integration_owner",
    "test_re_registering_with_a_different_claim_replaces_it",
    "test_a_claim_records_when_it_was_taken",
    "test_a_displaced_record_takes_its_claim_with_it",
    "test_the_ledger_listing_shows_who_holds_what",
    "test_a_ticket_id_that_is_only_nearly_right_is_refused",
)

for _name in _NAMES:
    globals()[_name] = getattr(legacy, _name)

for _fixture_name in ("treecase", "sweep_repo"):
    globals()[_fixture_name] = getattr(legacy, _fixture_name)

del _fixture_name
del _name
