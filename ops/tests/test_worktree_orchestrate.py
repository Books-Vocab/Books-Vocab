"""Tests for ops/worktree_orchestrate.py — the P3 worktree orchestrator primitive.

Two tiers, mirroring the rest of ops/tests:

  1. PURE layer (no git, no IO): intent→branch-type classification and the
     impact→gate mapping (`plan_gates`). The gate mapping is the one real piece of
     judgement the orchestrator owns; it is asserted here as a contract so the set
     of gates selected for a given changed-file list can never silently drift. It
     never actually runs an iOS build.
  2. INTEGRATION (git-backed scratch repo): the full birth→cutover→resolve loop —
     open (worktree add off LOCAL main + registry register) → a mock work commit →
     gate (verdict pass; no impact gates for a neutral file) → cutover (rebase onto
     local main + ff the primary's LOCAL main, offline) → resolve (worktree remove +
     branch -D + ledger closure). Asserts the worktree is gone, the branch is gone,
     LOCAL main advanced (origin untouched — that is the separate deploy), and the
     ledger record reads merged — i.e. NO residue.

git-backed tests opt-skip if git is absent.
"""

from __future__ import annotations

import importlib.util
import ast
import io
import json
import os
import shutil
import subprocess
import sys
import textwrap
from contextlib import redirect_stderr, redirect_stdout
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
def test_gate_plan_real_repo_plans_review_receipts():
    """Iron law 4's mechanical half must be planned for the real repo.

    The gate is skipped when ops/review_audit.sh is absent so synthetic fixture
    repos still work; this pins that the skip cannot quietly become permanent.
    """
    gates = plan_gates(["README.md"], ops_test_exists=lambda rel: True, base="main")
    g = next(x for x in gates if x["name"] == "review-receipts")
    assert g["level"] == "block"
    assert g["cmd"][:2] == ["ops/review_audit.sh", "--rev-range"]
    # and absent when the tool is not there
    assert "review-receipts" not in _names(
        plan_gates(["README.md"], ops_test_exists=lambda rel: False, base="main"))


def test_gate_plan_ios_ui_change_selects_full_ios_set():
    gates = plan_gates(["ios/BooksAndVocab/Reader/ReaderView.swift"])
    names = _names(gates)
    # sim green != Catalyst green -> both build variants
    assert "ios-build" in names
    assert "ios-build-catalyst" in names
    # a swift change -> the static lints actually RUN, as a block gate.
    # `quality impact` used to sit here at warn level, but it delegates to
    # ui_quality_plane's planner: every code path returns 0, so that gate was
    # structurally incapable of failing. It printed which lints *would* apply
    # and went green — the plan mistaken for the check.
    assert "ui-quality-fast" in names
    assert "ios-quality-impact" not in names
    fast = next(g for g in gates if g["name"] == "ui-quality-fast")
    assert fast["level"] == "block"
    assert "--execute" in fast["cmd"]
    # Seconds-scale lints must precede the minutes-scale build, or the feedback
    # delay is swallowed by xcodebuild.
    order = [g["name"] for g in gates]
    assert order.index("ui-quality-fast") < order.index("ios-build")
    assert "ios-test-unit" in names
    # a UI-source change with NO changed UITest file runs NO UI suite: the UI gate
    # is impacted-scope (per changed *Tests.swift class) — the full --ui suite as a
    # block gate false-blocks every iOS cutover on documented flaky tests.
    assert not any(n.startswith("ios-test-ui") for n in names)
    # a pure-ios path is NOT a design-system change
    assert "design-system" not in names


def test_gate_plan_changed_uitest_file_selects_its_ui_class():
    gates = plan_gates(["ios/BooksAndVocabUITests/ReaderFlowTests.swift"])
    names = _names(gates)
    # only the impacted UI test CLASS runs (scoped --file, marketing_demo dataset)
    assert "ios-test-ui:ReaderFlowTests" in names
    # helper/page-object files are not test classes
    gates = plan_gates(["ios/BooksAndVocabUITests/Pages/AppPage.swift"])
    assert not any(n.startswith("ios-test-ui") for n in _names(gates))


