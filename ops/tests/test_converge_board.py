"""Unit tests for ops/converge_board.py pure layer.

The classifier's pure layer takes a synthetic `facts` dict (what the IO layer
would have gathered from read-only git) and returns a canonical `state`, plus a
`suggest_disposition(state, facts)` that maps state -> recommended board mark.

These tests are the contract: every one of the 7 canonical states is exercised,
and the suggested disposition for each is asserted. No git, no IO -- pure.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "converge_board", ROOT / "ops" / "converge_board.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

classify = MODULE.classify
suggest_disposition = MODULE.suggest_disposition
State = MODULE.State
Mark = MODULE.Mark


def _facts(**overrides):
    """A clean baseline branch card fact dict; override per case."""
    base = {
        "name": "feature-x",
        "is_main": False,
        "detached": False,
        "ahead": 0,            # commits on branch not on main
        "behind": 0,           # commits on main not on branch
        "unmerged": 0,         # `git cherry main <branch>` '+' count (patch not in main)
        "dirty": False,        # worktree has uncommitted changes
        "has_origin": False,   # branch has an upstream tracking ref
        "origin_ahead": 0,     # local commits not on origin
        "origin_behind": 0,    # origin commits not on local
        "worktree": None,      # checked-out worktree path, or None
        "head_recent": False,  # worktree HEAD commit is recent (live-agent heuristic)
    }
    base.update(overrides)
    return base


# ----- CURRENT: == main, clean, nothing unique --------------------------------

def test_main_itself_is_current():
    f = _facts(name="main", is_main=True)
    assert classify(f) is State.CURRENT


def test_branch_at_main_tip_is_current():
    # 0 ahead / 0 behind / 0 unmerged, clean -> identical to main
    f = _facts(ahead=0, behind=0, unmerged=0, dirty=False)
    assert classify(f) is State.CURRENT


def test_current_suggests_black():
    # keep in sync (rebase no-op) / leave alone
    assert suggest_disposition(State.CURRENT, _facts()) is Mark.BLACK


# ----- MERGED: patch fully in main, ref still at old tip ----------------------

def test_merged_when_patch_in_main_but_ref_ahead():
    # branch ref still carries commits (ahead > 0) but cherry says all patches
    # already landed in main (unmerged == 0): redundant ref.
    f = _facts(ahead=3, behind=2, unmerged=0)
    assert classify(f) is State.MERGED


def test_merged_suggests_white():
    assert suggest_disposition(State.MERGED, _facts(ahead=3, unmerged=0)) is Mark.WHITE


# ----- AHEAD: unique committed work, clean, on top of main --------------------

def test_ahead_clean_unique_work():
    f = _facts(ahead=1, behind=0, unmerged=1, dirty=False)
    assert classify(f) is State.AHEAD


def test_ahead_suggests_promote():
    assert suggest_disposition(State.AHEAD, _facts(ahead=1, unmerged=1)) is Mark.PROMOTE


# ----- DIRTY: worktree has uncommitted changes --------------------------------

def test_dirty_dominates_even_with_unique_commits():
    f = _facts(ahead=1, unmerged=1, dirty=True)
    assert classify(f) is State.DIRTY


def test_dirty_dominates_on_current_branch():
    # even a branch that is otherwise == main, if dirty, is DIRTY
    f = _facts(ahead=0, behind=0, unmerged=0, dirty=True)
    assert classify(f) is State.DIRTY


def test_dirty_suggests_snap():
    assert suggest_disposition(State.DIRTY, _facts(dirty=True)) is Mark.SNAP


# ----- DIVERGED: local rebased, origin behind (needs force-push sync) ---------

def test_diverged_when_origin_behind_after_rebase():
    # local has unique work all reachable, but origin tracking ref diverged:
    # origin has commits we dropped (rebase) and we have commits origin lacks.
    f = _facts(
        ahead=1, behind=0, unmerged=1, dirty=False,
        has_origin=True, origin_ahead=1, origin_behind=2,
    )
    assert classify(f) is State.DIVERGED


def test_diverged_suggests_black():
    f = _facts(has_origin=True, origin_ahead=1, origin_behind=2, ahead=1, unmerged=1)
    assert suggest_disposition(State.DIVERGED, f) is Mark.BLACK


def test_origin_direction_only_ahead_triggers_diverged():
    # Pins the origin field direction so it can't silently flip:
    # DIVERGED means local has commits origin lacks (origin_ahead>0 = needs push).
    # origin_behind alone (local merely behind origin, nothing to push) must NOT
    # be DIVERGED — it falls through to AHEAD (it still has unique committed work).
    needs_push = _facts(ahead=1, unmerged=1, has_origin=True, origin_ahead=1, origin_behind=0)
    assert classify(needs_push) is State.DIVERGED
    only_behind = _facts(ahead=1, unmerged=1, has_origin=True, origin_ahead=0, origin_behind=5)
    assert classify(only_behind) is State.AHEAD


# ----- STALE_BASE: behind main, needs rebase ----------------------------------

def test_stale_base_when_behind_main_with_unique_work():
    f = _facts(ahead=1, behind=4, unmerged=1, dirty=False)
    assert classify(f) is State.STALE_BASE


def test_stale_base_suggests_black():
    assert suggest_disposition(State.STALE_BASE, _facts(behind=4, unmerged=1)) is Mark.BLACK


# ----- ORPHAN: detached worktree, no branch -----------------------------------

def test_orphan_detached_worktree():
    f = _facts(name=None, detached=True, worktree="/tmp/wt/2758")
    assert classify(f) is State.ORPHAN


def test_orphan_suggests_clean():
    f = _facts(name=None, detached=True, worktree="/tmp/wt/2758")
    assert suggest_disposition(State.ORPHAN, f) is Mark.CLEAN


# ----- live-agent heuristic ---------------------------------------------------

def test_live_agent_ahead_with_recent_head_flagged_live():
    # AHEAD card whose worktree HEAD is a recent commit: still AHEAD by state,
    # but suggestion is FREEZE (don't touch a live agent).
    f = _facts(ahead=1, unmerged=1, worktree="/tmp/wt/live", head_recent=True)
    assert classify(f) is State.AHEAD
    assert suggest_disposition(State.AHEAD, f) is Mark.FREEZE


# ----- precedence: DIRTY beats STALE_BASE beats DIVERGED ----------------------

def test_dirty_beats_stale_base():
    f = _facts(ahead=1, behind=4, unmerged=1, dirty=True)
    assert classify(f) is State.DIRTY


def test_detached_dirty_is_still_orphan():
    # an orphan (detached) takes precedence: nothing to snapshot onto a branch
    f = _facts(name=None, detached=True, dirty=True, worktree="/tmp/wt/x")
    assert classify(f) is State.ORPHAN


# ----- every state has a suggestion -------------------------------------------

def test_every_state_has_a_suggestion():
    for st in State:
        mark = suggest_disposition(st, _facts())
        assert isinstance(mark, Mark)
