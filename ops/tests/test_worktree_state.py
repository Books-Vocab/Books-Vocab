"""Unit tests for ops/lib/worktree_state.py — the pure worktree-health判定層.

House pattern (mirrors ops/tests/test_converge_board.py): load the module under
test with importlib.spec_from_file_location and feed the pure functions a
synthetic `facts` dict — exactly what the (future) IO layer would gather from
read-only git. No git, no subprocess, no filesystem — pure.

These tests ARE the contract:
  * every State is reachable from some facts dict;
  * unsafe_to_drop returns a reason on each way a drop loses work, None when safe;
  * the safety-critical precedence (DIRTY / LIVE dominate any recyclable verdict)
    is pinned so a still-running or unsaved worktree can never be misfiled as
    reclaimable.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "worktree_state", ROOT / "ops" / "lib" / "worktree_state.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

classify = MODULE.classify
unsafe_to_drop = MODULE.unsafe_to_drop
State = MODULE.State
SCHEMA = MODULE.SCHEMA


def _facts(**overrides):
    """A clean, owned branch card whose unique work (if any) is already landed.

    Baseline classifies MERGED (nothing to preserve); override per case. The
    field semantics mirror the module docstring's facts contract."""
    base = {
        "name": "feature-x",
        "detached": False,        # HEAD is on a branch
        "dirty": False,           # no uncommitted worktree changes
        "ahead": 0,               # topological commits on ref not on base (advisory)
        "behind": 0,              # commits on base not reachable from ref
        "unique_commits": 0,      # count of unique commits carrying work
        "landed_in_base": True,   # tree-diff: ref's net change already in base
        "head_age_s": None,       # seconds since HEAD commit; None = unknown
        "live_window_s": 7200,    # younger than this => LIVE
        "has_worktree": True,     # a checked-out worktree exists
        "has_origin": False,      # advisory: upstream tracking ref exists
        "registered_active": True,  # registry/ledger owns this as an active wt
    }
    base.update(overrides)
    return base


# ----- schema -----------------------------------------------------------------

def test_schema_constant():
    assert SCHEMA == "kg.worktree.state.v1"


# ----- ACTIVE: unique unlanded work, clean, on top of base --------------------

def test_active_clean_unique_work_on_top_of_base():
    f = _facts(unique_commits=2, ahead=2, landed_in_base=False, behind=0)
    assert classify(f) is State.ACTIVE


def test_active_needs_no_worktree_registration_to_hold_work():
    # genuine unlanded work is never an orphan, even without owner/worktree.
    f = _facts(unique_commits=1, landed_in_base=False, behind=0,
               registered_active=False, has_worktree=False)
    assert classify(f) is State.ACTIVE


# ----- MERGED: unique work already landed in base (tree-diff) -----------------

def test_merged_when_unique_work_landed_but_ref_still_ahead():
    # ref still carries commits topologically (ahead>0) but tree-diff says the net
    # change is already in base -> redundant ref, recyclable.
    f = _facts(unique_commits=3, ahead=3, behind=1, landed_in_base=True)
    assert classify(f) is State.MERGED


def test_owned_empty_ref_is_merged():
    # owned branch identical to base (no unique work) -> nothing to preserve.
    f = _facts(unique_commits=0, ahead=0, landed_in_base=True)
    assert classify(f) is State.MERGED


# ----- ORPHAN: detached (no branch) OR unowned stub with no unique work --------

def test_orphan_detached_worktree():
    f = _facts(name=None, detached=True, has_worktree=True, registered_active=False)
    assert classify(f) is State.ORPHAN


def test_orphan_unowned_stub_branch_no_unique_work():
    # a leftover stub branch nobody registered, carrying no unique work.
    f = _facts(name="stub/leftover", unique_commits=0, landed_in_base=True,
               registered_active=False, has_worktree=False)
    assert classify(f) is State.ORPHAN


# ----- DIRTY: uncommitted worktree changes ------------------------------------

def test_dirty_clean_case():
    f = _facts(dirty=True)
    assert classify(f) is State.DIRTY


# ----- DIVERGED: forked from base AND unique work unlanded ---------------------

def test_diverged_when_behind_base_with_unlanded_work():
    f = _facts(unique_commits=2, ahead=2, behind=5, landed_in_base=False)
    assert classify(f) is State.DIVERGED


# ----- LIVE: recent HEAD, suspected active agent ------------------------------

def test_live_when_head_within_window():
    f = _facts(head_age_s=10, live_window_s=7200)
    assert classify(f) is State.LIVE


def test_not_live_when_head_older_than_window():
    f = _facts(unique_commits=2, landed_in_base=False, behind=0,
               head_age_s=99999, live_window_s=7200)
    assert classify(f) is State.ACTIVE  # old head => classified by shape, not LIVE


def test_live_window_is_per_facts_overridable():
    # same 30s-old head is LIVE under a 60s window, not under a 5s window.
    young = _facts(head_age_s=30, live_window_s=60)
    assert classify(young) is State.LIVE
    aged = _facts(unique_commits=1, landed_in_base=False,
                  head_age_s=30, live_window_s=5)
    assert classify(aged) is State.ACTIVE


# ----- precedence: DIRTY / LIVE dominate every recyclable verdict --------------

def test_dirty_beats_looks_merged():
    # would classify MERGED on committed shape, but uncommitted work dominates.
    f = _facts(dirty=True, unique_commits=3, ahead=3, landed_in_base=True)
    assert classify(f) is State.DIRTY


