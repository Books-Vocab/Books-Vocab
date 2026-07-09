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

    # --- cutover: rebase onto origin/main + ff push sha:main (--commit) ---
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert cut["pushed"] is True
    # origin/main now carries the work
    assert "notes.txt" in _origin_main_files(remote)

    # --- resolve: teardown worktree + branch, close the ledger ---
    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK

    # NO residue: worktree gone, local branch gone
    assert not Path(wt).exists()
    assert "debug/reader-crash" not in _local_branches(repo)
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
