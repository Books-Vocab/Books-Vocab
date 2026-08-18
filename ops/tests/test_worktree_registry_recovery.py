"""Focused recovery and containment group for the registry test topology.

The historical registry collector remains the compatibility source for these
tests.  Re-exporting the selected functions gives the dispatcher a precise
ownership path while keeping the old node names available to callers that
still collect ``test_worktree_registry.py`` directly.
"""

from __future__ import annotations

import test_worktree_registry as legacy


treecase = legacy.treecase
sweep_repo = legacy.sweep_repo
pytestmark = legacy.pytestmark

_NAMES = (
    "test_containment_A_ancestor_is_landed",
    "test_containment_B_squash_merge_is_landed_though_cherry_lies",
    "test_containment_C_unique_work_is_not_landed",
    "test_containment_deletion_not_absorbed_is_not_landed",
    "test_sweep_dryrun_classifies_every_disposition",
    "test_landed_branch_with_open_worktree_is_kept",
    "test_dangling_unlanded_branch_is_kept",
    "test_sweep_dryrun_mutates_nothing",
    "test_sweep_commit_clears_safe_keeps_unsafe_and_protected",
    "test_sweep_untracked_worktree_is_flagged",
    "test_sweep_never_tears_down_base_branch_or_primary_worktree",
    "test_fresh_dangling_landed_branch_clears_despite_fresh_head",
    "test_sweep_default_base_is_origin_main",
    "test_json_mode_labels_and_reflects_execution",
    "test_sweep_exclude_current_keeps_the_invoking_worktree",
    "test_sweep_exclude_current_still_clears_other_orphans",
    "test_sweep_exclude_current_flag_defaults_false",
    "test_porcelain_parse_keeps_the_prunable_reason",
    "test_porcelain_parse_separates_locked_from_prunable",
    "test_protected_step_predicate_sees_past_option_flags",
)

for _name in _NAMES:
    globals()[_name] = getattr(legacy, _name)

del _name
