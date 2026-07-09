"""Integration tests for ops/worktree_registry.py against real scratch git repos.

Two things get exercised end-to-end (no synthetic facts — the pure verdicts live in
P1 ops/lib/worktree_state.py and are unit-tested there):

  1. TREE-DIFF CONTAINMENT (`landed_in_base`) — the anti-`git cherry` core. Three
     cases, including a squash-merge where `git cherry` reports FALSE unmerged but
     tree-diff correctly says landed.
  2. `sweep` — the orphan sentinel: landed+clean → propose clear; dirty → refuse;
     unlanded-unique → refuse+keep; untracked worktree → flag; stale-entry → strike.
     Plus register/list/resolve ledger state-machine basics.

git-backed; opt-skipped if git is absent.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "worktree_registry", ROOT / "ops" / "worktree_registry.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

landed_in_base = MODULE.landed_in_base

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")

# far-future 'now' so nothing is ever flagged LIVE by accident; belt-and-suspenders
# with --live-window 0 in sweep invocations.
FUTURE_AT = "2999-01-01T00:00:00Z"


def _git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout.strip()


def _git_rc(args, cwd):
    p = subprocess.run(["git", *args], cwd=str(cwd),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout.strip()


def _init(repo):
    repo.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "f").write_text("base\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "base"], repo)


def _local_branches(repo):
    return set(_git(["for-each-ref", "--format=%(refname:short)", "refs/heads"], repo).split())


def _remote_branches(repo):
    out = _git(["ls-remote", "--heads", "origin"], repo)
    return {ln.split("refs/heads/")[-1] for ln in out.splitlines() if ln}


# ============================================================================
# 1. TREE-DIFF CONTAINMENT — landed_in_base (the anti-git-cherry core)
# ============================================================================
@pytest.fixture
def treecase(tmp_path):
    """A repo set up so all three containment cases are reachable from one main."""
    repo = tmp_path / "tc"
    _init(repo)
    prev = Path.cwd()
    os.chdir(repo)
    try:
        yield repo
    finally:
        os.chdir(prev)


def test_containment_A_ancestor_is_landed(treecase):
    repo = treecase
    # branch off main, commit, fast-forward main onto it, then advance main further:
    # the branch HEAD is now a strict ancestor of main -> landed.
    _git(["checkout", "-q", "-b", "ff"], repo)
    (repo / "x").write_text("x\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", "X"], repo)
    _git(["checkout", "-q", "main"], repo)
    _git(["merge", "-q", "ff"], repo)                      # ff: main now contains X
    (repo / "z").write_text("z\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", "Z"], repo)
    assert landed_in_base("main", "ff") is True


def test_containment_B_squash_merge_is_landed_though_cherry_lies(treecase):
    repo = treecase
    # branch `sq` with TWO commits; main absorbs them as ONE squashed commit with
    # identical final content. git cherry compares each branch commit's patch-id and
    # finds no single main commit matching -> reports both as '+' (FALSE unmerged).
    # tree-diff compares the cumulative trees -> correctly landed.
    _git(["checkout", "-q", "-b", "sq"], repo)
    (repo / "s").write_text("line1\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", "s1"], repo)
    (repo / "s").write_text("line1\nline2\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", "s2"], repo)
    _git(["checkout", "-q", "main"], repo)
    (repo / "s").write_text("line1\nline2\n"); _git(["add", "-A"], repo)
    _git(["commit", "-qm", "squash of sq"], repo)          # one commit, same content

    # prove the trap: git cherry reports the branch as NOT landed (>=1 '+').
    cherry = _git(["cherry", "main", "sq"], repo)
    plus = [ln for ln in cherry.splitlines() if ln.startswith("+")]
    assert len(plus) >= 1, "precondition: git cherry must FALSELY report unmerged"

    # tree-diff gets it right.
    assert landed_in_base("main", "sq") is True


def test_containment_C_unique_work_is_not_landed(treecase):
    repo = treecase
    _git(["checkout", "-q", "-b", "uniq"], repo)
    (repo / "u").write_text("only-on-branch\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", "U"], repo)
    _git(["checkout", "-q", "main"], repo)
    assert landed_in_base("main", "uniq") is False


def test_containment_deletion_not_absorbed_is_not_landed(treecase):
    repo = treecase
    # branch deletes f; base still has f -> the deletion is NOT contained.
    _git(["checkout", "-q", "-b", "del"], repo)
    (repo / "f").unlink(); _git(["add", "-A"], repo); _git(["commit", "-qm", "rm f"], repo)
    _git(["checkout", "-q", "main"], repo)
    assert landed_in_base("main", "del") is False


# ============================================================================
# 2. sweep + ledger state machine
# ============================================================================
@pytest.fixture
def sweep_repo(tmp_path):
    """A repo + bare origin with a spread of worktrees/branches covering every
    sweep disposition. Chdir into it. Returns (tmp_path, repo, state_path)."""
    repo = tmp_path / "repo"
    _init(repo)
    remote = tmp_path / "remote.git"
    _git(["init", "-q", "--bare", str(remote)], repo)
    _git(["remote", "add", "origin", str(remote)], repo)
    _git(["push", "-q", "origin", "main"], repo)
    base_sha = _git(["rev-parse", "HEAD"], repo)

    # --- landed-ff: commit, ff into main, keep branch, push to origin -> landed+clean
    _git(["checkout", "-q", "-b", "landed-ff"], repo)
    (repo / "lf").write_text("lf\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", "LF"], repo)
    _git(["push", "-q", "-u", "origin", "landed-ff"], repo)
    _git(["checkout", "-q", "main"], repo)
    _git(["merge", "-q", "landed-ff"], repo)

    # --- squashed: two commits absorbed into main as one squashed commit -> landed
    #     (tree-diff), not pushed, UNREGISTERED (covers untracked + squash-in-sweep)
    _git(["checkout", "-q", "-b", "squashed"], repo)
    (repo / "sq").write_text("a\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", "sq1"], repo)
    (repo / "sq").write_text("a\nb\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", "sq2"], repo)
    _git(["checkout", "-q", "main"], repo)
    (repo / "sq").write_text("a\nb\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", "squash sq"], repo)

    # --- dirty: landed branch whose worktree has an uncommitted change -> DIRTY
    _git(["checkout", "-q", "-b", "dirty-b"], repo)
    (repo / "db").write_text("db\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", "DB"], repo)
    _git(["checkout", "-q", "main"], repo)
    _git(["merge", "-q", "dirty-b"], repo)

    # --- unlanded: unique work not in main, clean -> ACTIVE/DIVERGED (unsafe)
    _git(["checkout", "-q", "-b", "unlanded"], repo)
    (repo / "un").write_text("unique-real-work\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", "UN"], repo)
    _git(["checkout", "-q", "main"], repo)

    # worktrees for the branch subjects
    _git(["worktree", "add", "-q", str(tmp_path / "wt-landed-ff"), "landed-ff"], repo)
    _git(["worktree", "add", "-q", str(tmp_path / "wt-squashed"), "squashed"], repo)
    _git(["worktree", "add", "-q", str(tmp_path / "wt-dirty"), "dirty-b"], repo)
    (tmp_path / "wt-dirty" / "scratch").write_text("uncommitted\n")   # make it dirty
    _git(["worktree", "add", "-q", str(tmp_path / "wt-unlanded"), "unlanded"], repo)
    # detached orphan worktree pinned at the base commit (contained+clean)
    _git(["worktree", "add", "-q", "--detach", str(tmp_path / "wt-orphan"), base_sha], repo)

    # ledger: register the two CLEAR-eligible tracked worktrees + one stale ghost.
    state_path = tmp_path / "registry.json"
    common = ["--state", str(state_path), "--at", FUTURE_AT]
    MODULE.main(["register", *common, "--path", str(tmp_path / "wt-landed-ff"),
                 "--branch", "landed-ff", "--intent", "landed via ff", "--base", "main"])
    # ghost: an active record whose worktree path never exists -> stale-entry
    MODULE.main(["register", *common, "--path", str(tmp_path / "wt-ghost-GONE"),
                 "--branch", "ghost", "--intent", "crashed session", "--base", "main"])

    prev = Path.cwd()
    os.chdir(repo)
    try:
        yield tmp_path, repo, state_path
    finally:
        os.chdir(prev)


def _sweep_json(state_path, *extra):
    """Run sweep --json (dry-run unless --commit in extra) and return parsed payload
    from stdout. Returns (rc, payload)."""
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = MODULE.main(["sweep", "--state", str(state_path), "--at", FUTURE_AT,
                          "--live-window", "0", "--no-fetch", "--json", *extra])
    return rc, json.loads(buf.getvalue())


def _by_label(cards):
    return {c["label"]: c for c in cards}


def test_sweep_dryrun_classifies_every_disposition(sweep_repo):
    tmp_path, repo, state_path = sweep_repo
    rc, payload = _sweep_json(state_path)
    assert rc == MODULE.EXIT_OK
    assert payload["schema"] == "kg.worktree.registry.v1"
    assert payload["mode"] == "dry-run"

    clear = _by_label(payload["clear"])
    keep = _by_label(payload["keep"])

    # landed+clean tracked worktree -> CLEAR
    assert "landed-ff" in clear
    assert clear["landed-ff"]["untracked"] is False

    # squash-merged worktree -> landed via tree-diff -> CLEAR, and UNTRACKED-flagged
    assert "squashed" in clear
    assert clear["squashed"]["landed"] is True
    assert clear["squashed"]["untracked"] is True

    # detached orphan (contained + clean) -> CLEAR
    orphan = [lbl for lbl in clear if lbl.startswith("(detached")]
    assert orphan, "contained clean detached worktree should be CLEAR"

    # dirty -> KEEP (refused: uncommitted work)
    assert "dirty-b" in keep
    assert keep["dirty-b"]["state"] == "DIRTY"
    assert "dirty" in keep["dirty-b"]["unsafe"].lower()

    # unlanded unique -> KEEP (refused: unlanded commits)
    assert "unlanded" in keep
    assert keep["unlanded"]["unsafe"] is not None
    assert keep["unlanded"]["landed"] is False

    # stale-entry: registered but worktree gone
    stale = {s["branch"] for s in payload["stale_entries"]}
    assert "ghost" in stale


def test_sweep_dryrun_mutates_nothing(sweep_repo):
    tmp_path, repo, state_path = sweep_repo
    before_local = _local_branches(repo)
    before_remote = _remote_branches(repo)
    _sweep_json(state_path)  # dry-run
    assert _local_branches(repo) == before_local
    assert _remote_branches(repo) == before_remote
    assert (tmp_path / "wt-landed-ff").is_dir()
    assert (tmp_path / "wt-orphan").is_dir()
    # ledger ghost still active (not struck on dry-run)
    recs = {r["branch"]: r for r in json.loads(state_path.read_text())["records"]}
    assert recs["ghost"]["status"] == "active"


def test_sweep_commit_clears_safe_keeps_unsafe_strikes_stale(sweep_repo):
    tmp_path, repo, state_path = sweep_repo
    rc = MODULE.main(["sweep", "--state", str(state_path), "--at", FUTURE_AT,
                      "--live-window", "0", "--no-fetch", "--commit"])
    assert rc == MODULE.EXIT_OK

    local = _local_branches(repo)
    remote = _remote_branches(repo)

    # CLEAR executed: landed-ff local + remote deleted, worktree removed
    assert "landed-ff" not in local
    assert "landed-ff" not in remote
    assert not (tmp_path / "wt-landed-ff").exists()

    # CLEAR executed: squashed local deleted, worktree removed (never had a remote)
    assert "squashed" not in local
    assert not (tmp_path / "wt-squashed").exists()

    # CLEAR executed: detached orphan worktree pruned
    assert not (tmp_path / "wt-orphan").exists()

    # KEEP honored: dirty + unlanded untouched (branch + worktree survive)
    assert "dirty-b" in local
    assert (tmp_path / "wt-dirty").is_dir()
    assert "unlanded" in local
    assert (tmp_path / "wt-unlanded").is_dir()

    # stale ghost entry struck -> abandoned
    recs = {r["branch"]: r for r in json.loads(state_path.read_text())["records"]}
    assert recs["ghost"]["status"] == "abandoned"
    assert recs["ghost"]["resolved_at"] is not None


def test_sweep_untracked_worktree_is_flagged(sweep_repo):
    # squashed was never registered -> it must carry the untracked flag even though
    # its disposition is CLEAR (landed+clean). This is the "manual/crash residue"
    # signal an operator needs.
    tmp_path, repo, state_path = sweep_repo
    _, payload = _sweep_json(state_path)
    squashed = _by_label(payload["clear"])["squashed"]
    assert squashed["untracked"] is True


# ---- ledger state machine: register / list / resolve -----------------------
def test_register_list_resolve_roundtrip(tmp_path):
    state = tmp_path / "reg.json"
    common = ["--state", str(state), "--at", "2026-07-09T12:00:00Z"]

    assert MODULE.main(["register", *common, "--path", str(tmp_path / "wt-a"),
                        "--branch", "feat-a", "--intent", "thing", "--base", "main"]) == 0
    data = json.loads(state.read_text())
    assert data["schema"] == "kg.worktree.registry.v1"
    rec = data["records"][0]
    assert rec["branch"] == "feat-a" and rec["status"] == "active"
    assert rec["created_at"].startswith("2026-07-09T12:00:00")
    assert rec["resolved_at"] is None

    # re-register same branch = idempotent upsert (still ONE record), intent refreshed
    assert MODULE.main(["register", *common, "--path", str(tmp_path / "wt-a"),
                        "--branch", "feat-a", "--intent", "thing v2", "--base", "main"]) == 0
    data = json.loads(state.read_text())
    assert len(data["records"]) == 1
    assert data["records"][0]["intent"] == "thing v2"

    # resolve -> merged with a resolved_at timestamp
    assert MODULE.main(["resolve", *common, "--branch", "feat-a", "--status", "merged"]) == 0
    rec = json.loads(state.read_text())["records"][0]
    assert rec["status"] == "merged"
    assert rec["resolved_at"].startswith("2026-07-09T12:00:00")


def test_resolve_missing_record_is_usage_error(tmp_path):
    state = tmp_path / "reg.json"
    rc = MODULE.main(["resolve", "--state", str(state), "--branch", "nope", "--status", "abandoned"])
    assert rc == MODULE.EXIT_USAGE


def test_resolve_rejects_bad_status(tmp_path):
    state = tmp_path / "reg.json"
    MODULE.main(["register", "--state", str(state), "--at", "2026-07-09T12:00:00Z",
                 "--path", str(tmp_path / "w"), "--branch", "b", "--intent", "i", "--base", "main"])
    # argparse choices reject "active" as a resolve status (SystemExit(2)).
    with pytest.raises(SystemExit):
        MODULE.main(["resolve", "--state", str(state), "--branch", "b", "--status", "active"])


def test_list_json_reports_live_state_for_active(sweep_repo):
    tmp_path, repo, state_path = sweep_repo
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = MODULE.main(["list", "--state", str(state_path), "--at", FUTURE_AT,
                          "--live-window", "0", "--json"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    recs = {r["branch"]: r for r in payload["records"]}
    # landed-ff active record surfaces a live classify + landed=True
    assert recs["landed-ff"]["status"] == "active"
    assert recs["landed-ff"]["landed"] is True
    assert "live_state" in recs["landed-ff"]
    # ghost record's worktree is gone -> worktree_present False
    assert recs["ghost"]["worktree_present"] is False
