"""Unit tests for ops/converge_board.py pure layer.

The classifier's pure layer takes a synthetic `facts` dict (what the IO layer
would have gathered from read-only git) and returns a canonical `state`, plus a
`suggest_disposition(state, facts)` that maps state -> recommended board mark.

These tests are the contract: every one of the 7 canonical states is exercised,
and the suggested disposition for each is asserted. No git, no IO -- pure.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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
unsafe_to_drop = MODULE.unsafe_to_drop
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
        "remote_only": False,  # branch exists on origin with no local counterpart
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


# ============================================================================
# integration: the mutation subcommands (teardown / gc) against a real scratch
# git repo. These cover the IO + mutation layers the pure tests can't — exactly
# the gap that let a `facts['state']` KeyError ship. git-backed, opt-skipped if
# git is absent.
# ============================================================================
pytestmark_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def _git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout.strip()


def _local_branches(repo):
    return set(_git(["for-each-ref", "--format=%(refname:short)", "refs/heads"], repo).split())


def _remote_branches(repo):
    out = _git(["ls-remote", "--heads", "origin"], repo)
    return {ln.split("refs/heads/")[-1] for ln in out.splitlines() if ln}


@pytest.fixture
def scratch(tmp_path):
    """A repo with: base on main, a bare origin, branch `landed` (its patch in
    main, ref pushed to origin) checked out in a worktree, branch `unlanded`
    (commit not in main), and three detached worktrees: contained / dirty /
    uncontained. Chdir into it for the duration."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "f").write_text("base\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "base"], repo)

    remote = tmp_path / "remote.git"
    _git(["init", "-q", "--bare", str(remote)], repo)
    _git(["remote", "add", "origin", str(remote)], repo)
    _git(["push", "-q", "origin", "main"], repo)

    # landed: commit on a branch, then ff main onto it (patch contained), keep ref + push.
    _git(["checkout", "-q", "-b", "landed"], repo)
    (repo / "x").write_text("x\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "X"], repo)
    _git(["push", "-q", "-u", "origin", "landed"], repo)
    _git(["checkout", "-q", "main"], repo)
    _git(["merge", "-q", "landed"], repo)  # ff: main now contains landed's commit

    # unlanded: commit not in main
    _git(["checkout", "-q", "-b", "unlanded"], repo)
    (repo / "y").write_text("y\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "Y"], repo)
    uncontained_sha = _git(["rev-parse", "HEAD"], repo)
    _git(["checkout", "-q", "main"], repo)

    _git(["worktree", "add", "-q", str(tmp_path / "wt-landed"), "landed"], repo)
    _git(["worktree", "add", "-q", "--detach", str(tmp_path / "wt-contained"), "main"], repo)
    _git(["worktree", "add", "-q", "--detach", str(tmp_path / "wt-uncontained"), uncontained_sha], repo)
    _git(["worktree", "add", "-q", "--detach", str(tmp_path / "wt-dirty"), "main"], repo)
    (tmp_path / "wt-dirty" / "dirt").write_text("dirt\n")

    prev = Path.cwd()
    os.chdir(repo)
    try:
        yield tmp_path, repo
    finally:
        os.chdir(prev)


@pytestmark_git
def test_teardown_commit_deletes_local_and_remote_keeps_worktree(scratch):
    tmp_path, repo = scratch
    assert "landed" in _local_branches(repo)
    assert "landed" in _remote_branches(repo)

    rc = MODULE.main(["teardown", "--branches", "landed", "--commit", "--no-fetch"])
    assert rc == 0

    assert "landed" not in _local_branches(repo)          # local branch deleted
    assert "landed" not in _remote_branches(repo)         # remote branch deleted (the botched step)
    assert (tmp_path / "wt-landed").is_dir()              # worktree KEPT
    # worktree is now detached (HEAD is not a symbolic branch ref)
    head = subprocess.run(["git", "symbolic-ref", "-q", "HEAD"],
                          cwd=tmp_path / "wt-landed", stdout=subprocess.PIPE).returncode
    assert head != 0


@pytestmark_git
def test_teardown_refuses_unlanded_and_executes_nothing(scratch):
    tmp_path, repo = scratch
    rc = MODULE.main(["teardown", "--branches", "unlanded", "--commit", "--no-fetch"])
    assert rc == MODULE.EXIT_USAGE                        # refused before any write
    assert "unlanded" in _local_branches(repo)            # untouched


@pytestmark_git
def test_teardown_missing_branch_is_refused_not_crash(scratch):
    rc = MODULE.main(["teardown", "--branches", "ghost", "--commit", "--no-fetch"])
    assert rc != 0


@pytestmark_git
def test_gc_prunes_contained_keeps_dirty_and_uncontained(scratch):
    tmp_path, repo = scratch
    rc = MODULE.main(["gc", "--commit", "--no-fetch"])
    assert rc == 0
    assert not (tmp_path / "wt-contained").exists()       # contained+clean -> pruned
    assert (tmp_path / "wt-dirty").is_dir()               # dirty -> kept
    assert (tmp_path / "wt-uncontained").is_dir()         # uncontained -> kept


# ----- unsafe_to_drop: the teardown/gc safety predicate -----------------------
# Returns a reason string when dropping the card (delete branch / prune worktree)
# would lose work, else None. This is the guard that makes `teardown` and `gc`
# refuse to destroy unlanded/uncommitted work — the hole that an advisory-only
# plan left open.

def test_drop_safe_when_branch_fully_landed_and_clean():
    # unmerged == 0 (all patches in main), not dirty -> safe to delete branch.
    assert unsafe_to_drop(_facts(ahead=3, unmerged=0, dirty=False)) is None


def test_drop_unsafe_when_branch_has_unmerged_commits():
    reason = unsafe_to_drop(_facts(ahead=2, unmerged=2, dirty=False))
    assert reason is not None and "2" in reason


def test_drop_unsafe_when_dirty():
    # dirty dominates even if patches landed: uncommitted work would vanish.
    reason = unsafe_to_drop(_facts(ahead=0, unmerged=0, dirty=True))
    assert reason is not None and "dirty" in reason.lower()


def test_drop_safe_when_detached_contained_in_base():
    # detached worktree whose HEAD is an ancestor of base -> nothing lost.
    f = _facts(name=None, detached=True, contained=True, worktree="/tmp/wt/x")
    assert unsafe_to_drop(f) is None


def test_drop_unsafe_when_detached_not_contained():
    # detached HEAD carries commits not in base: pruning would orphan them.
    f = _facts(name=None, detached=True, contained=False, worktree="/tmp/wt/x")
    reason = unsafe_to_drop(f)
    assert reason is not None and "contain" in reason.lower()


def test_drop_unsafe_when_detached_dirty_even_if_contained():
    f = _facts(name=None, detached=True, contained=True, dirty=True, worktree="/tmp/wt/x")
    reason = unsafe_to_drop(f)
    assert reason is not None and "dirty" in reason.lower()


# ============================================================================
# remote-only branches: refs/remotes/origin/* with NO local counterpart and NO
# worktree (pushed by a cloud session / another machine). The board was blind to
# these — it only scanned refs/heads + detached worktrees — so a freshly pushed
# unmerged cloud branch read as "fully converged" (false-converged). These pin
# the classification + plan + safety contract for that card kind.
# ============================================================================

def test_remote_only_fully_contained_is_merged_not_current():
    # behind main, 0 unique patch: a SEPARATE remote ref fully in main is a
    # redundant ref to delete (MERGED), never CURRENT (which means "is main").
    f = _facts(remote_only=True, ahead=0, behind=115, unmerged=0, has_origin=True)
    assert classify(f) is State.MERGED


def test_remote_only_merged_at_main_tip_is_still_merged():
    # even pointing exactly at main HEAD, a differently-named remote ref is
    # redundant, not CURRENT.
    f = _facts(remote_only=True, ahead=0, behind=0, unmerged=0, has_origin=True)
    assert classify(f) is State.MERGED


def test_remote_only_unmerged_behind_is_stale_base():
    # cloud branch with unique commits on an older base -> needs rebase to land.
    f = _facts(remote_only=True, ahead=8, behind=72, unmerged=8, has_origin=True)
    assert classify(f) is State.STALE_BASE


def test_remote_only_unmerged_ontop_is_ahead():
    f = _facts(remote_only=True, ahead=8, behind=0, unmerged=8, has_origin=True)
    assert classify(f) is State.AHEAD


def test_remote_only_recent_unique_work_flagged_live():
    # a recently pushed cloud branch with unique work may be an active session;
    # _is_live should flag it even though it has no local worktree -> FREEZE.
    f = _facts(remote_only=True, ahead=1, unmerged=1, head_recent=True, has_origin=True)
    assert suggest_disposition(State.AHEAD, f) is Mark.FREEZE


def test_remote_only_unmerged_is_unsafe_to_drop():
    reason = unsafe_to_drop(_facts(remote_only=True, ahead=8, unmerged=8))
    assert reason is not None and "8" in reason


def test_remote_only_contained_is_safe_to_drop():
    assert unsafe_to_drop(_facts(remote_only=True, ahead=0, unmerged=0)) is None


def test_remote_only_white_plan_deletes_remote_without_local_branch():
    # WHITE on a remote-only card must NOT `git branch -D` (no local branch) and
    # MUST delete the remote ref.
    card = MODULE.build_card(_facts(
        name="claude/x", remote_only=True, ahead=0, behind=10, unmerged=0, has_origin=True,
    ))
    steps = "\n".join(MODULE.plan_actions(card, Mark.WHITE))
    assert "branch -D" not in steps
    assert "push origin --delete claude/x" in steps


# ============================================================================
# integration: gather_facts + teardown must SEE and act on remote-only branches.
# ============================================================================
def _make_remote_only(repo, name, *, merged):
    """Create branch `name`, push to origin, then delete the local ref so origin
    carries it with no local counterpart. merged=True -> its patch is in main."""
    _git(["checkout", "-q", "-b", name], repo)
    fn = name.replace("/", "_")
    (repo / fn).write_text(fn + "\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", f"commit for {name}"], repo)
    _git(["push", "-q", "origin", name], repo)
    if merged:
        _git(["checkout", "-q", "main"], repo)
        _git(["merge", "-q", "--no-ff", name, "-m", f"merge {name}"], repo)
        _git(["push", "-q", "origin", "main"], repo)
    _git(["checkout", "-q", "main"], repo)
    _git(["branch", "-qD", name], repo)  # drop local ref -> remote-only


@pytestmark_git
def test_gather_facts_surfaces_remote_only_branch(scratch):
    tmp_path, repo = scratch
    _make_remote_only(repo, "cloud/unmerged", merged=False)
    facts = MODULE.gather_facts(base="main", live_window_seconds=7200)
    by_name = {f.get("name"): f for f in facts}
    assert "cloud/unmerged" in by_name, "remote-only branch must appear as a card"
    card = by_name["cloud/unmerged"]
    assert card["remote_only"] is True
    assert card["unmerged"] >= 1          # unique commit not in main
    assert card["worktree"] is None
    # and it must NOT be double-counted as a local branch
    assert "cloud/unmerged" not in _local_branches(repo)


@pytestmark_git
def test_local_branch_not_double_counted_as_remote_only(scratch):
    # `landed` is a local branch tracking origin/landed; it must be ONE card,
    # not also a phantom remote-only card.
    tmp_path, repo = scratch
    facts = MODULE.gather_facts(base="main", live_window_seconds=7200)
    landed = [f for f in facts if f.get("name") == "landed"]
    assert len(landed) == 1
    assert landed[0]["remote_only"] is False


@pytestmark_git
def test_teardown_remote_only_deletes_remote_without_local(scratch):
    tmp_path, repo = scratch
    _make_remote_only(repo, "cloud/merged", merged=True)
    assert "cloud/merged" in _remote_branches(repo)
    assert "cloud/merged" not in _local_branches(repo)
    rc = MODULE.main(["teardown", "--branches", "cloud/merged", "--commit", "--no-fetch"])
    assert rc == 0
    assert "cloud/merged" not in _remote_branches(repo)   # remote ref deleted


@pytestmark_git
def test_teardown_refuses_unmerged_remote_only(scratch):
    tmp_path, repo = scratch
    _make_remote_only(repo, "cloud/wip", merged=False)
    rc = MODULE.main(["teardown", "--branches", "cloud/wip", "--commit", "--no-fetch"])
    assert rc == MODULE.EXIT_USAGE                          # unmerged -> refused
    assert "cloud/wip" in _remote_branches(repo)            # untouched
