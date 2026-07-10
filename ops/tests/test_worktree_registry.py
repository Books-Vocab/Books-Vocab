"""Integration tests for ops/worktree_registry.py against real scratch git repos.

Two things get exercised end-to-end (no synthetic facts — the pure verdicts live in
P1 ops/lib/worktree_state.py and are unit-tested there):

  1. TREE-DIFF CONTAINMENT (`landed_in_base`) — the anti-`git cherry` core. Three
     cases, including a squash-merge where `git cherry` reports FALSE unmerged but
     tree-diff correctly says landed.
  2. `sweep` — the orphan sentinel, in its CONSERVATIVE shape:
       * base branch + primary worktree are ABSOLUTELY protected (never CLEAR, never
         a teardown command) — the retired converge's "main first, never teardown".
       * CLEAR is confined to three shapes: (a) a dangling landed branch with no
         worktree, (b) a contained+clean detached orphan worktree, (c) a subject a
         registry record already resolved (merged/abandoned). A landed branch that
         still has a checked-out worktree is KEPT (reclaimable, awaiting resolve).
       * a dangling landed branch clears even with a FRESH HEAD (no worktree ⇒ never
         mis-shielded as a LIVE agent).
     Plus register/list/resolve ledger state-machine basics.

git-backed; opt-skipped if git is absent.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
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


def _setup_origin(repo, tmp_path):
    """Give `repo` a bare origin with main pushed. Returns the remote path."""
    remote = tmp_path / "remote.git"
    _git(["init", "-q", "--bare", str(remote)], repo)
    _git(["remote", "add", "origin", str(remote)], repo)
    _git(["push", "-q", "origin", "main"], repo)
    return remote


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
# 2. sweep + ledger state machine (conservative CLEAR + base/primary protection)
# ============================================================================
def _branch_land(repo, name, fname, content, msg):
    """Create `name` off main, commit `content` into `fname`, ff-merge into main.
    Leaves main containing it; the branch ref remains (worktree added separately)."""
    _git(["checkout", "-q", "-b", name], repo)
    (repo / fname).write_text(content); _git(["add", "-A"], repo); _git(["commit", "-qm", msg], repo)
    _git(["checkout", "-q", "main"], repo)
    _git(["merge", "-q", name], repo)


def _branch_squash(repo, name, fname, msg):
    """Create `name` off main with TWO commits, then absorb the same final content
    into main as ONE squash-style commit (tree-diff landed, sha differs)."""
    _git(["checkout", "-q", "-b", name], repo)
    (repo / fname).write_text("a\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", f"{msg}1"], repo)
    (repo / fname).write_text("a\nb\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", f"{msg}2"], repo)
    _git(["checkout", "-q", "main"], repo)
    (repo / fname).write_text("a\nb\n"); _git(["add", "-A"], repo); _git(["commit", "-qm", f"squash {name}"], repo)


def _branch_unique(repo, name, fname, content, msg):
    """Create `name` off main with genuinely unique work NOT absorbed into main."""
    _git(["checkout", "-q", "-b", name], repo)
    (repo / fname).write_text(content); _git(["add", "-A"], repo); _git(["commit", "-qm", msg], repo)
    _git(["checkout", "-q", "main"], repo)


@pytest.fixture
def sweep_repo(tmp_path):
    """A repo + bare origin with a spread of worktrees/branches covering every
    conservative-sweep disposition. origin/main is kept in sync with local main so
    the default `--base origin/main` sees the merges as landed. Chdir into repo.
    Returns (tmp_path, repo, state_path).

    Coverage:
      CLEAR  dangling-landed      landed ff, NO worktree, unregistered      -> (a)
             dangling-landed-reg  landed ff, NO worktree, REGISTERED active -> (a)+nit1
             wt-orphan (detached) detached at base sha, contained+clean     -> (b)
             resolved-merged-wt   landed, worktree PRESENT, record=merged   -> (c)
      KEEP   landed-wt            landed squash, worktree PRESENT, registered (open wt)
             squashed-wt          landed squash, worktree PRESENT, untracked (open wt)
             dirty-wt             landed, worktree PRESENT + uncommitted     (dirty)
             unlanded-wt          unique work, worktree PRESENT              (unlanded)
             dangling-unlanded    unique work, NO worktree                   (unlanded)
             main / primary       base branch + main working tree           (protected)
      STALE  ghost                registered active, worktree+branch gone    -> abandoned
    """
    repo = tmp_path / "repo"
    _init(repo)
    _setup_origin(repo, tmp_path)
    base_sha = _git(["rev-parse", "HEAD"], repo)

    _branch_land(repo, "dangling-landed", "dl", "dl\n", "DL")
    _branch_land(repo, "dangling-landed-reg", "dlr", "dlr\n", "DLR")
    _branch_squash(repo, "landed-wt", "lw", "lw")
    _branch_squash(repo, "squashed-wt", "sq", "sq")
    _branch_land(repo, "dirty-wt", "db", "db\n", "DB")
    _branch_unique(repo, "unlanded-wt", "un", "unique-real-work\n", "UN")
    _branch_unique(repo, "dangling-unlanded", "du", "unique-dangling\n", "DU")
    _branch_land(repo, "resolved-merged-wt", "rm", "rm\n", "RM")

    # sync origin/main so the default base (origin/main) sees the merges as landed.
    _git(["push", "-q", "origin", "main"], repo)

    # worktrees for the branch subjects that need one
    _git(["worktree", "add", "-q", str(tmp_path / "wt-landed"), "landed-wt"], repo)
    _git(["worktree", "add", "-q", str(tmp_path / "wt-squashed"), "squashed-wt"], repo)
    _git(["worktree", "add", "-q", str(tmp_path / "wt-dirty"), "dirty-wt"], repo)
    (tmp_path / "wt-dirty" / "scratch").write_text("uncommitted\n")   # make it dirty
    _git(["worktree", "add", "-q", str(tmp_path / "wt-unlanded"), "unlanded-wt"], repo)
    _git(["worktree", "add", "-q", str(tmp_path / "wt-resolved"), "resolved-merged-wt"], repo)
    # detached orphan worktree pinned at the base commit (contained + clean)
    _git(["worktree", "add", "-q", "--detach", str(tmp_path / "wt-orphan"), base_sha], repo)

    # ledger
    state_path = tmp_path / "registry.json"
    common = ["--state", str(state_path), "--at", FUTURE_AT]
    MODULE.main(["register", *common, "--path", str(tmp_path / "wt-landed"),
                 "--branch", "landed-wt", "--intent", "landed via squash", "--base", "main"])
    # dangling-landed-reg: registered active but its worktree path never existed
    # (branch landed, worktree already removed) -> cleared as (a), record -> merged (nit1)
    MODULE.main(["register", *common, "--path", str(tmp_path / "wt-dlr-GONE"),
                 "--branch", "dangling-landed-reg", "--intent", "landed, wt removed", "--base", "main"])
    # resolved-merged-wt: registered THEN resolved merged -> case (c) even with open wt
    MODULE.main(["register", *common, "--path", str(tmp_path / "wt-resolved"),
                 "--branch", "resolved-merged-wt", "--intent", "resolved", "--base", "main"])
    MODULE.main(["resolve", *common, "--branch", "resolved-merged-wt", "--status", "merged"])
    # ghost: an active record whose worktree path (and branch) never exist -> stale
    MODULE.main(["register", *common, "--path", str(tmp_path / "wt-ghost-GONE"),
                 "--branch", "ghost", "--intent", "crashed session", "--base", "main"])

    prev = Path.cwd()
    os.chdir(repo)
    try:
        yield tmp_path, repo, state_path
    finally:
        os.chdir(prev)


def _sweep_json(state_path, *extra, base=None):
    """Run sweep --json (dry-run unless --commit in extra) and return (rc, payload)."""
    argv = ["sweep", "--state", str(state_path), "--at", FUTURE_AT,
            "--live-window", "0", "--no-fetch", "--json"]
    if base is not None:
        argv += ["--base", base]
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = MODULE.main([*argv, *extra])
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

    # --- CLEAR (the three conservative shapes) ---
    # (a) dangling landed branch, no worktree, unregistered
    assert "dangling-landed" in clear and clear["dangling-landed"]["untracked"] is True
    # (a) dangling landed branch, no worktree, REGISTERED active
    assert "dangling-landed-reg" in clear
    # (b) contained + clean detached orphan worktree
    assert any(lbl.startswith("(detached") for lbl in clear), "detached orphan should CLEAR"
    # (c) registry-resolved (merged) subject, even though its worktree is still present
    assert "resolved-merged-wt" in clear

    # --- KEEP ---
    # base branch / primary worktree are protected
    assert "main" in keep and keep["main"]["protected"] is True
    # landed branch WITH a checked-out worktree -> KEEP (reclaimable, not auto-cleared)
    assert "landed-wt" in keep and keep["landed-wt"]["landed"] is True
    assert "squashed-wt" in keep and keep["squashed-wt"]["untracked"] is True
    # dirty -> KEEP (uncommitted work)
    assert "dirty-wt" in keep and keep["dirty-wt"]["state"] == "DIRTY"
    assert "dirty" in keep["dirty-wt"]["unsafe"].lower()
    # unlanded unique work -> KEEP, whether or not it has a worktree
    assert "unlanded-wt" in keep and keep["unlanded-wt"]["landed"] is False
    assert "dangling-unlanded" in keep and keep["dangling-unlanded"]["landed"] is False

    # stale-entry: registered but worktree + branch gone
    stale = {s["branch"] for s in payload["stale_entries"]}
    assert "ghost" in stale
    # a cleared dangling-landed-reg is NOT reported stale (it resolves to merged, not abandoned)
    assert "dangling-landed-reg" not in stale


def test_landed_branch_with_open_worktree_is_kept(sweep_repo):
    # THE conservative rule: a landed branch that still has a checked-out worktree is
    # NOT auto-cleared (avoid nuking a worktree an agent may still be using) — it is
    # KEPT as reclaimable until explicitly resolved.
    tmp_path, repo, state_path = sweep_repo
    _, payload = _sweep_json(state_path)
    keep = _by_label(payload["keep"])
    for name in ("landed-wt", "squashed-wt"):
        assert name in keep
        assert keep[name]["landed"] is True
        assert keep[name]["disposition"] == "KEEP"


def test_dangling_unlanded_branch_is_kept(sweep_repo):
    # a dangling branch (no worktree) carrying unique unlanded work must never CLEAR.
    tmp_path, repo, state_path = sweep_repo
    _, payload = _sweep_json(state_path)
    keep = _by_label(payload["keep"])
    assert "dangling-unlanded" in keep
    assert keep["dangling-unlanded"]["unsafe"] is not None
    assert keep["dangling-unlanded"]["landed"] is False


def test_sweep_dryrun_mutates_nothing(sweep_repo):
    tmp_path, repo, state_path = sweep_repo
    before_local = _local_branches(repo)
    before_remote = _remote_branches(repo)
    _sweep_json(state_path)  # dry-run
    assert _local_branches(repo) == before_local
    assert _remote_branches(repo) == before_remote
    assert (tmp_path / "wt-landed").is_dir()
    assert (tmp_path / "wt-orphan").is_dir()
    assert repo.is_dir() and (repo / ".git").exists()
    # ledger ghost still active (not struck on dry-run)
    recs = {r["branch"]: r for r in json.loads(state_path.read_text())["records"]}
    assert recs["ghost"]["status"] == "active"


def test_sweep_commit_clears_safe_keeps_unsafe_and_protected(sweep_repo):
    tmp_path, repo, state_path = sweep_repo
    rc = MODULE.main(["sweep", "--state", str(state_path), "--at", FUTURE_AT,
                      "--live-window", "0", "--no-fetch", "--commit"])
    assert rc == MODULE.EXIT_OK

    local = _local_branches(repo)

    # CLEAR executed: dangling landed branches deleted (no worktree to remove)
    assert "dangling-landed" not in local
    assert "dangling-landed-reg" not in local
    # CLEAR executed: detached orphan worktree pruned
    assert not (tmp_path / "wt-orphan").exists()
    # CLEAR executed: registry-resolved branch + its worktree removed
    assert "resolved-merged-wt" not in local
    assert not (tmp_path / "wt-resolved").exists()

    # KEEP honored: landed-with-worktree branches survive (branch + worktree)
    assert "landed-wt" in local and (tmp_path / "wt-landed").is_dir()
    assert "squashed-wt" in local and (tmp_path / "wt-squashed").is_dir()
    # KEEP honored: dirty + unlanded untouched
    assert "dirty-wt" in local and (tmp_path / "wt-dirty").is_dir()
    assert "unlanded-wt" in local and (tmp_path / "wt-unlanded").is_dir()
    assert "dangling-unlanded" in local

    # PROTECTED honored: base branch + primary worktree untouched
    assert "main" in local
    assert repo.is_dir() and (repo / ".git").exists()

    recs = {r["branch"]: r for r in json.loads(state_path.read_text())["records"]}
    # nit1: a cleared registered-active record resolves to merged (NOT abandoned)
    assert recs["dangling-landed-reg"]["status"] == "merged"
    assert recs["dangling-landed-reg"]["resolved_at"] is not None
    # stale ghost entry struck -> abandoned
    assert recs["ghost"]["status"] == "abandoned"
    assert recs["ghost"]["resolved_at"] is not None


def test_sweep_untracked_worktree_is_flagged(sweep_repo):
    # squashed-wt was never registered -> it must carry the untracked flag even though
    # (with an open worktree) its disposition is KEEP. Operator "manual/crash residue"
    # signal. And an unregistered dangling-landed CLEAR is also untracked-flagged.
    tmp_path, repo, state_path = sweep_repo
    _, payload = _sweep_json(state_path)
    keep = _by_label(payload["keep"]); clear = _by_label(payload["clear"])
    assert keep["squashed-wt"]["untracked"] is True
    assert clear["dangling-landed"]["untracked"] is True


# ---- [防自毀硬測試] base branch + primary worktree are NEVER torn down ----------
def test_sweep_never_tears_down_base_branch_or_primary_worktree(tmp_path):
    """Without protection, `main` (the base — landed in itself, HEAD old) classifies
    MERGED and the primary worktree becomes a CLEAR target: sweep would emit
    `git branch -D main` + `git worktree remove <repo>`, destroying the repository.
    Assert sweep KEEPs both and its plan/output contains NO such command — dry-run
    AND --commit — with the DEFAULT base (origin/main)."""
    repo = tmp_path / "repo"
    _init(repo)
    _setup_origin(repo, tmp_path)
    primary = os.path.realpath(repo)
    prev = Path.cwd()
    os.chdir(repo)
    try:
        state = tmp_path / "reg.json"
        # dry-run, JSON — default base (origin/main), NOT passed explicitly.
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = MODULE.main(["sweep", "--state", str(state), "--at", FUTURE_AT,
                              "--live-window", "0", "--no-fetch", "--json"])
        assert rc == MODULE.EXIT_OK
        payload = json.loads(buf.getvalue())

        # main must be KEEP + protected, never a CLEAR candidate
        assert "main" not in {c.get("name") for c in payload["clear"]}
        keep = _by_label(payload["keep"])
        assert "main" in keep and keep["main"]["protected"] is True

        # the machine-readable plan must contain no teardown of main or the primary
        all_cmds = [cmd for p in payload["plan"] for cmd in p["cmds"]]
        for cmd in all_cmds:
            assert "branch -D main" not in cmd
            assert "--delete main" not in cmd
            assert f"worktree remove {primary}" not in cmd

        # dry-run, TEXT — grep the human output for the forbidden commands
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            MODULE.main(["sweep", "--state", str(tmp_path / "reg2.json"), "--at", FUTURE_AT,
                         "--live-window", "0", "--no-fetch"])
        text = buf2.getvalue()
        assert "branch -D main" not in text
        assert f"worktree remove {primary}" not in text

        # --commit must not destroy anything: base branch + primary survive.
        rc2 = MODULE.main(["sweep", "--state", str(state), "--at", FUTURE_AT,
                           "--live-window", "0", "--no-fetch", "--commit"])
        assert rc2 == MODULE.EXIT_OK
        assert "main" in _local_branches(repo)
        assert repo.is_dir() and (repo / ".git").exists()
    finally:
        os.chdir(prev)


# ---- dangling landed stub with a FRESH HEAD clears (no LIVE mis-shield) ---------
def test_fresh_dangling_landed_branch_clears_despite_fresh_head(tmp_path):
    """A dangling landed stub branch (no worktree, landed, clean) with a FRESH HEAD
    (head_age < live_window) must CLEAR — a merge/squash making its HEAD look recent
    must NOT mis-shield it as a running LIVE agent. Contrast: the same freshness WITH
    a checked-out worktree stays KEEP (genuinely LIVE)."""
    repo = tmp_path / "repo"
    _init(repo)
    _setup_origin(repo, tmp_path)

    # landed dangling branch, fresh HEAD, NO worktree
    _branch_land(repo, "fresh-landed", "fl", "fl\n", "FL")
    # landed branch, fresh HEAD, WITH a worktree
    _branch_land(repo, "fresh-wt", "fw", "fw\n", "FW")
    _git(["push", "-q", "origin", "main"], repo)
    _git(["worktree", "add", "-q", str(tmp_path / "wt-fresh"), "fresh-wt"], repo)

    prev = Path.cwd()
    os.chdir(repo)
    try:
        # REAL 'now' (no --at) so the just-made commits sit inside a 7200s live window.
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = MODULE.main(["sweep", "--state", str(tmp_path / "reg.json"),
                              "--live-window", "7200", "--no-fetch", "--json"])
        assert rc == MODULE.EXIT_OK
        payload = json.loads(buf.getvalue())
        clear = _by_label(payload["clear"])
        keep = _by_label(payload["keep"])

        # dangling landed fresh branch (no worktree) -> CLEAR despite fresh HEAD
        assert "fresh-landed" in clear, "fresh HEAD must NOT shield a worktree-less branch as LIVE"
        # landed fresh branch WITH a worktree -> LIVE -> KEEP (has_worktree gate)
        assert "fresh-wt" in keep and keep["fresh-wt"]["state"] == "LIVE"
    finally:
        os.chdir(prev)


# ---- nit2: default base is origin/<base> (local base may lag origin) -----------
def test_sweep_default_base_is_origin_main():
    ns = MODULE.build_parser().parse_args(["sweep"])
    assert ns.base == "origin/main"


# ---- nit4: --json is clearly mode-labelled and reflects execution --------------
def test_json_mode_labels_and_reflects_execution(sweep_repo):
    tmp_path, repo, state_path = sweep_repo
    # dry-run: mode label + a plan, but no executed results
    _, dry = _sweep_json(state_path)
    assert dry["mode"] == "dry-run"
    assert "plan" in dry
    assert "executed" not in dry

    # committed: mode label + executed results reflecting what ran
    buf = io.StringIO()
    with redirect_stdout(buf):
        MODULE.main(["sweep", "--state", str(state_path), "--at", FUTURE_AT,
                     "--live-window", "0", "--no-fetch", "--json", "--commit"])
    committed = json.loads(buf.getvalue())
    assert committed["mode"] == "committed"
    assert "executed" in committed
    assert committed["failures"] == 0
    # every executed step reports success
    assert all(step["ok"] for card in committed["executed"] for step in card["steps"])


# ---- sweep --exclude-current: never self-clear the invoking worktree ----------
def test_sweep_exclude_current_keeps_the_invoking_worktree(tmp_path):
    """A detached, contained+clean worktree normally CLEARs as an orphan (shape b).
    But when `sweep --exclude-current` is invoked FROM that worktree, the worktree
    whose root is the caller's cwd must be force-KEPT (excluded) — so the P3
    orchestrator can run a preflight sweep from any worktree without nuking itself.
    Contrast: from the primary repo the same worktree still CLEARs."""
    repo = tmp_path / "repo"
    _init(repo)
    _setup_origin(repo, tmp_path)
    base_sha = _git(["rev-parse", "HEAD"], repo)
    # a detached, contained, clean orphan worktree — normally CLEAR shape (b)
    selfwt = tmp_path / "wt-self"
    _git(["worktree", "add", "-q", "--detach", str(selfwt), base_sha], repo)
    state = tmp_path / "reg.json"

    # (1) baseline: swept FROM the primary repo, wt-self is a CLEAR candidate.
    prev = Path.cwd()
    os.chdir(repo)
    try:
        _, base_payload = _sweep_json(state)
    finally:
        os.chdir(prev)
    assert any(c["path"] and os.path.realpath(c["path"]) == os.path.realpath(str(selfwt))
               for c in base_payload["clear"]), "baseline: detached orphan should CLEAR from primary"

    # (2) --exclude-current from INSIDE wt-self: it must be KEEP + excluded, never CLEAR.
    os.chdir(selfwt)
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = MODULE.main(["sweep", "--state", str(state), "--at", FUTURE_AT,
                              "--live-window", "0", "--no-fetch", "--json", "--exclude-current"])
        payload = json.loads(buf.getvalue())
    finally:
        os.chdir(prev)
    assert rc == MODULE.EXIT_OK
    self_real = os.path.realpath(str(selfwt))
    assert not any(c["path"] and os.path.realpath(c["path"]) == self_real
                   for c in payload["clear"]), "excluded worktree must NOT be a CLEAR candidate"
    excluded = [k for k in payload["keep"]
                if k["path"] and os.path.realpath(k["path"]) == self_real]
    assert excluded and excluded[0].get("excluded") is True, "self worktree must be KEEP + excluded=True"


def test_sweep_exclude_current_still_clears_other_orphans(tmp_path):
    """--exclude-current only shields the invoking worktree; OTHER orphan worktrees
    still CLEAR. Guards against the flag over-excluding."""
    repo = tmp_path / "repo"
    _init(repo)
    _setup_origin(repo, tmp_path)
    base_sha = _git(["rev-parse", "HEAD"], repo)
    selfwt = tmp_path / "wt-self"
    otherwt = tmp_path / "wt-other"
    _git(["worktree", "add", "-q", "--detach", str(selfwt), base_sha], repo)
    _git(["worktree", "add", "-q", "--detach", str(otherwt), base_sha], repo)
    state = tmp_path / "reg.json"

    prev = Path.cwd()
    os.chdir(selfwt)
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            MODULE.main(["sweep", "--state", str(state), "--at", FUTURE_AT,
                         "--live-window", "0", "--no-fetch", "--json", "--exclude-current"])
        payload = json.loads(buf.getvalue())
    finally:
        os.chdir(prev)
    other_real = os.path.realpath(str(otherwt))
    assert any(c["path"] and os.path.realpath(c["path"]) == other_real
               for c in payload["clear"]), "a different orphan worktree must still CLEAR"


def test_sweep_exclude_current_flag_defaults_false():
    ns = MODULE.build_parser().parse_args(["sweep"])
    assert ns.exclude_current is False


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


def _active(records):
    return [r for r in records if r.get("status") == "active"]


def test_register_collapses_cross_match_no_two_active_share_a_path(tmp_path):
    # A branch-match record and a DISTINCT path-match record can both be active at
    # once (branch feat-p lives at wtA; a re-checkout put feat-q at wtB). Registering
    # feat-q@wtA used to update only the FIRST match (feat-p, moving it to wtA),
    # leaving feat-p@wtA and feat-q@wtA — two active records sharing one path, which
    # `resolve --path` would double-kill. The upsert must collapse ALL matches so the
    # invariant holds: at most one active record per branch AND per path.
    state = tmp_path / "reg.json"
    common = ["--state", str(state), "--at", "2026-07-09T12:00:00Z"]
    wtA, wtB = str(tmp_path / "wtA"), str(tmp_path / "wtB")

    assert MODULE.main(["register", *common, "--path", wtA, "--branch", "feat-p",
                        "--intent", "p", "--base", "main"]) == 0
    assert MODULE.main(["register", *common, "--path", wtB, "--branch", "feat-q",
                        "--intent", "q", "--base", "main"]) == 0
    # now register feat-q AT wtA: collides with feat-q by branch AND feat-p by path
    assert MODULE.main(["register", *common, "--path", wtA, "--branch", "feat-q",
                        "--intent", "q v2", "--base", "main"]) == 0

    records = json.loads(state.read_text())["records"]
    active = _active(records)
    # exactly ONE active record survives, and it is feat-q at wtA
    assert len(active) == 1
    surv = active[0]
    assert surv["branch"] == "feat-q"
    assert MODULE._norm(surv["path"]) == MODULE._norm(wtA)
    assert surv["intent"] == "q v2"
    # no two active records ever share a path or a branch
    assert len({MODULE._norm(r["path"]) for r in active}) == len(active)
    assert len({r["branch"] for r in active}) == len(active)
    # the displaced record is retained as history, terminally closed (not left active)
    displaced = [r for r in records if r["branch"] == "feat-p"]
    assert len(displaced) == 1
    assert displaced[0]["status"] == "abandoned"
    assert displaced[0]["resolved_at"] is not None


def test_register_same_branch_moving_worktrees_leaves_one_active(tmp_path):
    # feat-a moves from wtA to wtB (same branch, new path). Exactly one active record,
    # relocated — the old path must not linger as a second active row.
    state = tmp_path / "reg.json"
    common = ["--state", str(state), "--at", "2026-07-09T12:00:00Z"]
    wtA, wtB = str(tmp_path / "wtA"), str(tmp_path / "wtB")
    assert MODULE.main(["register", *common, "--path", wtA, "--branch", "feat-a",
                        "--intent", "a", "--base", "main"]) == 0
    assert MODULE.main(["register", *common, "--path", wtB, "--branch", "feat-a",
                        "--intent", "a", "--base", "main"]) == 0
    active = _active(json.loads(state.read_text())["records"])
    assert len(active) == 1
    assert MODULE._norm(active[0]["path"]) == MODULE._norm(wtB)


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
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = MODULE.main(["list", "--state", str(state_path), "--at", FUTURE_AT,
                          "--live-window", "0", "--json"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    recs = {r["branch"]: r for r in payload["records"]}
    # landed-wt active record surfaces a live classify + landed=True
    assert recs["landed-wt"]["status"] == "active"
    assert recs["landed-wt"]["landed"] is True
    assert "live_state" in recs["landed-wt"]
    # ghost record's worktree is gone -> worktree_present False
    assert recs["ghost"]["worktree_present"] is False