def test_gate_plan_live_demo_uitest_compiles_for_device_but_never_runs_fixture_simulator():
    gates = plan_gates(["ios/BooksAndVocabUITests/LiveDemoAccessUITests.swift"])
    by_name = _by_name(gates)

    assert "ios-test-ui:LiveDemoAccessUITests" not in by_name
    compile_gate = by_name["ios-live-demo-uitest-compile"]
    assert compile_gate["level"] == "block"
    assert compile_gate["cmd"] == [
        "ops/ios_ops.sh", "test", "--ui", "--configuration", "Release",
        "--destination", "generic/platform=iOS", "--prepare-cache", "--json",
    ]
    advisory = by_name["ios-live-demo-runtime-advisory"]
    assert advisory["level"] == "warn"
    assert advisory["kind"] == "internal"
    assert "demo-run" in advisory["note"]


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


def test_gate_plan_ops_test_file_runs_itself():
    exists = {"ops/tests/test_capability_matrix.py"}.__contains__
    gates = plan_gates(["ops/tests/test_capability_matrix.py"], ops_test_exists=exists)
    g = _by_name(gates)
    assert "ops-pytest" in g
    spec = g["ops-pytest"]
    assert spec["level"] == "block"
    # runs from the worktree root (no cwd override) with the pinned uv invocation —
    # ops tests are __file__-anchored, backend/uv.lock must not be touched
    assert spec.get("cwd") is None
    assert spec["cmd"][:7] == ["uv", "run", "--no-project", "--python", "3.13",
                               "--with", "pytest"]
    assert "ops/tests/test_capability_matrix.py" in spec["cmd"]
    # targeted — never the whole ops/tests directory when every change maps to a test
    assert "ops/tests" not in spec["cmd"]


def test_gate_plan_ops_deleted_test_file_falls_back_not_pytest_args():
    # a DELETED test file is in the diff too (git diff --name-only) — passing the
    # gone path to pytest would exit 4 (file not found) and false-block; the
    # existence check applies to changed test files as well, missing -> fallback
    gates = plan_gates(["ops/tests/test_gone.py"], ops_test_exists=lambda rel: False)
    spec = _by_name(gates)["ops-pytest"]
    assert "ops/tests/test_gone.py" not in spec["cmd"]
    assert "ops/tests" in spec["cmd"]


def test_gate_plan_ops_src_with_matching_test_runs_it():
    exists = {"ops/tests/test_worktree_orchestrate.py"}.__contains__
    gates = plan_gates(["ops/worktree_orchestrate.py"], ops_test_exists=exists)
    spec = _by_name(gates)["ops-pytest"]
    assert "ops/tests/test_worktree_orchestrate.py" in spec["cmd"]
    assert "ops/tests" not in spec["cmd"]


def test_gate_plan_ops_lib_src_maps_by_basename():
    exists = {"ops/tests/test_worktree_registry.py"}.__contains__
    gates = plan_gates(["ops/lib/worktree_registry.py"], ops_test_exists=exists)
    spec = _by_name(gates)["ops-pytest"]
    assert "ops/tests/test_worktree_registry.py" in spec["cmd"]


def test_gate_plan_ops_src_without_test_falls_back_to_whole_ops_tests():
    # no matching ops/tests/test_X.py -> the whole ops/tests suite (which subsumes
    # any targeted files, so the fallback replaces the target list)
    gates = plan_gates(["ops/no_such_tool.py", "ops/tests/test_capability_matrix.py"],
                       ops_test_exists=lambda rel: False)
    spec = _by_name(gates)["ops-pytest"]
    assert "ops/tests" in spec["cmd"]
    assert "ops/tests/test_capability_matrix.py" not in spec["cmd"]


def test_gate_plan_ops_src_default_predicate_is_conservative_fallback():
    # without an injected existence predicate (pure layer: no IO), an ops src
    # change cannot prove a matching test exists -> whole ops/tests
    gates = plan_gates(["ops/worktree_orchestrate.py"])
    spec = _by_name(gates)["ops-pytest"]
    assert "ops/tests" in spec["cmd"]