def test_dirty_beats_detached_orphan():
    # deliberate divergence from converge_board: a detached DIRTY worktree is
    # DIRTY (snapshot first), NOT ORPHAN — else its uncommitted work is lost.
    f = _facts(name=None, detached=True, dirty=True)
    assert classify(f) is State.DIRTY


def test_live_beats_stub_when_worktree_present():
    # looks like an unowned stub (ORPHAN) but a checked-out worktree with a recent
    # HEAD -> LIVE wins. LIVE now REQUIRES has_worktree (see next test).
    f = _facts(name="stub", unique_commits=0, landed_in_base=True,
               registered_active=False, has_worktree=True, head_age_s=5)
    assert classify(f) is State.LIVE


def test_fresh_head_is_not_live_without_a_worktree():
    # THE bug fix: a dangling stub branch (no worktree) with a FRESH HEAD is NOT
    # LIVE — a just-landed ref must stay reclaimable, not be shielded as a running
    # agent because a merge commit made its HEAD look recent.
    f = _facts(name="stub", unique_commits=0, landed_in_base=True,
               registered_active=False, has_worktree=False, head_age_s=5)
    assert classify(f) is State.ORPHAN


def test_live_beats_detached_orphan():
    f = _facts(name=None, detached=True, head_age_s=5)
    assert classify(f) is State.LIVE


def test_live_beats_dirty():
    # both are "do not touch"; LIVE is stricter (don't even snapshot a racing wt).
    f = _facts(dirty=True, head_age_s=5)
    assert classify(f) is State.LIVE


# ----- every State is reachable + classify is total ---------------------------

def test_every_state_is_reachable():
    reached = {
        classify(_facts(head_age_s=1)),                                    # LIVE
        classify(_facts(dirty=True)),                                      # DIRTY
        classify(_facts(name=None, detached=True, registered_active=False)),  # ORPHAN
        classify(_facts(unique_commits=1, landed_in_base=False, behind=3)),   # DIVERGED
        classify(_facts(unique_commits=1, landed_in_base=False, behind=0)),   # ACTIVE
        classify(_facts(unique_commits=2, landed_in_base=True)),           # MERGED
    }
    assert reached == set(State)


def test_classify_always_returns_a_state():
    assert isinstance(classify(_facts()), State)


# ============================================================================
# unsafe_to_drop — the reclaim safety predicate. Returns a human reason when
# dropping the card would lose work, else None.
# ============================================================================

def test_drop_safe_when_landed_and_clean():
    # unique work all landed (tree-diff), clean, not live -> safe to reclaim.
    assert unsafe_to_drop(_facts(unique_commits=3, ahead=3, landed_in_base=True)) is None


def test_drop_safe_for_owned_empty_ref():
    assert unsafe_to_drop(_facts(unique_commits=0, landed_in_base=True)) is None


def test_drop_unsafe_when_dirty():
    reason = unsafe_to_drop(_facts(dirty=True))
    assert reason is not None and "dirty" in reason.lower()


def test_drop_unsafe_when_unique_work_unlanded():
    reason = unsafe_to_drop(_facts(unique_commits=2, ahead=2, landed_in_base=False))
    assert reason is not None and "2" in reason


def test_drop_unsafe_when_live():
    reason = unsafe_to_drop(_facts(head_age_s=5, live_window_s=7200))
    assert reason is not None and "live" in reason.lower()


def test_drop_safe_for_fresh_dangling_landed_branch():
    # fresh HEAD but no worktree + landed + clean -> not LIVE (no worktree to shield),
    # nothing unlanded -> safe to reclaim. Pairs with the classify bug-fix test.
    f = _facts(name="stub", unique_commits=0, landed_in_base=True,
               has_worktree=False, head_age_s=5)
    assert unsafe_to_drop(f) is None


def test_drop_safe_when_detached_contained_in_base():
    # detached worktree whose net change is already in base -> nothing orphaned.
    f = _facts(name=None, detached=True, landed_in_base=True)
    assert unsafe_to_drop(f) is None


def test_drop_unsafe_when_detached_not_contained():
    # detached HEAD carrying commits not in base -> pruning would orphan them.
    f = _facts(name=None, detached=True, landed_in_base=False, head_age_s=None)
    reason = unsafe_to_drop(f)
    assert reason is not None and "contain" in reason.lower()


def test_drop_unsafe_when_branch_not_contained_even_with_zero_unique():
    # belt-and-suspenders: IO reports contradictory facts (not landed_in_base but
    # 0 unique commits). A non-detached branch must NOT be silently declared safe —
    # the branch path guards on containment (not landed_in_base), not on
    # unique_commits alone, so committed work can never be dropped by a bad count.
    f = _facts(name="feature-x", detached=False,
               landed_in_base=False, unique_commits=0, ahead=0)
    reason = unsafe_to_drop(f)
    assert reason is not None and "contain" in reason.lower()


def test_drop_unsafe_dirty_dominates_even_if_landed():
    # a landed+clean-looking card that is actually dirty is still unsafe.
    reason = unsafe_to_drop(_facts(unique_commits=0, landed_in_base=True, dirty=True))
    assert reason is not None and "dirty" in reason.lower()


def test_drop_unsafe_live_dominates_even_if_landed():
    reason = unsafe_to_drop(_facts(unique_commits=0, landed_in_base=True, head_age_s=3))
    assert reason is not None and "live" in reason.lower()
