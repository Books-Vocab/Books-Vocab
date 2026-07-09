"""Pure 判定層 for worktree / branch health — orphan-sentinel + registration閉環.

Given the read-only facts an IO layer gathered about ONE tracked worktree/branch,
classify its health (`classify`) and answer whether reclaiming it would lose work
(`unsafe_to_drop`). This module is **pure**: it imports no subprocess, runs no
git, touches no filesystem and reads no clock — it consumes an already-gathered
`facts` dict and nothing else. All git/IO (and the tree-diff below) belong to a
separate IO layer that is NOT part of this stage.

Design lineage: this is a精簡/rename of ops/converge_board.py's 7-state taxonomy,
reshaped around two jobs — spotting *orphan sentinels* (worktrees/branches nobody
owns) and closing the *registration loop* (is a ref still owned/active?) — while
never mis-reclaiming a running or unsaved worktree.

--------------------------------------------------------------------------------
facts schema (contract the IO layer MUST honor)
--------------------------------------------------------------------------------
Every field below describes ONE worktree/branch card.

  name              str | None  — branch short-name; None for a detached worktree.
  detached          bool        — HEAD is not on a branch (a raw worktree).
  dirty             bool        — worktree has uncommitted changes.
  ahead             int         — TOPOLOGICAL commits on the ref not on base
                                  (rev-list base..ref). ADVISORY ONLY — after a
                                  rebase/squash it does NOT prove unlanded work.
  behind            int         — commits on base not reachable from the ref
                                  (base moved ahead). Drives DIVERGED vs ACTIVE.
  unique_commits    int         — count of commits carrying genuinely unique work
                                  (used for messaging + "is there unlanded work").
  landed_in_base    bool        — **THE containment truth**: the ref's net change
                                  is already present in base.
                                  ⚠ CONTRACT: the IO layer MUST compute this by
                                  TREE-DIFF (compare the ref's cumulative tree vs
                                  base's tree). It is STRICTLY FORBIDDEN to derive
                                  it from `git cherry` or patch-id: converge_board's
                                  _cherry_unmerged uses `git cherry` for containment
                                  and goes WRONG after a rebase (patch-ids drift),
                                  silently reporting landed work as unlanded (or the
                                  reverse). This lib deliberately consumes only the
                                  pre-computed tree-diff bool so that class of bug
                                  cannot recur here.
  head_age_s        int | None  — seconds since the HEAD commit's commit-time, as
                                  measured once by the IO layer (NOT read here).
                                  None = unknown/unavailable.
  live_window_s     int         — a HEAD younger than this is treated as LIVE.
                                  Optional; defaults to LIVE_WINDOW_DEFAULT_S.
  has_worktree      bool        — a checked-out worktree exists for this ref.
  has_origin        bool        — an upstream tracking ref exists. ADVISORY (for
                                  render/messaging; not read by the predicates).
  registered_active bool        — the active-worktree registry/ledger owns this
                                  ref (the "登記閉環": is it a booked, owned wt?).

`ahead`/`has_origin` are advisory and not consumed by the pure predicates; they
travel in the contract so IO/render layers share one fact shape.
"""

from __future__ import annotations

import enum
from typing import Any

SCHEMA = "kg.worktree.state.v1"

# A HEAD younger than this (seconds) is presumed to belong to a live agent.
LIVE_WINDOW_DEFAULT_S = 7200


class State(enum.Enum):
    """Health classification of one tracked worktree/branch.

    LIVE      HEAD younger than live_window_s — a suspected running agent; never
              touch (do not even snapshot: a racing worktree may be mid-write).
    DIRTY     uncommitted worktree changes — reclaiming vaporizes them.
    ORPHAN    a detached worktree (no branch to act on), OR an unowned stub branch
              (not registered, no worktree) carrying no unique work — the orphan
              sentinel a reclaim pass exists to sweep.
    DIVERGED  base moved ahead (behind>0) AND the ref still has unlanded unique
              work — needs a rebase before it can land.
    ACTIVE    unlanded unique work, clean, on top of base — a healthy going concern.
    MERGED    the ref's unique work is already in base (tree-diff) — a redundant
              ref, safe to reclaim.
    """

    LIVE = "LIVE"
    DIRTY = "DIRTY"
    ORPHAN = "ORPHAN"
    DIVERGED = "DIVERGED"
    ACTIVE = "ACTIVE"
    MERGED = "MERGED"


# ----------------------------------------------------------------------------
# pure helpers
# ----------------------------------------------------------------------------
def _live_window(facts: dict[str, Any]) -> int:
    w = facts.get("live_window_s")
    return int(w) if w is not None else LIVE_WINDOW_DEFAULT_S


