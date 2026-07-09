"""Tests for ops/worktree_orchestrate.py — the P3 worktree orchestrator primitive.

Two tiers, mirroring the rest of ops/tests:

  1. PURE layer (no git, no IO): intent→branch-type classification and the
     impact→gate mapping (`plan_gates`). The gate mapping is the one real piece of
     judgement the orchestrator owns; it is asserted here as a contract so the set
     of gates selected for a given changed-file list can never silently drift. It
     never actually runs an iOS build.
  2. INTEGRATION (git-backed scratch repo): the full birth→cutover→resolve loop —
     open (worktree add + registry register) → a mock work commit → gate (verdict
     pass; no impact gates for a neutral file) → cutover (rebase + ff push to main)
     → resolve (worktree remove + branch -D + ledger closure). Asserts the worktree
     is gone, the branch is gone, origin/main advanced, and the ledger record reads
     merged — i.e. NO residue.

git-backed tests opt-skip if git is absent.
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
    "worktree_orchestrate", ROOT / "ops" / "worktree_orchestrate.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

classify_intent = MODULE.classify_intent
branch_for = MODULE.branch_for
plan_gates = MODULE.plan_gates
aggregate_verdict = MODULE.aggregate_verdict


def _names(gates):
    return {g["name"] for g in gates}


def _by_name(gates):
    return {g["name"]: g for g in gates}


# ============================================================================
# PURE: intent classification
# ============================================================================
@pytest.mark.parametrize("text", [
    "fix the crash in the reader",
    "debug the flaky sync test",
    "reader hangs on open — bug",
    "investigate why the review flip stutters and fix it",
])
def test_intent_debug(text):
    assert classify_intent(text) == "debug"


@pytest.mark.parametrize("text", [
    "research how Apple Books paginates",
    "investigate the podcast pipeline latency",  # investigate w/o fix -> research
    "audit the docs registry coverage",
    "explore options for the KG layout",
])
def test_intent_research(text):
    assert classify_intent(text) == "research"


@pytest.mark.parametrize("text", [
    "add a share sheet to the notebook",
    "implement per-book podcast covers",
    "build the explore tab",
])
def test_intent_feat(text):
    assert classify_intent(text) == "feat"


@pytest.mark.parametrize("text", [
    # nit4: a bare noun-phrase (no leading imperative verb) is a feature, even when it
    # CONTAINS a research noun — an article introduces a noun phrase, not a research
    # imperative. Previously "the explore tab" mis-classified as research because the
    # filler-skip walked past "the" and hit the "explore" noun.
    "the explore tab",
    "the audit log view",
    "a research summary card",
    "the survey results screen",
    "the review checklist",
])
def test_intent_bare_noun_phrase_is_feat(text):
    assert classify_intent(text) == "feat"


def test_branch_for_composes_type_and_slug():
    assert branch_for("fix the reader crash", "reader-crash") == "debug/reader-crash"
    assert branch_for("add a share sheet", "share-sheet") == "feat/share-sheet"
    assert branch_for("research pagination", "pagination-study") == "research/pagination-study"


# ============================================================================
# PURE: impact -> gate plan (the orchestrator's one real judgement)
# ============================================================================
def test_gate_plan_ios_ui_change_selects_full_ios_set():
    gates = plan_gates(["ios/BooksAndVocab/Reader/ReaderView.swift"])
    names = _names(gates)
    # sim green != Catalyst green -> both build variants
    assert "ios-build" in names
    assert "ios-build-catalyst" in names
    # a swift change -> quality impact is consulted
    assert "ios-quality-impact" in names
    # a View -> UI-scoped test in addition to unit
    assert "ios-test-unit" in names
    assert "ios-test-ui" in names
    # a pure-ios path is NOT a design-system change
    assert "design-system" not in names


def test_gate_plan_ios_models_change_also_triggers_design_system():
    # ios/BooksAndVocab/Models/ is inside the design-system pre-commit pattern
    # (token drift) — so a Models change fans out to BOTH the iOS gates and the
    # design-system gate, but is not a UI-view change (no ios-test-ui).
    gates = plan_gates(["ios/BooksAndVocab/Models/Card.swift"])
    names = _names(gates)
    assert "ios-build" in names and "ios-build-catalyst" in names
    assert "design-system" in names
    assert "ios-test-ui" not in names


def test_gate_plan_design_system_only():
    gates = plan_gates(["design-system/tokens/color.json"])
    names = _names(gates)
    assert names == {"design-system"}
    assert _by_name(gates)["design-system"]["level"] == "block"


def test_gate_plan_generated_css_triggers_design_system():
    gates = plan_gates(["backend/static/kg-tokens.css"])
    assert "design-system" in _names(gates)


def test_gate_plan_docs_change_selects_lint_conflict_and_verified():
    gates = plan_gates(["docs/reference/tech_index.md"])
    names = _names(gates)
    assert "docs-lint" in names
    assert "docs-conflict-markers" in names
    assert "docs-verified-against" in names
    assert _by_name(gates)["docs-verified-against"]["level"] == "warn"


def test_gate_plan_backend_test_file_runs_targeted_pytest():
    gates = plan_gates(["backend/tests/test_app.py"])
    g = _by_name(gates)
    assert "backend-pytest" in g
    spec = g["backend-pytest"]
    assert spec["cwd"] == "backend"
    # targeted at the changed test file (path made backend-relative), never full suite
    assert any("tests/test_app.py" in part for part in spec["cmd"])
    assert "backend-tests-advisory" not in g


def test_gate_plan_backend_src_only_is_advisory_warn_not_full_suite():
    # honours the "don't run the full backend suite (36 pre-existing false fails)"
    # rule: a src-only change with no targeted test in the diff is a WARN advisory.
    gates = plan_gates(["backend/src/kg/app.py"])
    g = _by_name(gates)
    assert "backend-tests-advisory" in g
    assert g["backend-tests-advisory"]["level"] == "warn"
    assert "backend-pytest" not in g


def test_gate_plan_neutral_file_selects_nothing():
    assert plan_gates(["README.md"]) == []
    assert plan_gates(["notes.txt"]) == []
    assert plan_gates([]) == []


# ============================================================================
# PURE: verdict aggregation
# ============================================================================
def test_verdict_empty_is_pass():
    assert aggregate_verdict([]) == "pass"


def test_verdict_all_pass():
    assert aggregate_verdict([{"status": "pass"}, {"status": "pass"}]) == "pass"


def test_verdict_warn_dominates_pass():
    assert aggregate_verdict([{"status": "pass"}, {"status": "warn"}]) == "warn"


def test_verdict_block_dominates_all():
    assert aggregate_verdict([{"status": "warn"}, {"status": "block"}]) == "block"
    assert aggregate_verdict([{"status": "pass"}, {"status": "block"}]) == "block"


# ============================================================================
# INTEGRATION: the full open -> gate -> cutover -> resolve loop
# ============================================================================
gitmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def _git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout.strip()


def _local_branches(repo):
    return set(_git(["for-each-ref", "--format=%(refname:short)", "refs/heads"], repo).split())


def _origin_main_files(remote):
    # list files in the tip tree of origin's main
    out = _git(["ls-tree", "-r", "--name-only", "main"], remote)
    return set(out.splitlines())


@pytest.fixture
def scratch(tmp_path):
    """A repo with a bare origin, main pushed. Chdir into the repo (the orchestrator
    derives repo_root + registry state from cwd's git context)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "f").write_text("base\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "base"], repo)

    remote = tmp_path / "remote.git"
    _git(["init", "-q", "--bare", str(remote)], repo)
    _git(["remote", "add", "origin", str(remote)], repo)
    _git(["push", "-q", "origin", "main"], repo)

    prev = Path.cwd()
    os.chdir(repo)
    try:
        yield tmp_path, repo, remote
    finally:
        os.chdir(prev)


def _run_json(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = MODULE.main(argv)
    text = buf.getvalue()
    payload = json.loads(text) if text.strip() else {}
    return rc, payload


@gitmark
def test_open_cutover_resolve_roundtrip_leaves_no_residue(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")

    # --- open: worktree add + registry register ---
    rc, opened = _run_json(
        ["open", "--intent", "fix the reader crash", "--slug", "reader-crash",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK
    assert opened["branch"] == "debug/reader-crash"
    wt = opened["path"]
    assert Path(wt).is_dir()
    assert "reader-crash" in {r["branch"].split("/")[-1] for r in
                              json.loads(Path(state).read_text())["records"]}

    # --- mock work: a commit touching a NEUTRAL file (matches no impact gate) ---
    (Path(wt) / "notes.txt").write_text("did the thing\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)

    # --- gate: neutral change -> no impact gates -> verdict pass ---
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["schema"] == "kg.worktree.gate.v1"
    assert gate["verdict"] == "pass"
    assert gate["gates"] == []
    assert "notes.txt" in gate["changed_files"]
    # gate wrote a verdict cache beside the ledger (nit3 will strike it on resolve).
    gate_cache = MODULE._gate_record_path(state, wt)
    assert gate_cache.exists()

    # --- cutover: rebase onto origin/main + ff push sha:main (--commit) ---
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert cut["pushed"] is True
    # origin/main now carries the work
    assert "notes.txt" in _origin_main_files(remote)

    # --- resolve: teardown worktree + branch, close the ledger ---
    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK

    # NO residue: worktree gone, local branch gone, gate-record cache struck (nit3)
    assert not Path(wt).exists()
    assert "debug/reader-crash" not in _local_branches(repo)
    assert res.get("gate_cache_removed") is True
    assert not gate_cache.exists()
    # ledger record struck to merged
    recs = {r["branch"]: r for r in json.loads(Path(state).read_text())["records"]}
    assert recs["debug/reader-crash"]["status"] == "merged"
    assert recs["debug/reader-crash"]["resolved_at"] is not None


@gitmark
def test_cutover_refused_without_a_passing_gate(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "add share sheet", "--slug", "share-sheet",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("x\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work"], wt)

    # cutover WITHOUT running gate first -> refused (no verdict on file)
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["pushed"] is False
    # origin/main did NOT advance
    assert "notes.txt" not in _origin_main_files(remote)


@gitmark
def test_cutover_refused_when_gate_verdict_is_stale(scratch):
    # a gate pass recorded against an OLD head must not authorize a cutover of NEW
    # (ungated) commits.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "fix thing", "--slug", "thing", "--state", state, "--json"]
    )
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("v1\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "v1"], wt)
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert gate["verdict"] == "pass"

    # a NEW commit after the gate ran -> verdict is now stale
    (Path(wt) / "more.txt").write_text("v2\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "v2"], wt)

    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["pushed"] is False


@gitmark
def test_cutover_lands_with_warn_verdict(scratch):
    # nit1: a WARN verdict is advisory — the driving agent owns its disposition, the
    # tool must not hard-refuse it. A backend-src-only change (no targeted test in the
    # diff) plans a WARN advisory gate; cutover --commit must LAND it and record the
    # warning ("landed with warnings: <gate>").
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "add backend endpoint", "--slug", "backend-ep",
         "--state", state, "--json"]
    )
    wt = opened["path"]
    src = Path(wt) / "backend" / "src" / "kg" / "app.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("x = 1\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "backend src"], wt)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["verdict"] == "warn"
    assert "backend-tests-advisory" in {g["name"] for g in gate["gates"]}

    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert cut["pushed"] is True
    assert cut["verdict"] == "warn"
    assert "backend-tests-advisory" in cut["warnings"]
    # the work actually landed on origin/main
    assert "backend/src/kg/app.py" in _origin_main_files(remote)


@gitmark
def test_cutover_refused_when_gate_verdict_is_block(scratch):
    # nit1 (the other edge): a BLOCK verdict must STILL refuse cutover. A docs change
    # with a conflict marker -> docs-conflict-markers blocks -> verdict block -> refused.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    # seed a no-op docs_lint.sh into base so the docs-lint shell gate can run cleanly
    # (the conflict-marker internal gate is what supplies the block).
    lint = repo / "ops" / "docs_lint.sh"
    lint.parent.mkdir(parents=True, exist_ok=True)
    lint.write_text("#!/bin/sh\nexit 0\n")
    lint.chmod(0o755)
    _git(["add", "-A"], repo); _git(["commit", "-qm", "seed docs_lint"], repo)
    _git(["push", "-q", "origin", "main"], repo)

    rc, opened = _run_json(
        ["open", "--intent", "update the reader doc", "--slug", "reader-doc",
         "--state", state, "--json"]
    )
    wt = opened["path"]
    doc = Path(wt) / "docs" / "reference" / "x.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("intro\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> other\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "doc with conflict"], wt)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert gate["verdict"] == "block"

    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["pushed"] is False
    assert "docs/reference/x.md" not in _origin_main_files(remote)


@gitmark
def test_resolve_refused_when_branch_not_landed(scratch):
    # nit2: resolve is a force-discard (worktree remove --force + branch -D). Called
    # out of order (before cutover) it would vaporize unlanded work. It must REFUSE a
    # branch not contained in base (tree-diff), unless --force.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "add share sheet", "--slug", "share-sheet",
         "--state", state, "--json"]
    )
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("unlanded work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "unlanded"], wt)

    # resolve WITHOUT a prior cutover -> branch not landed -> refused, NO teardown.
    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert res.get("landed") is False
    assert Path(wt).exists()                                   # worktree preserved
    assert "feat/share-sheet" in _local_branches(repo)         # branch preserved

    # --force overrides the floor (an operator that accepts the loss).
    rc, res2 = _run_json(
        ["resolve", "--worktree", wt, "--state", state, "--commit", "--force", "--json"]
    )
    assert rc == MODULE.EXIT_OK
    assert not Path(wt).exists()
    assert "feat/share-sheet" not in _local_branches(repo)


@gitmark
def test_open_rejects_non_kebab_slug(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, _ = _run_json(
        ["open", "--intent", "x", "--slug", "Bad_Slug", "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_USAGE


@gitmark
def test_preflight_runs_sweep_and_reports(scratch):
    # preflight = fetch + registry sweep --exclude-current (dry-run default). With a
    # clean scratch repo it should simply report a clean sweep, rc 0.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, pre = _run_json(["preflight", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert pre["schema"] == "kg.worktree.orchestrate.v1"
    assert pre["step"] == "preflight"
    assert "sweep" in pre


@gitmark
def test_resolve_from_inside_the_target_worktree_completes(scratch):
    # Regression: resolve invoked with cwd INSIDE the target worktree used to derive
    # its teardown cwd from repo_root() — the worktree's own toplevel. Step 1
    # (worktree remove) then vaporized that cwd and every remaining step (branch -D,
    # gate-cache strike) crashed with an unhandled FileNotFoundError, leaving a
    # half-resolved state. Standing inside the worktree is the natural place for a
    # working agent, so the full teardown must complete from there.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "fix the reader crash", "--slug", "inside-resolve",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("did the thing\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    rc, _ = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert cut["pushed"] is True
    gate_cache = MODULE._gate_record_path(state, wt)
    assert gate_cache.exists()

    os.chdir(wt)
    try:
        rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    finally:
        os.chdir(repo)

    assert rc == MODULE.EXIT_OK
    assert res["failures"] == 0
    assert not Path(wt).exists()
    assert "debug/inside-resolve" not in _local_branches(repo)
    assert res.get("gate_cache_removed") is True
    assert not gate_cache.exists()
    recs = {r["branch"]: r for r in json.loads(Path(state).read_text())["records"]}
    assert recs["debug/inside-resolve"]["status"] == "merged"


@gitmark
def test_open_from_inside_another_worktree_anchors_at_primary_root(scratch):
    # Regression: open used repo_root() (cwd's toplevel), so opening from inside a
    # linked worktree would NEST the new worktree under it instead of anchoring at
    # the primary root's .claude/worktrees/ like every other flow expects.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, first = _run_json(
        ["open", "--intent", "fix the reader crash", "--slug", "first",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK

    os.chdir(first["path"])
    try:
        rc, second = _run_json(
            ["open", "--intent", "fix the reader crash", "--slug", "second",
             "--state", state, "--json"]
        )
    finally:
        os.chdir(repo)

    assert rc == MODULE.EXIT_OK
    expected = (repo / ".claude" / "worktrees" / "second").resolve()
    assert Path(second["path"]).resolve() == expected


@gitmark
def test_resolve_from_inside_without_state_flag_completes(scratch):
    # The production invocation form (worktree-flow SKILL.md) passes NO --state. That
    # branch of _gate_record_path derives the ledger anchor lazily via the registry's
    # common_anchor() — a cwd-dependent git call. Computed AFTER the teardown loop it
    # runs from a vanished cwd (empty git output → Path("").resolve() → getcwd() →
    # FileNotFoundError), so it must be resolved BEFORE the worktree is removed.
    tmp_path, repo, remote = scratch
    rc, opened = _run_json(
        ["open", "--intent", "fix the reader crash", "--slug", "inside-default-state",
         "--json"]
    )
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("did the thing\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    rc, _ = _run_json(["gate", "--worktree", wt, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, cut = _run_json(["cutover", "--worktree", wt, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert cut["pushed"] is True
    gate_cache = MODULE._gate_record_path(None, wt)
    assert gate_cache.exists()

    os.chdir(wt)
    try:
        rc, res = _run_json(["resolve", "--worktree", wt, "--commit", "--json"])
    finally:
        os.chdir(repo)

    assert rc == MODULE.EXIT_OK
    assert res["failures"] == 0
    assert not Path(wt).exists()
    assert "debug/inside-default-state" not in _local_branches(repo)
    assert res.get("gate_cache_removed") is True
    assert not gate_cache.exists()


# ============================================================================
# INTEGRATION: adopt (register an out-of-band worktree — the bootstrap fallback)
# ============================================================================
@gitmark
def test_adopt_registers_an_out_of_band_worktree(scratch):
    # bare `git worktree add` needs no repo tooling; adopt backfills the ledger so the
    # rest of the flow (gate/cutover/resolve/sweep) sees a born-registered peer.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "oob"
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)
    rc, res = _run_json(["adopt", "--worktree", str(wt), "--intent", "hand-made worktree",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["step"] == "adopt"
    assert res["branch"] == "feat/oob"
    recs = json.loads(Path(state).read_text())["records"]
    mine = [r for r in recs if r["branch"] == "feat/oob"]
    assert len(mine) == 1
    assert mine[0]["status"] == "active"
    assert Path(mine[0]["path"]).resolve() == wt.resolve()


@gitmark
def test_adopt_is_idempotent(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "oob"
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)
    for _ in range(2):
        rc, _res = _run_json(["adopt", "--worktree", str(wt), "--intent", "twice",
                              "--state", state, "--json"])
        assert rc == MODULE.EXIT_OK
    recs = json.loads(Path(state).read_text())["records"]
    assert len([r for r in recs if r["branch"] == "feat/oob"]) == 1


@gitmark
def test_adopt_defaults_to_cwd(scratch):
    # the bootstrap flow is `cd <fresh worktree> && orchestrate adopt --intent ...`
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "oob"
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)
    os.chdir(wt)
    try:
        rc, res = _run_json(["adopt", "--intent", "from inside", "--state", state, "--json"])
    finally:
        os.chdir(repo)
    assert rc == MODULE.EXIT_OK
    assert res["branch"] == "feat/oob"


@gitmark
def test_adopt_refuses_primary_root(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, res = _run_json(["adopt", "--worktree", str(repo), "--intent", "nope",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_USAGE
    assert not (tmp_path / "reg.json").exists() or not json.loads(
        (tmp_path / "reg.json").read_text())["records"]


@gitmark
def test_adopt_refuses_detached_worktree(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "det"
    _git(["worktree", "add", "--detach", str(wt), "main"], repo)
    rc, _res = _run_json(["adopt", "--worktree", str(wt), "--intent", "nope",
                          "--state", state, "--json"])
    assert rc == MODULE.EXIT_USAGE


# ============================================================================
# INTEGRATION: freeze (stop-the-world surgery lock)
# ============================================================================
@gitmark
def test_freeze_status_and_reason_roundtrip(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, st = _run_json(["freeze", "status", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert st["frozen"] is False

    rc, on = _run_json(["freeze", "on", "--reason", "history rewrite in progress",
                        "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, st = _run_json(["freeze", "status", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert st["frozen"] is True
    assert st["reason"] == "history rewrite in progress"

    rc, _off = _run_json(["freeze", "off", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, st = _run_json(["freeze", "status", "--state", state, "--json"])
    assert st["frozen"] is False


@gitmark
def test_freeze_blocks_open_adopt_cutover_until_off(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    # a live worktree from BEFORE the freeze, for the cutover/adopt probes
    rc, opened = _run_json(["open", "--intent", "fix the reader crash",
                            "--slug", "pre-freeze", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]

    rc, _ = _run_json(["freeze", "on", "--reason", "surgery", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK

    rc, res = _run_json(["open", "--intent", "fix the reader crash",
                         "--slug", "during-freeze", "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "surgery" in json.dumps(res)
    rc, _res = _run_json(["adopt", "--worktree", wt, "--intent", "nope",
                          "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    rc, _res = _run_json(["cutover", "--worktree", wt, "--state", state,
                          "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK

    # resolve stays ALLOWED — surgery prep is about draining, not trapping
    rc, _res = _run_json(["freeze", "off", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, _res = _run_json(["open", "--intent", "fix the reader crash",
                          "--slug", "post-freeze", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK


@gitmark
def test_freeze_on_twice_requires_force(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, _ = _run_json(["freeze", "on", "--reason", "first", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, res = _run_json(["freeze", "on", "--reason", "second", "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "first" in json.dumps(res)  # existing reason surfaced, not clobbered
    rc, _ = _run_json(["freeze", "on", "--reason", "second", "--force",
                       "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, st = _run_json(["freeze", "status", "--state", state, "--json"])
    assert st["reason"] == "second"


# ============================================================================
# INTEGRATION: sync-main (guarded ff of the PRIMARY checkout's local main)
# ============================================================================
def _advance_origin_main(tmp_path, repo, name, base="main"):
    """Move origin/main one commit ahead WITHOUT touching the primary's main."""
    wt = tmp_path / f"adv-{name}"
    _git(["worktree", "add", "-b", f"adv-{name}", str(wt), base], repo)
    (wt / f"{name}.txt").write_text("advance\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", f"advance: {name}"], wt)
    _git(["push", "-q", "origin", f"adv-{name}:main"], wt)


@gitmark
def test_sync_main_noop_when_up_to_date(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, res = _run_json(["sync-main", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["verdict"] == "noop"


@gitmark
def test_sync_main_ff_when_strictly_behind(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _advance_origin_main(tmp_path, repo, "one")
    (repo / "stray-untracked.txt").write_text("untracked must not block\n")
    before = _git(["rev-parse", "main"], repo)

    # dry-run: reports the plan, moves nothing
    rc, dry = _run_json(["sync-main", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert dry["verdict"] == "dry-run"
    assert dry["commits"] == 1
    assert _git(["rev-parse", "main"], repo) == before

    rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["verdict"] == "ff"
    assert _git(["rev-parse", "main"], repo) == _git(["rev-parse", "origin/main"], repo)
    assert (repo / "one.txt").exists()  # working tree really moved
    assert (repo / "stray-untracked.txt").exists()  # untouched


@gitmark
def test_sync_main_refuses_dirty_primary(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _advance_origin_main(tmp_path, repo, "two")
    (repo / "f").write_text("tracked modification\n")
    rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "dirty" in json.dumps(res)
    _git(["checkout", "--", "f"], repo)
    rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and res["verdict"] == "ff"


@gitmark
def test_sync_main_refuses_diverged_main(scratch):
    # local main holds a commit origin lacks — NEVER auto-merged/rebased away
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    (repo / "local-only.txt").write_text("unique local work\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "local unique"], repo)
    # fork the advance from origin/main (NOT local main) so the histories truly split
    _git(["fetch", "-q", "origin"], repo)
    _advance_origin_main(tmp_path, repo, "three", base="origin/main")
    rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "cutover" in json.dumps(res)  # points at the right recovery
    # untouched: the unique commit is still local main's tip
    assert (repo / "local-only.txt").exists()


@gitmark
def test_sync_main_refuses_when_frozen(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _advance_origin_main(tmp_path, repo, "four")
    rc, _ = _run_json(["freeze", "on", "--reason", "surgery", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, _res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK


@gitmark
def test_sync_main_refuses_when_primary_not_on_main(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _advance_origin_main(tmp_path, repo, "five")
    _git(["checkout", "-q", "-b", "sidetrack"], repo)
    try:
        rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "sidetrack" in json.dumps(res)
    finally:
        _git(["checkout", "-q", "main"], repo)