def test_gate_plan_ops_src_and_its_test_dedupes_target():
    # the self-referential dogfood shape: tool + its test changed together
    exists = {"ops/tests/test_worktree_orchestrate.py"}.__contains__
    gates = plan_gates(["ops/worktree_orchestrate.py",
                        "ops/tests/test_worktree_orchestrate.py"],
                       ops_test_exists=exists)
    spec = _by_name(gates)["ops-pytest"]
    assert spec["cmd"].count("ops/tests/test_worktree_orchestrate.py") == 1
    assert "ops/tests" not in spec["cmd"]


def test_gate_plan_ops_shell_and_non_ops_select_no_ops_pytest():
    # ops shell scripts are out of scope (no pytest counterpart); docs/backend
    # changes must not leak into the ops route
    assert plan_gates(["ops/devops_kg_safe.sh"]) == []
    assert not any(n == "ops-pytest"
                   for n in _names(plan_gates(["docs/reference/tech_index.md"])))
    assert not any(n == "ops-pytest"
                   for n in _names(plan_gates(["backend/tests/test_app.py"])))


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


def test_streamed_gate_runner_heartbeats_to_stderr_and_keeps_stdout_pure(tmp_path):
    stdout = io.StringIO()
    stderr = io.StringIO()
    command = [
        sys.executable,
        "-c",
        "import time; print('first', flush=True); time.sleep(.08); print('last')",
    ]

    with redirect_stdout(stdout), redirect_stderr(stderr):
        rc, tail = MODULE._run_streamed_command(
            command,
            cwd=tmp_path,
            gate_name="slow-gate",
            heartbeat_interval=0.02,
        )

    progress = stderr.getvalue()
    assert rc == 0
    assert stdout.getvalue() == ""
    assert "gate=slow-gate phase=start" in progress
    assert "phase=heartbeat" in progress
    assert "elapsed=" in progress
    assert "pid=" in progress
    assert "alive=true" in progress
    assert "phase=done" in progress
    assert "rc=0" in progress
    assert tail.splitlines()[-1] == "last"


def test_streamed_gate_runner_bounds_capture_and_preserves_nonzero_exit(tmp_path):
    stderr = io.StringIO()
    command = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('x' * 200000 + '\\nEND\\n'); sys.exit(7)",
    ]

    with redirect_stderr(stderr):
        rc, tail = MODULE._run_streamed_command(
            command,
            cwd=tmp_path,
            gate_name="failing-gate",
            heartbeat_interval=0.01,
            capture_limit=4096,
        )

    assert rc == 7
    assert len(tail.encode()) <= 4096
    assert tail.endswith("END\n")
    assert "phase=done" in stderr.getvalue()
    assert "rc=7" in stderr.getvalue()