def _is_live(facts: dict[str, Any]) -> bool:
    """True when the HEAD commit is younger than the live window (agent likely
    still running). Time was measured by the IO layer into `head_age_s`; this
    function reads no clock. Unknown age (None) is never LIVE."""
    age = facts.get("head_age_s")
    if age is None:
        return False
    return int(age) < _live_window(facts)


def _unique(facts: dict[str, Any]) -> int:
    """Count of unique-work commits. Prefers `unique_commits`; falls back to the
    advisory topological `ahead` only when unique_commits is absent."""
    v = facts.get("unique_commits")
    if v is None:
        v = facts.get("ahead", 0)
    return int(v or 0)


def _has_unlanded_work(facts: dict[str, Any]) -> bool:
    """True when the ref carries unique work NOT yet in base. Uses the tree-diff
    `landed_in_base` bool (never git cherry) as the authority on containment."""
    return (not facts.get("landed_in_base", False)) and _unique(facts) > 0


def _is_stub_orphan(facts: dict[str, Any]) -> bool:
    """An unowned stub branch: on a branch, no unique work, and nobody owns it
    (neither the active registry nor a live worktree). This is the branch-shaped
    orphan sentinel (the detached-worktree shape is handled directly in classify)."""
    if facts.get("detached"):
        return False
    if _has_unlanded_work(facts) or _unique(facts) > 0:
        return False
    return not facts.get("registered_active", False) and not facts.get("has_worktree", False)


# ----------------------------------------------------------------------------
# classify — pure
# ----------------------------------------------------------------------------
def classify(facts: dict[str, Any]) -> State:
    """Map gathered facts to a health State. Pure; precedence is safety-critical.

    Precedence (checked top-down; first match wins):
      1. LIVE     head_age_s < live_window_s. Dominates EVERYTHING — a running
                  agent must never be reclaimed, snapshotted, or reshaped.
      2. DIRTY    uncommitted changes. Dominates every recyclable verdict so
                  unsaved work is never dropped (incl. a detached dirty worktree,
                  which — unlike converge_board — is DIRTY here, not ORPHAN).
      3. ORPHAN   a detached worktree, or an unowned stub branch with no unique
                  work.
      then, by committed shape (has a branch, clean, not live):
        DIVERGED  unlanded unique work AND base moved ahead (behind>0).
        ACTIVE    unlanded unique work on top of base (behind==0).
        MERGED    no unlanded unique work — unique work already in base, or an
                  owned empty ref: a redundant, reclaimable reference.

    Rules 1 and 2 preceding rules ORPHAN/MERGED is the whole safety contract:
    reordering them would let a still-running or unsaved worktree be filed as
    reclaimable and its work destroyed.
    """
    if _is_live(facts):
        return State.LIVE
    if facts.get("dirty"):
        return State.DIRTY
    if facts.get("detached") or _is_stub_orphan(facts):
        return State.ORPHAN

    if _has_unlanded_work(facts):
        if int(facts.get("behind", 0)) > 0:
            return State.DIVERGED
        return State.ACTIVE

    # No unlanded unique work left: the ref's contribution is already in base
    # (or it never had any) -> a redundant, reclaimable reference.
    return State.MERGED


# ----------------------------------------------------------------------------
# unsafe_to_drop — pure reclaim guard
# ----------------------------------------------------------------------------
def unsafe_to_drop(facts: dict[str, Any]) -> str | None:
    """Return a human reason why reclaiming this card would LOSE work, else None.

    Pure. Precedence mirrors classify's safety ordering:
      live                 HEAD within the live window — an agent may be running.
      dirty                uncommitted changes would vanish (snapshot first;
                           never stash).
      detached !contained  a detached HEAD whose net change is NOT in base (tree-
                           diff) — pruning would orphan commits absent from base.
      unlanded unique      a branch with unique commits not yet landed in base
                           (tree-diff) — deleting the ref would lose them.

    Safe (None): a landed+clean branch, an owned empty ref, or a detached worktree
    whose work is already contained in base. `landed_in_base` — computed by the IO
    layer via TREE-DIFF, never git cherry — is the authority on containment.
    """
    if _is_live(facts):
        return "live: HEAD within live window (an agent may be running; do not reclaim)"
    if facts.get("dirty"):
        return "dirty: uncommitted changes would vanish (snapshot first; never stash)"
    if facts.get("detached"):
        if not facts.get("landed_in_base", False):
            return ("detached HEAD not contained in base (tree-diff): "
                    "pruning would orphan commits not in base")
        return None
    if _has_unlanded_work(facts):
        n = _unique(facts)
        return f"{n} unique commit(s) not yet landed in base (tree-diff) — would be lost"
    return None