def test_git_mutation_streams_semantic_progress_without_exposing_argv(
    tmp_path, monkeypatch,
):
    """Silent git mutations heartbeat without leaking credential-shaped argv."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(textwrap.dedent("""\
        #!/bin/sh
        sleep 0.06
        printf 'mutation-output\\n'
    """))
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ.get('PATH', '')}")

    err = io.StringIO()
    with redirect_stderr(err):
        rc, output = MODULE._git_mutation(
            ["push", "origin", "token=super-secret"],
            cwd=tmp_path,
            label="sync-push",
            heartbeat_interval=0.01,
        )

    assert rc == 0
    assert output == "mutation-output"
    progress = err.getvalue()
    assert "mutation=sync-push phase=start" in progress
    assert "mutation=sync-push phase=spawned" in progress
    assert "mutation=sync-push phase=heartbeat" in progress
    assert "mutation=sync-push phase=done" in progress
    assert "pid=" in progress and "alive=" in progress
    assert "super-secret" not in progress


def test_registry_mutation_keeps_json_parseable_and_progress_off_stdout(
    tmp_path, monkeypatch,
):
    payload = {"schema": "kg.worktree.registry.v1", "clear": []}

    def fake_stream(command, **kwargs):
        assert kwargs["label"] == "preflight-sweep"
        assert kwargs["merge_stderr"] is False
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "diagnostic")

    monkeypatch.setattr(MODULE, "run_streamed_command", fake_stream)
    rc, parsed = MODULE._registry_mutation(
        ["sweep", "--commit", "--json"],
        cwd=tmp_path,
        label="preflight-sweep",
    )

    assert rc == 0
    assert parsed == payload


def test_registry_mutation_preserves_failure_diagnostic_without_stdout_pollution(
    tmp_path, monkeypatch,
):
    def fake_stream(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "sweep failed safely")

    monkeypatch.setattr(MODULE, "run_streamed_command", fake_stream)
    rc, parsed = MODULE._registry_mutation(
        ["sweep", "--commit", "--json"],
        cwd=tmp_path,
        label="preflight-sweep",
    )

    assert rc == 1
    assert parsed == {"error": "registry mutation failed", "detail": "sweep failed safely"}


def test_committed_preflight_routes_sweep_through_observed_registry_runner(
    tmp_path, monkeypatch,
):
    calls = []
    monkeypatch.setattr(MODULE, "_fetch", lambda: (0, ""))
    monkeypatch.setattr(MODULE, "primary_root", lambda: tmp_path)
    monkeypatch.setattr(
        MODULE,
        "_registry_mutation",
        lambda argv, **kwargs: (calls.append((argv, kwargs)) or (0, {"clear": []})),
    )
    monkeypatch.setattr(
        MODULE,
        "_registry",
        lambda argv: pytest.fail("committed sweep must not use silent in-process route"),
    )
    args = MODULE.argparse.Namespace(
        commit=True, state=None, json=True, allow_offline=False,
    )

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        rc = MODULE.cmd_preflight(args)

    assert rc == 0
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert "--commit" in argv and "--json" in argv
    assert kwargs == {"cwd": tmp_path, "label": "preflight-sweep"}
    assert json.loads(stdout.getvalue())["sweep_rc"] == 0


def test_remote_branch_probe_routes_ls_remote_through_observed_runner(
    tmp_path, monkeypatch,
):
    calls = []
    monkeypatch.setattr(MODULE, "primary_root", lambda: tmp_path)
    monkeypatch.setattr(
        MODULE,
        "_git_mutation",
        lambda argv, **kwargs: (calls.append((argv, kwargs)) or (0, "abc refs/heads/x")),
    )
    monkeypatch.setattr(
        MODULE, "_git", lambda *args, **kwargs: pytest.fail("ls-remote must be observed"),
    )

    assert MODULE._remote_branch_exists("x") is True
    assert calls == [
        (["ls-remote", "--heads", "origin", "x"],
         {"cwd": tmp_path, "label": "remote-branch-probe"}),
    ]


def test_committed_sync_routes_push_and_remote_verification_through_observed_runner(
    tmp_path, monkeypatch,
):
    local_sha = "a" * 40
    upstream_sha = "b" * 40
    observed = []
    monkeypatch.setattr(MODULE, "primary_root", lambda: tmp_path)
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *args: None)
    monkeypatch.setattr(MODULE, "_current_branch", lambda path: "main")
    monkeypatch.setattr(MODULE, "_fetch", lambda: (0, ""))

    def fake_probe(argv, cwd=None):
        if argv == ["rev-parse", "refs/heads/main"]:
            return 0, local_sha
        if argv == ["rev-parse", "origin/main"]:
            return 0, upstream_sha
        if argv[:2] == ["merge-base", "--is-ancestor"]:
            return 0, ""
        if argv[:2] == ["rev-list", "--count"]:
            return 0, "1"
        pytest.fail(f"unexpected silent probe: {argv}")

    def fake_observed(argv, **kwargs):
        observed.append((argv, kwargs["label"]))
        if argv[0] == "push":
            return 0, ""
        if argv[0] == "ls-remote":
            return 0, f"{local_sha}\trefs/heads/main"
        pytest.fail(f"unexpected observed command: {argv}")

    monkeypatch.setattr(MODULE, "_git", fake_probe)
    monkeypatch.setattr(MODULE, "_git_mutation", fake_observed)
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        rc = MODULE._guarded_advance(
            src_branch="main", dest_branch="main", production=False, step="sync",
            commit=True, as_json=True, state=None,
        )

    assert rc == 0
    assert observed == [
        (["push", "origin", "refs/heads/main:main"], "sync-push"),
        (["ls-remote", "origin", "main"], "sync-verify-remote"),
    ]
    assert json.loads(stdout.getvalue())["verdict"] == "pushed"


def test_potentially_long_git_operations_never_use_silent_probe_runner():
    """Static tripwire for every reviewed mutation family in this orchestrator."""
    tree = ast.parse((ROOT / "ops" / "worktree_orchestrate.py").read_text())
    forbidden = {
        "fetch", "push", "rebase", "merge", "worktree", "branch", "ls-remote",
    }
    violations = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_git" and node.args):
            continue
        argv = node.args[0]
        if not (isinstance(argv, ast.List) and argv.elts
                and isinstance(argv.elts[0], ast.Constant)):
            continue
        verb = argv.elts[0].value
        if verb in forbidden:
            violations.append((verb, node.lineno))
    assert violations == []


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


def _origin_prod_files(remote):
    # list files in the tip tree of origin's prod (the release-plane ref deploy advances)
    out = _git(["ls-tree", "-r", "--name-only", "prod"], remote)
    return set(out.splitlines())


def _local_main_files(repo):
    # local-centric: cutover advances the PRIMARY's local main (origin is untouched
    # until a separate deploy). Assert against the local trunk's tip tree.
    out = _git(["ls-tree", "-r", "--name-only", "main"], repo)
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
    # seed origin/prod = origin/main (the release-plane ref deploy advances); the
    # switchover seeds it once, then only `deploy` moves it. Without it, deploy's noop
    # baseline is absent.
    _git(["push", "-q", "origin", "main:prod"], repo)

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

    # --- cutover: rebase onto local main + ff the primary's local main (--commit) ---
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert cut["landed"] is True
    # local main now carries the work
    assert "notes.txt" in _local_main_files(repo)

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


def _advance_local_main(repo, name):
    """Add a commit to LOCAL main that origin does not have (origin is never pushed)."""
    (repo / f"{name}.txt").write_text("local-only\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", f"local: {name}"], repo)


@gitmark
def test_open_forks_from_local_main_not_origin(scratch):
    # local-centric: a commit that exists only on LOCAL main (origin never saw it) must
    # be present in a freshly opened worktree — proving the fork point is local, offline.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _advance_local_main(repo, "localwork")
    assert "localwork.txt" not in _origin_main_files(remote)   # origin is behind
    rc, opened = _run_json(["open", "--intent", "build on local work",
                            "--slug", "on-local", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    assert (Path(wt) / "localwork.txt").exists()               # forked from local main
    assert opened["base"] == "main"


@gitmark
def test_cutover_advances_local_main_and_leaves_origin_untouched(scratch):
    # the defining property of the local-centric model: cutover lands on LOCAL main,
    # origin is NOT pushed (deploy is a separate step).
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do the thing", "--slug", "thing",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and cut["landed"] is True
    assert "notes.txt" in _local_main_files(repo)              # local trunk advanced
    assert "notes.txt" not in _origin_main_files(remote)       # origin UNTOUCHED


@gitmark
def test_cutover_refused_when_primary_is_dirty(scratch):
    # cutover ff's the primary's checked-out main, which updates its working tree — so
    # a dirty primary (tracked changes) must refuse rather than clobber.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "doit",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    (repo / "f").write_text("dirtied the primary\n")            # tracked, uncommitted
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "dirty" in json.dumps(cut)
    assert cut["landed"] is False
    assert "notes.txt" not in _local_main_files(repo)          # trunk not advanced
    _git(["checkout", "--", "f"], repo)                         # clean up → now it lands
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and cut["landed"] is True


@gitmark
def test_cutover_refused_when_primary_not_on_main(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "doit2",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    _git(["checkout", "-q", "-b", "sidetrack"], repo)           # primary leaves main
    try:
        rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "sidetrack" in json.dumps(cut) and cut["landed"] is False
        # every refusal names its next step — here: put the primary back on main.
        assert "re-run cutover" in cut["error"]
    finally:
        _git(["checkout", "-q", "main"], repo)


@gitmark
def test_cutover_dirty_refusal_is_actionable(scratch):
    # a dirty-primary refusal must be ACTIONABLE for a concurrent-session agent:
    # name the dirty files (machine-readable `dirty_files` + in-message list) and
    # carry coordination guidance (find the co-tenant session, or evacuate your own
    # residue) instead of a bare "dirty" that leaves the agent dead-waiting.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    (repo / "alpha.txt").write_text("base\n")
    (repo / "beta.txt").write_text("base\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "track alpha/beta"], repo)
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "dirty-ux",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    (repo / "alpha.txt").write_text("another session's edit\n")
    (repo / "beta.txt").write_text("another session's edit\n")
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK and cut["landed"] is False
    assert sorted(cut["dirty_files"]) == ["alpha.txt", "beta.txt"]  # machine-readable
    err = cut["error"]
    assert "alpha.txt" in err and "beta.txt" in err                 # named in message
    for cue in ("list_sessions", "send_message", "commit",          # coordination path
                "gate verdict", "re-run cutover"):                  # verdict stays valid
        assert cue in err, f"missing guidance cue {cue!r} in: {err}"


@gitmark
def test_cutover_dirty_refusal_caps_message_list_at_ten(scratch):
    # the message stays readable (first 10 + "… and N more"); the JSON carries ALL.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    names = [f"trk{i:02d}.txt" for i in range(12)]
    for n in names:
        (repo / n).write_text("base\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "track 12 files"], repo)
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "dirty-cap",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    for n in names:
        (repo / n).write_text("dirty\n")
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert sorted(cut["dirty_files"]) == sorted(names)   # JSON: complete list
    assert cut["error"].count("trk") == 10               # message: capped at 10
    assert "and 2 more" in cut["error"]


@gitmark
def test_cutover_dirty_refusal_unquotes_special_paths(scratch):
    # git porcelain C-quotes unusual paths (`"my file.txt"`; octal-escaped UTF-8 for
    # non-ASCII under default core.quotePath=true). dirty_files must carry the REAL
    # paths — a literal-quoted/escaped entry is unusable to both machines and humans.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    names = ["my file.txt", "中文檔.txt"]
    for n in names:
        (repo / n).write_text("base\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "track special names"], repo)
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "dirty-quote",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    for n in names:
        (repo / n).write_text("dirty\n")
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert sorted(cut["dirty_files"]) == sorted(names)   # unquoted, decoded paths
    assert not any('"' in f or "\\" in f for f in cut["dirty_files"])


@gitmark
def test_cutover_merge_in_flight_refusal_names_next_step(scratch):
    # non-dirty refusals keep their reason but must also point at the next step.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "merge-flight",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    # stage a merge-in-progress in the primary (MERGE_HEAD set)
    _git(["checkout", "-q", "-b", "side"], repo)
    (repo / "side.txt").write_text("side\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "side"], repo)
    _git(["checkout", "-q", "main"], repo)
    _git(["merge", "--no-commit", "--no-ff", "side"], repo)
    try:
        rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "merge is in progress" in cut["error"]
        assert "re-run cutover" in cut["error"]
    finally:
        _git(["merge", "--abort"], repo)
        _git(["branch", "-qD", "side"], repo)


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
    assert cut["landed"] is False
    # local main did NOT advance
    assert "notes.txt" not in _local_main_files(repo)


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
    assert cut["landed"] is False


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
    assert cut["landed"] is True
    assert cut["verdict"] == "warn"
    assert "backend-tests-advisory" in cut["warnings"]
    # the work actually landed on LOCAL main
    assert "backend/src/kg/app.py" in _local_main_files(repo)


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
    assert cut["landed"] is False
    assert "docs/reference/x.md" not in _local_main_files(repo)


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
    assert cut["landed"] is True
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
    assert cut["landed"] is True
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

    # resolve stays ALLOWED while frozen — surgery prep is about draining, not
    # trapping. The pre-freeze worktree is landed (freshly forked from main, zero
    # unique commits) so the landed-floor passes and the teardown must complete.
    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["failures"] == 0
    assert not Path(wt).exists()

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


@gitmark
def test_adopt_from_subdirectory_registers_the_worktree_root(scratch):
    # review B1: cd <wt>/sub && adopt must register the worktree ROOT, not the subdir
    # (a subdir path breaks all later path-addressed operations: resolve, sweep).
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "oob"
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)
    (wt / "sub").mkdir()
    os.chdir(wt / "sub")
    try:
        rc, res = _run_json(["adopt", "--intent", "from a subdir", "--state", state,
                             "--json"])
    finally:
        os.chdir(repo)
    assert rc == MODULE.EXIT_OK
    recs = json.loads(Path(state).read_text())["records"]
    assert Path(recs[0]["path"]).resolve() == wt.resolve()


@gitmark
def test_adopt_anchors_default_ledger_at_target_not_process_cwd(scratch):
    # review B2: invoked from OUTSIDE any repo with an explicit --worktree and no
    # --state, the ledger must be derived from the TARGET's git-common-dir — not the
    # process cwd (which would silently write a stray ledger the flow never reads).
    tmp_path, repo, remote = scratch
    wt = tmp_path / "oob"
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    os.chdir(outside)
    try:
        rc, res = _run_json(["adopt", "--worktree", str(wt), "--intent", "from afar",
                             "--json"])
    finally:
        os.chdir(repo)
    assert rc == MODULE.EXIT_OK
    ledger = repo / ".cache" / "worktree_registry.json"
    assert ledger.exists()
    recs = json.loads(ledger.read_text())["records"]
    assert [r for r in recs if r["branch"] == "feat/oob"]
    assert not (outside / ".cache").exists()
    assert not (tmp_path / ".cache").exists()


@gitmark
def test_adopt_refuses_unresolvable_base(scratch):
    # review N2: open gets ref validation for free from `git worktree add`; adopt
    # must check --base itself instead of recording garbage in the ledger.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = tmp_path / "oob"
    _git(["worktree", "add", "-b", "feat/oob", str(wt), "main"], repo)
    rc, _res = _run_json(["adopt", "--worktree", str(wt), "--intent", "bad base",
                          "--base", "no/such-ref", "--state", state, "--json"])
    assert rc == MODULE.EXIT_USAGE


@gitmark
def test_sync_main_refuses_merge_in_progress_even_with_clean_porcelain(scratch):
    # review: MERGE_HEAD is the ONLY load-bearing guard for `merge --no-commit -s
    # ours` (the ours strategy leaves porcelain clean, so the dirty check alone
    # would wave it through).
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _git(["checkout", "-q", "-b", "side"], repo)
    (repo / "side.txt").write_text("side\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "side work"], repo)
    _git(["checkout", "-q", "main"], repo)
    _git(["merge", "--no-commit", "--no-ff", "-s", "ours", "side"], repo)
    assert not _git(["status", "--porcelain", "--untracked-files=no"], repo)
    try:
        rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "merge is in progress" in json.dumps(res)
    finally:
        _git(["merge", "--abort"], repo)
        _git(["branch", "-D", "side"], repo)


@gitmark
def test_sync_main_refuses_when_fetch_fails(scratch):
    # review: a dead origin must refuse, not report a stale-snapshot "noop"
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _git(["remote", "set-url", "origin", str(tmp_path / "gone.git")], repo)
    try:
        rc, res = _run_json(["sync-main", "--state", state, "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "fetch failed" in json.dumps(res)
    finally:
        _git(["remote", "set-url", "origin", str(remote)], repo)


# ============================================================================
# INTEGRATION: deploy (publish local trunk to origin — the one production touch)
# ============================================================================
@gitmark
def test_deploy_noop_when_origin_already_current(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, res = _run_json(["deploy", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["verdict"] == "noop"


@gitmark
def test_deploy_dry_run_reports_range_and_backend_rollout(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    # local main gets ahead with a backend change (origin is not pushed)
    bp = repo / "backend" / "src" / "kg" / "app.py"
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text("x = 1\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "backend change"], repo)

    rc, dry = _run_json(["deploy", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert dry["verdict"] == "dry-run"
    assert dry["commits"] == 1
    assert dry["would_roll_out"] is True
    assert "backend/src/kg/app.py" in dry["backend_files"]
    # dry-run pushed nothing — origin/prod (deploy's target) untouched
    assert "backend/src/kg/app.py" not in _origin_prod_files(remote)


@gitmark
def test_deploy_commit_pushes_and_advances_origin(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    (repo / "docs.md").write_text("note\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "a docs-only change"], repo)

    rc, res = _run_json(["deploy", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["verdict"] == "pushed"
    assert res["rolled_out"] is False           # no backend in range
    assert "docs.md" in _origin_prod_files(remote)     # origin/prod advanced (release plane)
    assert "docs.md" not in _origin_main_files(remote)  # origin/main untouched — deploy != sync


@gitmark
def test_deploy_refused_when_primary_not_on_main(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _git(["checkout", "-q", "-b", "sidetrack"], repo)
    try:
        rc, res = _run_json(["deploy", "--state", state, "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "sidetrack" in json.dumps(res)
    finally:
        _git(["checkout", "-q", "main"], repo)


@gitmark
def test_deploy_refused_when_origin_diverged(scratch):
    # origin/prod holds a commit local main lacks -> deploy must refuse (never force-push)
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    # advance origin/prod behind our back via a second clone (checkout prod there)
    other = tmp_path / "other"
    _git(["clone", "-q", "-b", "prod", str(remote), str(other)], tmp_path)
    _git(["config", "user.email", "o@o"], other); _git(["config", "user.name", "o"], other)
    (other / "remote-only.txt").write_text("from elsewhere\n")
    _git(["add", "-A"], other); _git(["commit", "-qm", "remote-only"], other)
    _git(["push", "-q", "origin", "prod"], other)
    # our local main also advances (diverging from origin/prod)
    (repo / "local-only.txt").write_text("mine\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "local-only"], repo)

    rc, res = _run_json(["deploy", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "reconcile" in json.dumps(res)


@gitmark
def test_deploy_refused_when_frozen(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    (repo / "x.txt").write_text("y\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "x"], repo)
    _run_json(["freeze", "on", "--reason", "surgery", "--state", state, "--json"])
    rc, res = _run_json(["deploy", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK


# ============================================================================
# INTEGRATION: sync (backup plane — mirror local trunk to origin/main, no side-effect)
# ============================================================================
@gitmark
def test_sync_noop_when_origin_already_current(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, res = _run_json(["sync", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["verdict"] == "noop"


@gitmark
def test_sync_dry_run_has_no_rollout_fields(scratch):
    # backup plane never speaks of rollout — even a backend change carries no
    # would_roll_out/backend_files (that is the deploy plane's concern).
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    bp = repo / "backend" / "src" / "kg" / "app.py"
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text("x = 1\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "backend change"], repo)

    rc, dry = _run_json(["sync", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert dry["verdict"] == "dry-run"
    assert dry["commits"] == 1
    assert "would_roll_out" not in dry
    assert "backend_files" not in dry


@gitmark
def test_sync_commit_mirrors_to_origin_main_not_prod(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    bp = repo / "backend" / "src" / "kg" / "app.py"
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text("x = 1\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "backend change"], repo)

    rc, res = _run_json(["sync", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["verdict"] == "pushed"
    assert "rolled_out" not in res                       # backup carries no rollout verdict
    assert "backend/src/kg/app.py" in _origin_main_files(remote)     # origin/main advanced
    assert "backend/src/kg/app.py" not in _origin_prod_files(remote)  # prod untouched — no deploy


@gitmark
def test_sync_refused_when_primary_not_on_main(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _git(["checkout", "-q", "-b", "sidetrack"], repo)
    try:
        rc, res = _run_json(["sync", "--state", state, "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert "sidetrack" in json.dumps(res)
    finally:
        _git(["checkout", "-q", "main"], repo)


@gitmark
def test_sync_refused_when_frozen(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    (repo / "x.txt").write_text("y\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "x"], repo)
    _run_json(["freeze", "on", "--reason", "surgery", "--state", state, "--json"])
    rc, res = _run_json(["sync", "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
