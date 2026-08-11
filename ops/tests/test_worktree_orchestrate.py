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
import argparse
import ast
import errno
import io
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
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

DISPATCH_SPEC = importlib.util.spec_from_file_location(
    "dispatch_preflight", ROOT / "ops" / "lib" / "dispatch_preflight.py"
)
assert DISPATCH_SPEC and DISPATCH_SPEC.loader
DISPATCH = importlib.util.module_from_spec(DISPATCH_SPEC)
sys.modules[DISPATCH_SPEC.name] = DISPATCH
DISPATCH_SPEC.loader.exec_module(DISPATCH)


def test_usage_errors_return_contract_code_for_root_and_subparser_typos():
    """Argparse's generic 2 must not collide with the workflow usage code 64."""
    for argv in (["--brnach"], ["open", "--brnach"]):
        assert MODULE.main(argv) == MODULE.EXIT_USAGE


def _names(gates):
    return {g["name"] for g in gates}


def _by_name(gates):
    return {g["name"]: g for g in gates}


# ============================================================================
# P0: dispatch preflight compiler
# ============================================================================
def _dispatch_payload(**overrides):
    payload = {
        "id": "IMP-20260811-fixture",
        "status": "triaged",
        "fix_site": "ops/backlog.py; ops/tests/test_backlog.py",
        "acceptance_cmd": "uv run --no-project --python 3.13 --with pytest pytest -q ops/tests/test_backlog.py",
        "blocked_by": [],
    }
    payload.update(overrides)
    return payload


def test_dispatch_preflight_static_red_is_executable(tmp_path):
    result = DISPATCH.compile_static(
        _dispatch_payload(), repo=tmp_path,
        contract_problems=[],
    )
    assert result.classification == "executable"
    assert result.ok is True
    assert result.problems == ()
    assert result.schema == "kg.dispatch.preflight.v1"


def test_dispatch_preflight_has_stable_contract_blocked_shape(tmp_path):
    result = DISPATCH.compile_static(
        _dispatch_payload(fix_site="ops/missing.py"), repo=tmp_path,
        contract_problems=[{"kind": "fix-site-missing", "path": "ops/missing.py"}],
    )
    payload = result.to_dict()
    assert payload["classification"] == "contract-blocked"
    assert payload["ok"] is False
    assert payload["problems"] == [{"kind": "fix-site-missing", "path": "ops/missing.py"}]
    assert payload["repair_hints"]
    assert set(payload) == {
        "schema", "ticket_id", "classification", "ok", "problems",
        "repair_hints", "probe",
    }


def test_dispatch_preflight_dependency_and_overlap_are_named(tmp_path):
    result = DISPATCH.compile_static(
        _dispatch_payload(blocked_by=["IMP-20260811-blocker"]),
        repo=tmp_path,
        contract_problems=[],
        unresolved_blockers=["IMP-20260811-blocker"],
        active_files={"ops/backlog.py"},
    )
    assert result.classification == "dependency-blocked"
    assert {problem["kind"] for problem in result.problems} == {
        "dependency-blocked", "active-overlap",
    }


def test_dispatch_preflight_probe_classifies_baseline_and_environment():
    baseline = DISPATCH.with_probe(
        DISPATCH.compile_static(_dispatch_payload(), repo=Path("."), contract_problems=[]),
        returncode=0, expected_returncode=0, stderr="",
    )
    environment = DISPATCH.with_probe(
        DISPATCH.compile_static(_dispatch_payload(), repo=Path("."), contract_problems=[]),
        returncode=1, expected_returncode=0, stderr="ModuleNotFoundError: No module named 'ebooklib'",
    )
    assert baseline.classification == "baseline-green"
    assert environment.classification == "environment-blocked"


def test_dispatch_preflight_declared_baseline_never_enters_a_worktree(tmp_path):
    result = DISPATCH.compile_static(
        _dispatch_payload(contract_baseline="green"), repo=tmp_path,
        contract_problems=[],
    )
    assert result.classification == "baseline-green"
    assert result.ok is False
    with_contract = DISPATCH.compile_static(
        _dispatch_payload(contract_baseline="green"), repo=tmp_path,
        contract_problems=[{"kind": "contract-baseline-not-red", "value": "green"}],
    )
    assert with_contract.classification == "baseline-green"

    for declared, kind in (("green", "baseline-green"), ("environment", "environment-blocked")):
        result = DISPATCH.compile_static(
            _dispatch_payload(contract_baseline=declared), repo=tmp_path,
            contract_problems=[],
        )
        assert result.classification == kind
        assert [problem["kind"] for problem in result.problems] == [kind]


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
def test_plan_is_never_empty():
    """An empty plan is how "checked nothing" became indistinguishable from
    "everything passed": aggregate_verdict([]) is pass. Make it unreachable."""
    assert plan_gates([]) != []
    assert "coverage" in _names(plan_gates([]))


def test_unrouted_file_is_named_not_dropped():
    cov = next(g for g in plan_gates(["lab/experiment.rb"]) if g["name"] == "coverage")
    assert cov["uncovered"] == ["lab/experiment.rb"]


def test_neutral_file_is_declared_with_a_reason():
    cov = next(g for g in plan_gates(["README.md"]) if g["name"] == "coverage")
    assert cov["uncovered"] == []
    assert cov["neutral"] == [["README.md", "README.md"]]


def test_claude_neutral_reason_does_not_claim_docs_coverage():
    """Keep the neutral reason honest while docs_lint does not scan `.claude/`."""
    source = (ROOT / "ops" / "docs_lint.sh").read_text()
    match = re.search(r"(?ms)^all_docs\(\) \{\n(?P<body>.*?)^}", source)
    assert match, "docs_lint.sh all_docs() definition is not parseable"
    if ".claude" in match.group("body"):
        return

    reason = dict(MODULE.NEUTRAL_RULES)[".claude/"]
    forbidden_claims = ("registry", "docs_lint", "涵蓋")
    assert not any(claim in reason.casefold() for claim in forbidden_claims), reason


def test_coverage_partition_is_exact():
    files = ["ios/BooksAndVocab/A.swift", "README.md", "lab/x.rb", "docs/reference/tech_index.md"]
    cov = next(g for g in plan_gates(files) if g["name"] == "coverage")
    parts = set(cov["covered"]) | {n[0] for n in cov["neutral"]} | set(cov["uncovered"])
    assert parts == set(files)


def test_backlog_entry_change_selects_validate():
    """The kaizen ledger is a data plane with no gate (IMP-20260805-9a51e9).

    `backlog.py validate` exists and has ZERO automatic callers: not CI, not any
    ops/*.sh, not this orchestrator. Measured today — the only mention outside its
    own tests is a prose line in .claude/agents/platform-steward.md, i.e. it runs
    only if an agent happens to read that line and choose to. Meanwhile the
    generated VIEW is machine-checked (registry `check:` -> render --check), so
    the tool guarantees the table matches the store and guarantees nothing about
    whether the store is true.

    Block, not warn: a malformed entry is a defect, and the check cannot go red
    just because you used the tool correctly — `add`/`update` only ever write
    schema-valid entries, and view staleness is render --check's job, not this
    one's. A gate that reds on correct use is the shape that gets muted.
    """
    gates = plan_gates(["docs/runbook/backlog/IMP-0001.json"])
    g = _by_name(gates).get("backlog-validate")
    assert g is not None, f"no backlog-validate gate; planned: {_names(gates)}"
    assert g["level"] == "block", g
    assert g["cmd"][:2] == ["ops/backlog.py", "validate"], g["cmd"]


def test_backlog_entry_is_not_reported_uncovered():
    cov = next(g for g in plan_gates(["docs/runbook/backlog/IMP-0001.json"])
               if g["name"] == "coverage")
    assert cov["uncovered"] == [], cov["uncovered"]


def test_backlog_entry_change_also_checks_the_generated_view():
    """A store-only diff must not report "everything routed" while the thing that
    actually breaks in that diff shape goes unwatched.

    `validate` checks entry schema; it says nothing about whether the generated
    view still matches the store. Mutating the store stales the view, and that is
    the single most-hit trap in this repo today. Before this route existed,
    `coverage` at least NAMED the json as uncovered; marking it covered by a gate
    that deliberately ignores view freshness would be a net loss.

    `docs_lint.sh --registry` runs registry `check:`, which for
    runbook.improvement_backlog is `backlog.py render --check`.
    """
    gates = _by_name(plan_gates(["docs/runbook/backlog/IMP-0001.json"]))
    g = gates.get("data-plane:ops/docs_lint.sh")
    assert g is not None, f"view freshness unguarded; planned: {sorted(gates)}"
    assert g["level"] == "block", g
    assert "--registry" in g["cmd"], g["cmd"]


def test_changing_the_validator_itself_validates_the_store():
    """Keying only on the store lets the validator change without anyone running
    it against real data.

    Concretely scheduled, not hypothetical: IMP-20260805-9a51e9 plans to add
    traceability checks and states outright that the real store must go to 7
    problems the moment they land. That commit touches only ops/backlog.py and its
    tests -> ops-pytest passes on its own fixtures -> cutover green -> the store is
    globally invalid, and the next unrelated agent to touch any entry eats 7
    problems they did not cause. That is the "red on correct use -> gate gets
    muted" shape this route exists to avoid.
    """
    gates = _by_name(plan_gates(["ops/backlog.py"]))
    assert "backlog-validate" in gates, sorted(gates)


def test_backlog_route_does_not_claim_paths_the_validator_never_reads():
    """`validate_store` globs `*.json` at the top level only (non-recursive), so a
    nested path would be routed, counted as covered, and never actually read — a
    vacuous pass one directory deeper than the one the route already guards."""
    gates = plan_gates(["docs/runbook/backlog/sub/nested.json"])
    assert "backlog-validate" not in _names(gates)
    cov = next(g for g in gates if g["name"] == "coverage")
    assert cov["uncovered"] == ["docs/runbook/backlog/sub/nested.json"], cov


def test_backlog_validate_does_not_swallow_unrelated_json():
    """Anti-over-reach. The route keys on the store directory, not on `.json`
    anywhere under docs/ — otherwise an unrelated data file would select a
    validator that knows nothing about it and pass vacuously."""
    gates = plan_gates(["docs/reference/some_other_data.json"])
    assert "backlog-validate" not in _names(gates)


def test_no_neutral_rule_swallows_a_source_surface():
    import re as _re
    for probe in ("ios/BooksAndVocab/X.swift", "backend/src/kg/app.py",
                  "ops/x.py", "ops/x.sh", "design-system/tokens.json"):
        for pat, _reason in MODULE.NEUTRAL_RULES:
            assert not (probe == pat or probe.startswith(pat)), f"{pat} swallows {probe}"


def test_gate_plan_real_repo_plans_review_receipts():
    """Iron law 4's mechanical half must be planned for the real repo.

    The gate is skipped when ops/review_audit.sh is absent so synthetic fixture
    repos still work; this pins that the skip cannot quietly become permanent.
    """
    gates = plan_gates(["README.md"], ops_test_exists=lambda rel: True, base="main")
    g = next(x for x in gates if x["name"] == "review-receipts")
    assert g["level"] == "block"
    assert g["cmd"][:2] == ["ops/review_audit.sh", "--rev-range"]
    assert "--machine-gate" not in g["cmd"], (
        "an ordinary gate must not discharge missing commit review receipts")
    integration = plan_gates(
        ["README.md"], ops_test_exists=lambda rel: True, base="main",
        machine_gate=True,
    )
    integration_review = next(
        x for x in integration if x["name"] == "review-receipts")
    assert integration_review["cmd"][-1] == "--machine-gate"
    # and absent when the tool is not there
    assert "review-receipts" not in _names(
        plan_gates(["README.md"], ops_test_exists=lambda rel: False, base="main"))


def test_integrate_gate_explicitly_requests_the_machine_review_exception(
    tmp_path, monkeypatch, capsys
):
    """The exception belongs to parent integration, not to `plan_gates` globally."""
    call = {}

    def fake_land_step(func, **kwargs):
        call.update(kwargs)
        return MODULE.EXIT_BLOCK, {
            "verdict": "block", "head_sha": "abc1234", "gates": [],
        }

    monkeypatch.setattr(MODULE, "_land_step", fake_land_step)
    monkeypatch.setattr(MODULE, "_head_sha", lambda _wt: "abc1234")
    state_path = tmp_path / "integration.json"
    args = argparse.Namespace(
        state=str(tmp_path / "registry.json"), base="main", json=True, slug="batch")
    integration_state = {
        "worktree": str(tmp_path), "slug": "batch", "branch": "feat/batch",
        "trunk": "main", "branches": [], "picked": [], "skipped": [],
        "queue": [], "planned_total": 0,
    }

    assert MODULE._integrate_gate(args, state_path, integration_state) == MODULE.EXIT_BLOCK
    capsys.readouterr()
    assert call["machine_gate"] is True


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


def test_gate_plan_ios_test_gates_lease_a_pool_simulator():
    """Both iOS test gates must pass `--lease`.

    Without it they contend for the single default simulator, whose device lock
    has a 600s ceiling. Under concurrent worktrees that ceiling is hit routinely
    and `ios_test.sh` exits 1 — identical, from the gate's side, to a genuine
    test failure. Observed 2026-08-05: `ios-test-ui:ExploreNavigationUITests`
    blocked a cutover with `timed out after 600s waiting for device lock`,
    having never reached a single test. Nothing else pins this flag, so removing
    it would leave the whole suite green.
    """
    unit = _by_name(plan_gates(["ios/BooksAndVocab/Views/Explore/ExploreView.swift"]))["ios-test-unit"]
    assert "--lease" in unit["cmd"], unit["cmd"]

    ui = _by_name(plan_gates(["ios/BooksAndVocabUITests/ReaderFlowTests.swift"]))["ios-test-ui:ReaderFlowTests"]
    assert "--lease" in ui["cmd"], ui["cmd"]


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
    assert names - {"coverage"} == {"design-system"}
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


@pytest.mark.parametrize("changed", [
    ["ops/worktree_orchestrate.py", "ops/tests/test_worktree_orchestrate.py"],
    ["backend/src/kg/app.py"],
    ["lab/monitor.py"],
])
def test_gate_plan_any_python_source_runs_python_scan_once(changed):
    gates = _by_name(plan_gates(changed, ops_test_exists=lambda rel: True))
    spec = gates["ops-python-scan"]
    assert spec["level"] == "block"
    assert spec["cmd"] == ["ops/python_scan.py"]
    assert list(gates).count("ops-python-scan") == 1


def test_gate_plan_python_scan_excludes_non_python_diffs():
    assert "ops-python-scan" not in _names(plan_gates(["ios/App/View.swift", "README.md"]))


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


def test_gate_plan_ops_shell_selects_no_ops_pytest():
    """Shell scripts have no pytest counterpart; docs/backend must not leak into the
    ops route either."""
    assert "ops-pytest" not in _names(plan_gates(["ops/devops_kg_safe.sh"]))
    assert not any(n == "ops-pytest"
                   for n in _names(plan_gates(["docs/reference/tech_index.md"])))
    assert not any(n == "ops-pytest"
                   for n in _names(plan_gates(["backend/tests/test_app.py"])))


# ---------------------------------------------------------------------------
# ops/**/*.sh routing (IMP-0051)
#
# Until 2026-08-04 a changed shell script selected NOTHING. `ops/devops_kg_safe.sh`
# is iron law 7's enforcement point and `ops/release.sh` is the only path to
# production; both landed on nothing but the commit-trailer audit.
# ---------------------------------------------------------------------------
def test_a_changed_shell_script_always_gets_at_least_a_syntax_floor():
    """The floor has to be universal, because ~13 ops scripts have no test at all.
    `bash -n` needs nothing but bash, so there is no machine where it is skipped."""
    gates = _by_name(plan_gates(["ops/kg_backup.sh"], ops_test_exists=lambda rel: False))
    assert gates["ops-shell-syntax"]["level"] == "block"
    assert gates["ops-shell-syntax"]["files"] == ["ops/kg_backup.sh"]


def test_a_changed_shell_script_runs_the_test_named_after_it():
    gates = _by_name(plan_gates(["ops/docs_lint.sh"], ops_test_exists=lambda rel: True))
    assert gates["ops-shell:test_docs_lint.sh"]["cmd"] == ["ops/tests/test_docs_lint.sh"]
    assert gates["ops-shell:test_docs_lint.sh"]["level"] == "block"


def test_a_changed_test_script_runs_itself():
    gates = _by_name(plan_gates(["ops/tests/test_gate_can_fail.sh"],
                                ops_test_exists=lambda rel: True))
    assert gates["ops-shell:test_gate_can_fail.sh"]["cmd"] == ["ops/tests/test_gate_can_fail.sh"]


def test_a_deleted_test_script_is_not_handed_back_to_the_runner():
    """A deleted file is in the diff too. Routing to it would make the gate red for a
    reason that has nothing to do with the change — the ops_py branch learned this the
    same way (pytest exits 4 on a gone path)."""
    gates = _by_name(plan_gates(["ops/tests/test_gate_can_fail.sh"],
                                ops_test_exists=lambda rel: False))
    assert not any(n.startswith("ops-shell:") for n in gates)
    assert gates["ops-shell-untested"]["level"] == "warn"


def test_a_shell_script_with_no_test_is_named_rather_than_dropped():
    """The advisory is the point: `uncovered` said only that something was unrouted,
    which is indistinguishable from a file nobody has classified yet. Naming the script
    and the reason turns a routing hole into an enumerated one."""
    gates = _by_name(plan_gates(["ops/kg_backup.sh"], ops_test_exists=lambda rel: False))
    advisory = gates["ops-shell-untested"]
    assert advisory["files"] == ["ops/kg_backup.sh"]
    assert "ops/kg_backup.sh" in advisory["note"]
    # and it is no longer reported as an unrouted file
    assert gates["coverage"]["uncovered"] == []


def test_the_aggregate_runner_is_never_armed_as_a_block_gate():
    """`ops/test_ops.sh` invokes every group, including the ones excluded from CI for
    needing local assets, and takes many minutes. Routing it would hand cutover a gate
    whose colour depends on the machine — the ios-build-catalyst pathology, which teaches
    people to leave the process. It goes to the advisory WITH its reason instead, because
    a silent exclusion is how the next person concludes the file is covered.

    The reason is asserted by identity, not by keyword: pinning a literal like an IMP id
    means the test breaks when the prose is corrected rather than when the behaviour is."""
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    gates = _by_name(plan_gates(["ops/test_ops.sh"], ops_test_exists=real))
    assert not any(n.startswith("ops-shell:") for n in gates)
    note = gates["ops-shell-untested"]["note"]
    assert "ops/test_ops.sh" in note
    assert MODULE.OPS_SHELL_UNROUTABLE_TESTS["ops/test_ops.sh"] in note
    assert gates["ops-shell-syntax"]["files"] == ["ops/test_ops.sh"]


def test_every_unroutable_test_declaration_still_names_a_real_file():
    """A stale exclusion silently stops excluding anything, and reads as if it does."""
    for rel, reason in MODULE.OPS_SHELL_UNROUTABLE_TESTS.items():
        assert (ROOT / rel).is_file(), f"{rel} no longer exists"
        assert reason.strip(), f"{rel} has no reason — an unexplained exclusion is a hole"


def test_every_shell_test_alias_points_at_a_test_that_mentions_its_script():
    """A hand-written map is fine; an unverifiable one is not. Each alias must name a
    file that exists AND that actually references the script it claims to cover, so an
    alias cannot keep claiming coverage after the test stops exercising it.

    NECESSARY, NOT SUFFICIENT — and the gap has already bitten: `release_changelog.sh ->
    test_release.sh` passed every assertion here while the target only `[[ -f ]]`-checked
    the script and grepped a DIFFERENT file for a mention of it. Mechanically proving
    coverage means mutating the script and requiring the target to go red (IMP-0055)."""
    assert MODULE.OPS_SHELL_TEST_ALIASES, "the alias map is the fallback for name mismatches"
    for src, target in MODULE.OPS_SHELL_TEST_ALIASES.items():
        assert (ROOT / src).is_file(), f"alias source {src} no longer exists"
        assert (ROOT / target).is_file(), f"alias target {target} no longer exists"
        base = src.rsplit("/", 1)[-1]
        assert base in (ROOT / target).read_text(errors="replace"), \
            f"{target} never mentions {base} — the alias claims coverage it does not have"
        # a name-mismatch alias is pointless if convention already resolves it
        assert not (ROOT / f"ops/tests/test_{base}").is_file()
        assert not (ROOT / f"ops/test_{base}").is_file()


def test_shell_routing_resolves_against_the_real_repo():
    """The lambda-True prober cannot reach the alias branch (convention always wins), so
    the alias is exercised with a real existence probe or not at all."""
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    gates = _by_name(plan_gates(["ops/devops_kg_safe.sh"], ops_test_exists=real))
    assert "ops-shell:test_devops_safe_lightsail_guard.sh" in gates
    assert "ops-shell-untested" not in gates


def test_catalog_shell_routes_to_its_behavioral_boundary_test():
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    gates = _by_name(plan_gates(["ops/lib/ios_ops_catalog.sh"], ops_test_exists=real))
    gate = gates["ops-shell:test_catalog_agent_boundary.sh"]
    assert gate["cmd"] == ["ops/tests/test_catalog_agent_boundary.sh"]
    assert os.access(ROOT / gate["cmd"][0], os.X_OK)
    executed = subprocess.run(
        [str(ROOT / gate["cmd"][0])], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert executed.returncode == 0, executed.stdout + executed.stderr
    assert "ops-shell-untested" not in gates


def test_a_repo_root_shell_script_is_routed_like_any_other():
    """`devops.sh` is the production deploy command and lives at the repo root, so the
    original `ops/`-prefixed filter skipped it entirely — the single highest-consequence
    shell script in the tree was the one with no gate. Its test existed and had been red
    for six weeks (IMP-0052); nothing was arranged to notice."""
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    gates = _by_name(plan_gates(["devops.sh"], ops_test_exists=real))
    assert gates["ops-shell:test_devops.sh"]["cmd"] == ["ops/test_devops.sh"]
    assert gates["ops-shell:test_devops.sh"]["level"] == "block"
    assert gates["ops-shell-syntax"]["files"] == ["devops.sh"]
    assert gates["coverage"]["uncovered"] == []


def test_a_repo_root_shell_script_with_no_test_lands_in_the_advisory():
    """Widening the filter must not turn a routing hole into a silent pass: a root script
    with no test still has to be named, exactly as an ops/ one would be."""
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    gates = _by_name(plan_gates(["start.sh"], ops_test_exists=real))
    assert not any(n.startswith("ops-shell:") for n in gates)
    assert gates["ops-shell-untested"]["files"] == ["start.sh"]
    assert gates["coverage"]["uncovered"] == []


# --- ops-shell-scan: the guard no diff could ever reach (IMP-20260808-3bbfa2) ---
#
# `ops/tests/test_script_help.sh` has scanned every tracked *.sh for `$VAR` abutting
# a non-ASCII character since 2026-08-05 (eleven full-width punctuation characters and
# nothing else until 2026-08-08, any byte >= 0x80 after) — correctly, with a positive
# control, and
# it names the offending file and line the moment anyone runs it. Nobody ran it. The
# cutover gate routes a changed `ops/**.sh` to `bash -n` and to that script's OWN
# test, and a repo-wide scanner is nobody's own test, so the check existed, was
# right, and was unreachable from the only path that could have used it. On
# 2026-08-08 that cost half an hour and let `devops.sh:669` reach `land`.
#
# The hole was in the ROUTING, so the fix is routing plus one shared entry point —
# not a second copy of the scan living in the orchestrator.

def test_plan_routes_shell_scan_for_any_changed_sh():
    gates = _by_name(plan_gates(["ops/devops_kg_safe.sh"]))
    assert "ops-shell-scan" in gates
    assert gates["ops-shell-scan"]["level"] == "block"
    assert gates["ops-shell-scan"]["cmd"] == ["ops/shell_scan.sh"]


def test_plan_routes_shell_scan_for_a_repo_root_sh():
    """Same widening as `ops-shell-syntax`: `devops.sh` lives at the root and has the
    highest blast radius in the tree (IMP-0052)."""
    assert "ops-shell-scan" in _names(plan_gates(["devops.sh"]))


def test_plan_leaves_shell_scan_out_when_no_sh_changed():
    """The control. A gate present in every plan would satisfy both tests above while
    saying nothing about routing — and would also run a repo-wide scan on every
    Swift-only diff."""
    assert "ops-shell-scan" not in _names(plan_gates(["backend/src/kg/x.py",
                                                      "ios/App/View.swift"]))


def test_plan_routes_shell_scan_only_once_for_many_changed_sh():
    """It is a REPO-wide scan; per-file instances would be N identical runs."""
    names = [g["name"] for g in plan_gates(
        ["ops/a.sh", "ops/b.sh", "devops.sh", "ops/c.sh"])]
    assert names.count("ops-shell-scan") == 1


def test_ui_quality_plane_yml_routes_to_its_owner_tools():
    """`ops/ui_quality_plane.yml` stopped being a mechanism *listing* on 2026-08-05: it
    now carries the `run:` argv the UI quality gate actually executes (IMP-0041). A typo
    in it silently shrinks what the gate runs — and until this routing existed, changing
    it selected no gate at all, so nothing would say so."""
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    gates = _by_name(plan_gates(["ops/ui_quality_plane.yml"], ops_test_exists=real))
    assert gates["data-plane:ops/ui_quality_plane.py"]["cmd"] == [
        "ops/ui_quality_plane.py", "validate"]
    assert gates["data-plane:ops/ui_quality_plane.py"]["level"] == "block"
    assert gates["data-plane:ops/tests/test_ui_quality_plane.sh"]["cmd"] == [
        "ops/tests/test_ui_quality_plane.sh"]
    assert "data-plane-unowned" not in gates
    assert gates["coverage"]["uncovered"] == []


def test_docs_registry_yml_routes_to_the_registry_lint():
    """The docs control plane is a yml, so `docs/**.md` never covered it: the file that
    decides which docs are gated was itself ungated."""
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    gates = _by_name(plan_gates(["docs/registry.yml"], ops_test_exists=real))
    assert gates["data-plane:ops/docs_lint.sh"]["cmd"] == ["ops/docs_lint.sh", "--registry"]
    assert gates["coverage"]["uncovered"] == []


def test_registry_lint_is_not_planned_twice_when_docs_lint_files_covers_it():
    """`docs_lint.sh --files` validates the registry before dispatching its mode, so a
    separate `--registry` run would assert the same fact twice for one diff."""
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    gates = plan_gates(["docs/registry.yml", "docs/sop/ios.md"],
                       ops_test_exists=real)
    docs_lint_runs = [g["cmd"] for g in gates
                      if g.get("cmd", [None])[0] == "ops/docs_lint.sh"]
    assert docs_lint_runs == [["ops/docs_lint.sh", "--files", "docs/sop/ios.md"]]
    assert _by_name(gates)["coverage"]["uncovered"] == []


def test_the_same_tool_is_not_planned_twice_for_one_diff():
    """Changing a yml AND the script that tests it must not run that script twice. The
    shell router already selected `ops/tests/test_ui_quality_plane.sh`; the data-plane
    router has to notice, or every such diff pays for a duplicate run and the operator
    reads two verdicts for one fact."""
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    gates = plan_gates(["ops/ui_quality_plane.yml", "ops/tests/test_ui_quality_plane.sh"],
                       ops_test_exists=real)
    runs = [g["cmd"] for g in gates if g.get("cmd") == ["ops/tests/test_ui_quality_plane.sh"]]
    assert len(runs) == 1, [g["name"] for g in gates]


def test_a_yaml_with_no_owner_tool_is_named_not_swallowed():
    """Same shape as `ops-shell-untested`: an enumerated hole beats an anonymous one.
    There is no universal syntax floor here the way `bash -n` is for shell — no YAML
    parser ships with the stdlib, and hand-rolling one to gate on would make the gate's
    verdict a property of my parser rather than of the file."""
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    gates = _by_name(plan_gates([".github/workflows/ui-quality-gate.yml"],
                                ops_test_exists=real))
    assert gates["data-plane-unowned"]["files"] == [".github/workflows/ui-quality-gate.yml"]
    assert gates["data-plane-unowned"]["level"] == "warn"
    assert gates["coverage"]["uncovered"] == []


def test_a_neutral_yaml_stays_neutral_and_is_not_named_twice():
    """`promotion/` and `frozen/` already have a neutral rule. Routing yml must not
    re-adopt them, or every asset-metadata edit grows a warn that means nothing."""
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    gates = _by_name(plan_gates(["promotion/screenshots/manifest.yml"],
                                ops_test_exists=real))
    assert "data-plane-unowned" not in gates
    assert gates["coverage"]["uncovered"] == []
    assert gates["coverage"]["neutral"] == [["promotion/screenshots/manifest.yml",
                                             "promotion/"]]


def test_a_deleted_data_plane_yml_does_not_route_to_a_tool_that_would_red():
    """A deleted file is in the diff too. `ui_quality_plane.py validate` on a yml that is
    gone exits non-zero, which reads as "your change is broken" rather than "you removed
    the file" — the same false-red shape that made the ops-pytest existence probe
    necessary (IMP-0045)."""
    gone = lambda rel: rel != "ops/ui_quality_plane.yml"  # noqa: E731
    gates = _by_name(plan_gates(["ops/ui_quality_plane.yml"], ops_test_exists=gone))
    assert not any(n.startswith("data-plane:") for n in gates)
    # …and it must still be NAMED. Skipping the validator while counting the file as
    # covered would make `coverage` report "every changed file is routed to a gate" about
    # a file nothing looked at — strictly worse than the anonymous hole this replaced.
    assert gates["data-plane-deleted"]["files"] == ["ops/ui_quality_plane.yml"]
    assert gates["data-plane-deleted"]["level"] == "warn"
    assert gates["coverage"]["uncovered"] == []


def test_no_two_data_plane_owners_produce_the_same_gate_name():
    """Gate names key the plan JSON, the result lookup and the history journal, so a
    duplicate name means the second verdict overwrites the first while the plan still
    reads complete. Naming by tool PATH removes the directory-collision route; what is
    left is one tool invoked with two different argv (a future `docs_lint.sh --files`
    beside `--registry`), which this catches and the basename version did not."""
    seen: dict[str, list[str]] = {}
    for target, owners in MODULE.DATA_PLANE_OWNERS.items():
        for cmd in owners:
            name = f"data-plane:{cmd[0]}"
            assert name not in seen or seen[name] == list(cmd), (
                f"gate name collision on {name}: {list(cmd)} (for {target}) "
                f"and {seen[name]}")
            seen[name] = list(cmd)


def test_data_plane_commands_are_spelled_repo_relative():
    """`./ops/x.sh` and `ops/x.sh` name the same file — `ROOT / "./ops/x.sh"` exists, so
    the existence contract test passes either way — but they are different strings, and
    the dedup against the shell router is exact list equality. One `./` and the same
    script runs twice under two names, with nothing to say so."""
    for target, owners in MODULE.DATA_PLANE_OWNERS.items():
        for cmd in owners:
            tool = cmd[0]
            assert not tool.startswith(("./", "/")), f"{tool} (for {target})"
            assert "/" in tool, f"{tool} (for {target}) is not repo-relative"


def test_every_declared_data_plane_owner_exists_in_the_repo():
    """The routing table names tools by path. A rename that misses this table produces a
    gate that can only ever be red — the `ios-build-catalyst` failure mode, which blocked
    every iOS cutover for two months before anyone read it as a tool problem."""
    for target, owners in MODULE.DATA_PLANE_OWNERS.items():
        assert (ROOT / target).is_file(), f"routed target missing: {target}"
        for cmd in owners:
            assert (ROOT / cmd[0]).is_file(), f"owner tool missing: {cmd[0]} (for {target})"


# (`gitmark` is defined further down, next to the integration tests that need it)
@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_no_two_routable_shell_scripts_share_a_basename():
    """`_ops_shell_test_candidates` keys on the basename alone, so two routable scripts
    with the same name resolve to the same test file. Widening the filter to repo-root
    scripts made that reachable: a future root `release.sh` would be "covered" by
    `ops/test_release.sh` — the test for `ops/release.sh` — and its gate would go green
    without executing a line of it. Nothing collides today; this pins that, because when
    it does happen the misrouting is silent and looks exactly like real coverage.

    If this test starts failing on the assert below because routing became path-aware,
    the guard has been made redundant by a better fix — delete the test, don't patch it.

    Since IMP-0057 the `routable` predicate below is no longer the gate's file filter
    (that is now every `*.sh` minus SHELL_GATE_EXCLUDED_TREES) but exactly the set where
    the basename CONVENTION applies. The guard therefore also pins the two halves
    together: widen `_ops_shell_test_candidates` past ops/ + root without renaming
    `lab/podcast/start.sh`, and this collides."""
    # the trap itself, demonstrated rather than asserted from memory
    assert (MODULE._ops_shell_test_candidates("release.sh")
            == MODULE._ops_shell_test_candidates("ops/release.sh"))

    out = subprocess.run(["git", "ls-files", "*.sh"], cwd=str(ROOT),
                         capture_output=True, text=True, check=True)
    routable = [p for p in out.stdout.split() if p.startswith("ops/") or "/" not in p]
    # an empty list would make the loop below vacuously green
    assert len(routable) > 20, f"git ls-files returned {len(routable)} — the probe is broken"

    seen: dict[str, str] = {}
    for p in routable:
        base = p.rsplit("/", 1)[-1]
        assert base not in seen, (
            f"{p} and {seen[base]} share a basename, so both route to "
            f"{MODULE._ops_shell_test_candidates(p)} — one would be gated by the "
            f"other's test. Rename one, or make routing path-aware."
        )
        seen[base] = p

    # Same defect, one hop further: OPS_SHELL_UNROUTABLE_TESTS is consulted for the
    # changed script, never for the test it resolves to. A script named `ops.sh` would
    # resolve to `ops/test_ops.sh` — the aggregate runner, declared unroutable precisely
    # because arming it as a block gate is unacceptable — and be armed anyway.
    for p in routable:
        for cand in MODULE._ops_shell_test_candidates(p):
            assert cand not in MODULE.OPS_SHELL_UNROUTABLE_TESTS, (
                f"{p} resolves to {cand}, which OPS_SHELL_UNROUTABLE_TESTS declares "
                f"must never be a gate ({MODULE.OPS_SHELL_UNROUTABLE_TESTS[cand]}) — "
                f"the exclusion is keyed on the changed script, not on the target"
            )

    # The loop above covers where the CONVENTION applies. The set that can EMIT an
    # `ops-shell:<basename>` gate is strictly larger, because the `test_` self-gate
    # branch returns BEFORE the ops/+root restriction — it is path-exact, so it happily
    # routes a `backend/test_docs_lint.sh`. The gate NAME is not path-exact: plan_gates
    # dedupes `sh_targets` as a set of PATHS and then names each one by basename alone,
    # so two distinct target files sharing a basename become two gates with one name —
    # and `_gate_log_path` slugs the name, so they share one log and one clobbers the
    # other's captured failure output, the artefact IMP-20260808-c47253 exists to keep.
    #
    # Two scripts resolving to the SAME target (ios_build.sh and ios_archive.sh both
    # alias to ops/test_ios_ops.sh) is not this bug: one path, one gate, one log.
    # Found by review of IMP-0057; nothing collides today.
    excluded = tuple(pat for pat, _ in MODULE.SHELL_GATE_EXCLUDED_TREES)
    routed = [p for p in out.stdout.split() if not p.startswith(excluded)]
    assert len(routed) > 20, f"git ls-files returned {len(routed)} — the probe is broken"
    # The RESOLVED target only — first candidate that exists, exactly as plan_gates
    # picks it. Comparing the whole candidate list would compare hypotheticals: it
    # always holds both `ops/tests/test_X.sh` and `ops/test_X.sh`, which share a
    # basename by construction and of which at most one is ever real.
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    by_gate_name: dict[str, str] = {}
    for p in routed:
        hit = next((c for c in MODULE._ops_shell_test_candidates(p) if real(c)), None)
        if hit is None:
            continue
        gname = f"ops-shell:{hit.rsplit('/', 1)[-1]}"
        assert by_gate_name.setdefault(gname, hit) == hit, (
            f"{hit} and {by_gate_name[gname]} are different files that both emit the "
            f"gate {gname!r} (reached via {p}), so they share one gate log and one "
            f"clobbers the other's failure output. Rename one, or make the gate name "
            f"path-aware."
        )
    # without this the loop above is vacuously green the day resolution stops working
    assert len(by_gate_name) > 20, (
        f"only {len(by_gate_name)} script(s) resolved to a real test — the probe is "
        f"broken, not the routing")


def test_a_shell_script_outside_ops_is_routed_like_any_other():
    """`backend/view_logs.sh` 是 ops/test_devops.sh 靜態測著的那支；在 ops/ 與
    repo root 之外，shell gate 之前完全不路由（IMP-0057，與 IMP-0052 同形）。"""
    real = lambda rel: (ROOT / rel).is_file()  # noqa: E731
    gates = _by_name(plan_gates(["backend/view_logs.sh"], ops_test_exists=real))
    assert gates["ops-shell-syntax"]["files"] == ["backend/view_logs.sh"]
    assert gates["ops-shell-syntax"]["level"] == "block"
    # ops/tests/test_view_logs.sh 與 ops/test_view_logs.sh 都不存在，所以不得有 ops-shell: gate
    assert not any(n.startswith("ops-shell:") for n in gates)
    assert gates["ops-shell-untested"]["files"] == ["backend/view_logs.sh"]
    assert gates["coverage"]["uncovered"] == []


def test_a_frozen_shell_script_selects_no_shell_gate():
    """frozen/ 是刻意冷凍的快照：掛上 gate 只會讓 advisory 永遠列著 7 個沒人打算補測試
    的檔，advisory 一有長期雜訊就沒人看。排除必須具名，不能靠 anonymous hole。"""
    rel = "frozen/2026-06-14-web-chrome-parity/web/start.sh"
    real = lambda p: (ROOT / p).is_file()  # noqa: E731
    gates = _by_name(plan_gates([rel], ops_test_exists=real))
    assert not any(n.startswith("ops-shell") for n in gates)
    assert gates["coverage"]["neutral"] == [[rel, "frozen/"]]
    assert "frozen/" in dict(MODULE.SHELL_GATE_EXCLUDED_TREES)


def test_shell_test_convention_stops_at_ops_and_root():
    """basename 慣例（ops/tests/test_<base> / ops/test_<base>）只在 ops/ 與 repo root
    成立。放寬 filter 後 lab/podcast/start.sh 會撞上 root start.sh 的候選，兩支互相
    「覆蓋」而沒有執行過對方一行。"""
    assert MODULE._ops_shell_test_candidates("lab/podcast/start.sh") == []
    assert MODULE._ops_shell_test_candidates("backend/view_logs.sh") == []
    assert MODULE._ops_shell_test_candidates(".claude/skills/app-debug/find-polluter.sh") == []
    # 慣例在原本適用的兩處必須毫髮無傷
    assert MODULE._ops_shell_test_candidates("start.sh") == ["ops/tests/test_start.sh",
                                                            "ops/test_start.sh"]
    assert MODULE._ops_shell_test_candidates("ops/docs_lint.sh")[0] == "ops/tests/test_docs_lint.sh"


def test_shell_syntax_skips_a_shebang_it_cannot_run(tmp_path):
    """語法地板拿 bash -n 打一支非 bash 腳本會產生假紅。認不出直譯器就跳過並具名——
    an enumerated hole beats an anonymous one。"""
    d = tmp_path / "misc"
    d.mkdir()
    (d / "weird.sh").write_text("#!/usr/bin/env python3\nif [[ -z ]; then\n")
    (d / "fine.sh").write_text("#!/usr/bin/env bash\necho ok\n")
    out = MODULE._run_shell_syntax(str(tmp_path), ["misc/weird.sh", "misc/fine.sh"])
    assert out["status"] == "pass"
    assert "misc/weird.sh" in out["summary"]
    assert "skipped" in out["summary"]
    # 沒有 shebang 的檔（ops/lib/*.sh 有 6 支）必須仍走 bash -n，不得被降級成 skipped
    (d / "noshebang.sh").write_text("if [[ -z ]; then\n")
    bad = MODULE._run_shell_syntax(str(tmp_path), ["misc/noshebang.sh"])
    assert bad["status"] == "block"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_the_workflow_triggers_on_every_routed_script_outside_ops():
    """cutover 路由面與 CI 觸發面對同一個檔案必須有相同意見。ops-suite.yml 的 `ops/**`
    只涵蓋 ops/；其餘沒有共同前綴，只能逐條列，所以它是會漂的那一半——漏一條的後果
    就是 IMP-0052 本身（本機 gate 擋得住、CI 完全看不到那支腳本）。"""
    wf = (ROOT / ".github/workflows/ops-suite.yml").read_text()
    block = wf.split("paths: &ops_paths", 1)[1].split("pull_request:", 1)[0]
    listed = set(re.findall(r"^\s*- '([^']+)'", block, re.MULTILINE))
    assert "ops/**" in listed, "解析不到 ops/** 代表探針壞了，不是 workflow 壞了"

    out = subprocess.run(["git", "ls-files", "*.sh"], cwd=str(ROOT),
                         capture_output=True, text=True, check=True)
    excluded = tuple(pat for pat, _ in MODULE.SHELL_GATE_EXCLUDED_TREES)
    routed_outside_ops = [p for p in out.stdout.split()
                          if not p.startswith("ops/") and not p.startswith(excluded)]
    assert len(routed_outside_ops) >= 5, (
        f"git ls-files 只給了 {len(routed_outside_ops)} 支——探針壞了")
    missing = [p for p in routed_outside_ops if p not in listed]
    assert missing == [], (
        f"cutover 會路由這些腳本，但 .github/workflows/ops-suite.yml 不會因它們觸發：{missing}")


def test_shell_syntax_counts_only_the_scripts_it_actually_parsed(tmp_path):
    """The pass summary is the only thing anyone reads from a green syntax gate, so it
    must not claim more than it did. `len(files)` includes the ones skipped for being
    deleted in this same diff — in the all-deleted case the gate reported "3 shell
    script(s) parse" having run bash zero times, which is a vacuous green stating a
    number. Found by review of IMP-0057; the `skipped` branch inherited the same defect
    from the pre-existing one."""
    d = tmp_path / "ops"
    d.mkdir()
    (d / "real.sh").write_text("#!/usr/bin/env bash\necho ok\n")
    (d / "skipme.sh").write_text("#!/usr/bin/env python3\nnot bash at all\n")
    out = MODULE._run_shell_syntax(str(tmp_path),
                                   ["ops/real.sh", "ops/gone.sh", "ops/skipme.sh"])
    assert out["status"] == "pass"
    assert out["summary"].startswith("1 shell script(s) parse"), out["summary"]
    assert "1 skipped" in out["summary"]

    # and the all-green path, where the same overcount lived before this fix
    only = MODULE._run_shell_syntax(str(tmp_path), ["ops/real.sh", "ops/gone.sh"])
    assert only["summary"] == "1 shell script(s) parse"
    # every file deleted: nothing ran, and the summary must not pretend otherwise
    none_left = MODULE._run_shell_syntax(str(tmp_path), ["ops/gone.sh", "ops/also-gone.sh"])
    assert none_left["summary"] == "0 shell script(s) parse"


def test_shell_syntax_skips_an_interpreter_the_machine_does_not_have(tmp_path, monkeypatch):
    """`_SYNTAX_CHECKABLE_SHELLS` holds `sh`/`zsh` as well as bash, and the name is
    resolved through PATH. A recognised-but-absent interpreter used to land in `bad` via
    the OSError arm — a BLOCK about the SCRIPT for a fact about the MACHINE, which is
    the exact failure the shebang handling was added to avoid. `zsh` is not on GitHub's
    ubuntu runner by default, so this is one CI job away from being real."""
    d = tmp_path / "ops"
    d.mkdir()
    (d / "zsh_tool.sh").write_text("#!/bin/zsh\nprint hi\n")
    (d / "ok.sh").write_text("#!/usr/bin/env bash\necho ok\n")
    # patched through the module's own seam, not on the stdlib module object: the
    # latter leaks into every other test in the process
    monkeypatch.setattr(MODULE, "_which",
                        lambda name: None if name == "zsh" else "/bin/" + name)
    out = MODULE._run_shell_syntax(str(tmp_path), ["ops/zsh_tool.sh", "ops/ok.sh"])
    assert out["status"] == "pass"
    assert "ops/zsh_tool.sh" in out["summary"] and "skipped" in out["summary"]
    # bash is present, so a genuinely broken bash script must still block
    (d / "broken.sh").write_text("#!/usr/bin/env bash\nif [[ -z ]; then\n")
    assert MODULE._run_shell_syntax(str(tmp_path), ["ops/broken.sh"])["status"] == "block"


def test_shell_syntax_that_checked_nothing_does_not_report_pass(tmp_path):
    """`ops-shell-syntax` is a BLOCK gate, so its colour is a claim. When every routed
    script was skipped the gate ran bash zero times and established nothing — and "I
    verified nothing" must not share a colour with "everything passed". Exactly the
    reason the summary stopped saying `len(files)`; found by review, one file further in.

    It degrades to warn rather than block: a machine missing an interpreter is not the
    branch's fault, which is the same judgement `inconclusive` encodes for gates."""
    d = tmp_path / "ops"
    d.mkdir()
    (d / "a.sh").write_text("#!/usr/bin/env python3\nnot bash\n")
    (d / "b.sh").write_text("#!/usr/bin/env python3\nalso not bash\n")
    out = MODULE._run_shell_syntax(str(tmp_path), ["ops/a.sh", "ops/b.sh"])
    assert out["status"] == "warn"
    assert "0 shell script(s) parse" in out["summary"]
    assert "ops/a.sh" in out["summary"] and "ops/b.sh" in out["summary"]

    # control: one real check is enough to make the gate a pass again
    (d / "c.sh").write_text("#!/usr/bin/env bash\necho ok\n")
    mixed = MODULE._run_shell_syntax(str(tmp_path), ["ops/a.sh", "ops/c.sh"])
    assert mixed["status"] == "pass"
    # and a diff whose only shell file was DELETED is not "checked nothing" in this
    # sense — there is nothing left to check, and that was already a pass
    gone = MODULE._run_shell_syntax(str(tmp_path), ["ops/deleted.sh"])
    assert gone["status"] == "pass"


def test_shell_syntax_marks_runs_that_checked_nothing_unestablished(tmp_path):
    """A green colour from an all-deleted diff is not evidence that syntax was checked.

    The result must carry an explicit provenance bit so the gate-history reader can
    exclude both this case and the all-skipped interpreter case from capability proof.
    """
    d = tmp_path / "ops"
    d.mkdir()
    (d / "python.sh").write_text("#!/usr/bin/env python3\nprint('not bash')\n")

    skipped = MODULE._run_shell_syntax(str(tmp_path), ["ops/python.sh"])
    assert skipped["status"] == "warn"
    assert skipped["established"] is False

    deleted = MODULE._run_shell_syntax(str(tmp_path), ["ops/missing.sh"])
    assert deleted["status"] == "pass"
    assert deleted["established"] is False


def test_shell_syntax_gate_names_the_file_that_will_not_parse(tmp_path):
    good = tmp_path / "ops" / "fine.sh"
    good.parent.mkdir(parents=True)
    good.write_text("#!/usr/bin/env bash\necho ok\n")
    assert MODULE._run_shell_syntax(str(tmp_path), ["ops/fine.sh"])["status"] == "pass"

    bad = tmp_path / "ops" / "broken.sh"
    bad.write_text("#!/usr/bin/env bash\nif [[ -z ]; then\n")
    out = MODULE._run_shell_syntax(str(tmp_path), ["ops/fine.sh", "ops/broken.sh"])
    assert out["status"] == "block"
    assert "ops/broken.sh" in out["summary"]
    assert "ops/fine.sh" not in out["summary"]


def test_shell_syntax_gate_ignores_a_file_the_diff_deleted(tmp_path):
    assert MODULE._run_shell_syntax(str(tmp_path), ["ops/gone.sh"])["status"] == "pass"


def test_gate_plan_neutral_file_selects_only_the_coverage_gate():
    """Explicit contract update (2026-08-03): a neutral diff no longer yields an
    EMPTY plan, because an empty plan is what made aggregate_verdict return pass
    for having checked nothing. It now yields exactly the coverage bookkeeping
    gate, which records why nothing else was selected."""
    for files in (["README.md"], ["notes.txt"], []):
        assert _names(plan_gates(files)) == {"coverage"}
    # an unrouted extension is named rather than silently dropped
    cov = next(g for g in plan_gates(["notes.txt"]) if g["name"] == "coverage")
    assert cov["uncovered"] == ["notes.txt"]


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
    # the batch shape this actually shows up as: one genuine red alongside one red that
    # tag surgery contaminated. The contaminated one must not launder the genuine one.
    assert aggregate_verdict([{"status": "inconclusive"},
                              {"status": "block"}]) == "block"


def test_verdict_inconclusive_degrades_to_warn():
    assert aggregate_verdict([{"status": "inconclusive"}]) == "warn"
    assert aggregate_verdict([{"status": "pass"}, {"status": "inconclusive"}]) == "warn"


def test_verdict_refuses_a_status_it_does_not_know(): # noqa: D103
    """An unknown status must block, and the fall-through must not be `pass`.

    Today no producer emits one, so this is a latent charge rather than a live bug —
    but the failure direction is GREEN, and the next status anyone adds is the most
    likely trigger (`timeout` is already named by two open entries). A gate that
    reports something the aggregator cannot read is the aggregator saying "I do not
    know what I am looking at", and there is exactly one safe answer to that.

    NOT `warn`: in this module `warn` means "degraded, named, disposition belongs to
    the driving agent" — see the `inconclusive` argument in the docstring. That is a
    state somebody JUDGED. An unrecognised status is a state nobody judged.
    """
    assert aggregate_verdict([{"status": "timeout"}]) == "block"
    assert aggregate_verdict([{"status": "pass"}, {"status": "timeout"}]) == "block"


def test_verdict_refuses_a_result_with_no_status_at_all():
    """`{}` rather than `{"status": None}`: a MISSING key is the shape a truncated or
    half-built result actually has, and `.get()` turns it into `None` silently — the
    original fall-through then folded that straight to `pass`."""
    assert aggregate_verdict([{}]) == "block"
    assert aggregate_verdict([{"status": "pass"}, {"name": "half-built"}]) == "block"
    assert aggregate_verdict([{"status": None}]) == "block"


def test_infrastructure_unavailable_rc_is_not_a_block(tmp_path, monkeypatch):
    """A typed iOS lock timeout is machine state, not a product verdict."""
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "stable")
    monkeypatch.setattr(
        MODULE,
        "_run_streamed_command",
        lambda *args, **kwargs: (75, "[ios_test] infrastructure unavailable", 0.001),
    )

    result = MODULE._run_gate(
        {
            "name": "ios-test-unit",
            "category": "ios",
            "level": "block",
            "kind": "shell",
            "cmd": ["ops/ios_ops.sh", "test", "--unit"],
        },
        str(tmp_path),
    )

    assert result["rc"] == 75
    assert result["status"] == "inconclusive"
    assert result["summary"] == (
        "infrastructure unavailable (rc=75), not a verdict on this branch"
    )
    assert MODULE.aggregate_verdict([result]) == "warn"


def test_non_infrastructure_failure_still_blocks(tmp_path, monkeypatch):
    """Only the typed infrastructure sentinel is downgraded."""
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "stable")
    monkeypatch.setattr(
        MODULE,
        "_run_streamed_command",
        lambda *args, **kwargs: (1, "assertion failed", 0.001),
    )

    result = MODULE._run_gate(
        {
            "name": "ios-test-unit",
            "category": "ios",
            "level": "block",
            "kind": "shell",
            "cmd": ["ops/ios_ops.sh", "test", "--unit"],
        },
        str(tmp_path),
    )

    assert result["rc"] == 1
    assert result["status"] == "block"


def test_typed_warn_exit_is_advisory_even_for_block_level_shell_gate(tmp_path, monkeypatch):
    """A producer's rc=3 WARN must survive the orchestrator consumer boundary."""
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "stable")
    monkeypatch.setattr(
        MODULE,
        "_run_streamed_command",
        lambda *args, **kwargs: (3, "WARN: origin-unreachable", 0.001),
    )

    result = MODULE._run_gate(
        {
            "name": "docs-verified-against",
            "category": "docs",
            "level": "block",
            "kind": "shell",
            "cmd": ["ops/docs_lint.sh", "--files", "docs/sop/ios.md"],
        },
        str(tmp_path),
    )

    assert result["rc"] == 3
    assert result["status"] == "warn"
    assert MODULE.aggregate_verdict([result]) == "warn"


def test_verdict_names_the_offender_rather_than_just_refusing(capsys):
    """Blocking without saying which gate leaves the reader to diff the payload by
    hand. The name and the offending value both have to travel.

    Asserted through `aggregate_verdict` — the function production actually calls —
    and NOT only through `assert_known_statuses`. A test that reaches past the caller
    passes against an implementation whose handler catches the exception bare and
    throws the message away, which is exactly what the first draft of this fix did.
    """
    with pytest.raises(MODULE.UnknownGateStatus) as excinfo:
        MODULE.assert_known_statuses([{"name": "ios-build", "status": "timeout"}])
    message = str(excinfo.value)
    assert "ios-build" in message, message
    assert "timeout" in message, message

    assert aggregate_verdict([{"name": "ios-build", "status": "timeout"}]) == "block"
    emitted = capsys.readouterr().err
    assert "ios-build" in emitted, emitted
    assert "timeout" in emitted, emitted


def test_streamed_gate_runner_heartbeats_to_stderr_and_keeps_stdout_pure(tmp_path):
    stdout = io.StringIO()
    stderr = io.StringIO()
    command = [
        sys.executable,
        "-c",
        "import time; print('first', flush=True); time.sleep(.08); print('last')",
    ]

    with redirect_stdout(stdout), redirect_stderr(stderr):
        rc, tail, dur_s = MODULE._run_streamed_command(
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
    assert dur_s >= 0.06


def test_streamed_gate_runner_bounds_capture_and_preserves_nonzero_exit(tmp_path):
    stderr = io.StringIO()
    command = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('x' * 200000 + '\\nEND\\n'); sys.exit(7)",
    ]

    with redirect_stderr(stderr):
        rc, tail, dur_s = MODULE._run_streamed_command(
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
    assert dur_s >= 0


def test_shell_and_internal_gate_results_carry_duration(tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "stable")
    monkeypatch.setattr(
        MODULE,
        "_run_streamed_command",
        lambda *args, **kwargs: (0, "lockWaitMs=9000 deviceRunLockWaitMs=3000", 12.5),
    )

    shell = MODULE._run_gate(
        MODULE._shell("ios-test-unit", "ios", ["ops/ios_ops.sh", "test"], "block"),
        str(tmp_path),
    )
    internal = MODULE._run_gate(
        MODULE._internal(
            "coverage", "meta", "warn", covered=[], neutral=[], uncovered=[]
        ),
        str(tmp_path),
    )

    assert shell["dur_s"] == 12.5
    assert internal["dur_s"] >= 0
    assert internal["status"] == "pass"


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


def _normalise_fixture_ref(token):
    """Return a comparable branch name for a push refspec destination."""
    token = token.strip().lstrip("+")
    if ":" in token:
        token = token.rsplit(":", 1)[1]
    while True:
        for prefix in ("refs/remotes/", "refs/heads/", "origin/"):
            if token.startswith(prefix):
                token = token[len(prefix):]
                break
        else:
            return token.rsplit("/", 1)[-1]


def _is_production_ref(token):
    return _normalise_fixture_ref(token) == "prod"


def _is_network_target(token):
    lowered = token.lower()
    return (
        lowered.startswith("//")
        or lowered.startswith("ext::")
        or bool(re.match(r"^[a-z][a-z0-9+.-]*://", lowered))
        or (":" in token and not token.startswith(("/", "./", "../"))
            and not re.match(r"^[A-Za-z]:[\\/].*$", token))
    )


def _fixture_remote_urls(cwd):
    """Read configured remote URLs without invoking a process or network."""
    root = Path(cwd)
    marker = root / ".git"
    candidates = [root / "config"]
    if marker.is_dir():
        candidates.append(marker / "config")
    elif marker.is_file():
        try:
            gitdir_line = next(
                line for line in marker.read_text(encoding="utf-8").splitlines()
                if line.startswith("gitdir:")
            )
            gitdir = Path(gitdir_line.partition(":")[2].strip()).expanduser()
            if not gitdir.is_absolute():
                gitdir = (root / gitdir).resolve()
            candidates.extend((gitdir / "config", gitdir.parent.parent / "config"))
        except (OSError, StopIteration, UnicodeError):
            pass
    urls = []
    for config in candidates:
        try:
            lines = config.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in lines:
            if line.lstrip().startswith("[include"):
                urls.append("unresolved-config-include://fixture")
                break
            key, separator, value = line.partition("=")
            if separator and key.strip() in {"url", "pushurl"}:
                urls.append(value.strip())
    return urls


def _assert_fixture_git_safe(args, cwd):
    """Keep scratch fixtures off production refs and network-capable remotes."""
    command = args[:1]
    network_commands = {"clone", "fetch", "ls-remote", "pull", "push", "remote", "submodule"}
    if command and command[0] not in network_commands:
        network_tokens = []
    else:
        tokens = list(enumerate(args[1:], start=1))
        if command == ["push"]:
            repository = next((index for index, token in tokens if not token.startswith("-")), None)
            network_tokens = [
                token for index, token in tokens
                if not (repository is not None and index > repository and ":" in token)
            ]
        else:
            network_tokens = [token for _, token in tokens]
    if command and command[0] in network_commands and (
        any(_is_network_target(token) for token in network_tokens)
        or any(_is_network_target(url) for url in _fixture_remote_urls(cwd))
    ):
        raise AssertionError("fixture git helper refuses network-capable remote")
    if command == ["push"] and any(token in {"--all", "--mirror"} for token in args[1:]):
        raise AssertionError("fixture git helper refuses implicit production ref push")
    if command == ["push"] and any(_is_production_ref(token) for token in args[1:]):
        raise AssertionError("fixture git helper refuses production ref push")


def _git(args, cwd):
    _assert_fixture_git_safe(args, cwd)
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout.strip()


def test_safety_fixture_no_production_push():
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for function in (
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name != "test_production_ref_push_denied"
    ):
        for call in ast.walk(function):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "_git"
                and call.args
                and isinstance(call.args[0], ast.List)
                and call.args[0].elts
                and isinstance(call.args[0].elts[0], ast.Constant)
                and call.args[0].elts[0].value == "push"
            ):
                continue
            for argument in call.args[0].elts[1:]:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    assert not _is_production_ref(argument.value)
                elif isinstance(argument, ast.JoinedStr):
                    literal = "".join(
                        part.value for part in argument.values if isinstance(part, ast.Constant)
                    )
                    assert not _is_production_ref(literal)


def test_production_ref_push_denied(monkeypatch, tmp_path):
    calls = []

    def unexpected_subprocess(*args, **kwargs):
        calls.append(args[0])
        raise AssertionError("production ref reached subprocess")

    monkeypatch.setattr(subprocess, "run", unexpected_subprocess)
    for ref in (
        "main:prod", "prod", "origin/prod", "HEAD:refs/heads/prod",
        "refs/heads/prod", "refs/remotes/origin/prod",
        "refs/heads/main:refs/heads/prod",
    ):
        with pytest.raises(AssertionError, match="fixture git helper refuses production ref"):
            _git(["push", "-q", "origin", ref], tmp_path)
    for option in ("--all", "--mirror"):
        with pytest.raises(AssertionError, match="fixture git helper refuses implicit production ref push"):
            _git(["push", "-q", "origin", option], tmp_path)
    with pytest.raises(AssertionError, match="fixture git helper refuses network-capable remote"):
        _git(["push", "https://example.invalid/repository.git", "HEAD:fixture"], tmp_path)
    for remote in (
        "github.com:/repo.git", "git@github.com:/repo.git", "192.168.1.5:repo.git",
        "build-server:repo.git", "git@[::1]:repo.git", "//host/repo.git",
    ):
        with pytest.raises(AssertionError, match="fixture git helper refuses network-capable remote"):
            _git(["push", remote, "HEAD:fixture"], tmp_path)
    configured = tmp_path / "configured-network"
    (configured / ".git").mkdir(parents=True)
    (configured / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = git+ssh://git@example.invalid/repository.git\n',
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="fixture git helper refuses network-capable remote"):
        _git(["fetch", "origin"], configured)
    included = tmp_path / "included-config"
    (included / ".git").mkdir(parents=True)
    (included / ".git" / "config").write_text(
        "[include]\n\tpath = ~/.gitconfig-network\n", encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="fixture git helper refuses network-capable remote"):
        _git(["push", "origin", "HEAD:fixture"], included)
    linked = tmp_path / "linked-worktree"
    common_git = linked / "common.git"
    (common_git / "worktrees" / "fixture").mkdir(parents=True)
    linked.mkdir(exist_ok=True)
    (linked / ".git").write_text(
        f"gitdir: {common_git / 'worktrees' / 'fixture'}\n", encoding="utf-8"
    )
    (common_git / "config").write_text(
        '[remote "origin"]\n\turl = ssh://git@example.invalid/repository.git\n',
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="fixture git helper refuses network-capable remote"):
        _git(["push", "origin", "HEAD:fixture"], linked)
    assert calls == []


@gitmark
def test_verified_against_requires_head_reachability(tmp_path):
    repo = tmp_path / "verified-against"
    (repo / "docs").mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "probe@example.test"], repo)
    _git(["config", "user.name", "probe"], repo)
    doc = repo / "docs" / "x.md"

    def anchor(sha):
        doc.write_text(
            "<!-- doc-meta\nverified_against: " + sha + "\n-->\n",
            encoding="utf-8",
        )

    anchor("0000000")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "base"], repo)
    base = _git(["rev-parse", "HEAD"], repo)
    _git(["checkout", "-q", "-b", "wt-fixture"], repo)
    (repo / "note.txt").write_text("worktree commit\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "branch"], repo)
    branch = _git(["rev-parse", "HEAD"], repo)
    orphan = _git(
        ["-c", "user.email=probe@example.test", "-c", "user.name=probe",
         "commit-tree", "HEAD^{tree}", "-m", "orphan"],
        repo,
    )

    reachability = subprocess.run(
        ["git", "merge-base", "--is-ancestor", orphan, "HEAD"],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert reachability.returncode != 0

    anchor(base)
    assert MODULE._run_verified_against(str(repo), ["docs/x.md"])["status"] == "pass"
    anchor(branch)
    assert MODULE._run_verified_against(str(repo), ["docs/x.md"])["status"] == "pass"

    anchor("0" * 40)
    absent = MODULE._run_verified_against(str(repo), ["docs/x.md"])
    assert absent["status"] != "pass"
    assert "absent" in absent["summary"]

    anchor(orphan)
    orphan_result = MODULE._run_verified_against(str(repo), ["docs/x.md"])
    assert orphan_result["status"] != "pass"
    assert "orphan" in orphan_result["summary"]


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


SHELL_SCAN = ROOT / "ops" / "shell_scan.sh"


def _scan_fixture(tmp_path, name, offending=None):
    """A tracked tree the scanner can be pointed at.

    Twelve filler scripts because the scanner refuses to trust a run that saw
    suspiciously few files — a floor that exists so a broken probe cannot report
    "clean". Satisfying it is right; switching it off for the test would delete the
    property from exactly the place that checks the scanner.
    """
    repo = tmp_path / name
    (repo / "ops").mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], repo)
    for i in range(12):
        (repo / "ops" / f"filler{i}.sh").write_text(
            f'var=x\necho "filler {i}"\necho "safe ${{var}}，braced"\n',
            encoding="utf-8")
    if offending is not None:
        (repo / "ops" / "offender.sh").write_text(offending, encoding="utf-8")
    _git(["add", "-A"], repo)
    return repo


@gitmark
def test_shell_scan_blocks_a_var_abutting_full_width_punctuation(tmp_path):
    """The 2026-08-08 line, verbatim in shape."""
    repo = _scan_fixture(tmp_path, "dirty",
                         offending='dest=/tmp\necho "目錄：$dest（已標記）"\n')
    proc = subprocess.run([str(SHELL_SCAN), str(repo)],
                          capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, out
    # naming the site is the whole value: a scanner that only says "found 1" leaves
    # the reader where the 94-character summary left them
    assert "ops/offender.sh:2" in out, out


@gitmark
def test_shell_scan_passes_a_clean_tree_including_the_braced_form(tmp_path):
    """The positive control for the test above, and for `${VAR}` being the FIX: the
    fillers all contain `${var}，`, so a pattern broad enough to flag the safe form
    turns this red."""
    repo = _scan_fixture(tmp_path, "clean")
    proc = subprocess.run([str(SHELL_SCAN), str(repo)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@gitmark
def test_shell_scan_respects_a_named_exemption(tmp_path):
    """`fw-allow` with a reason is the documented escape hatch; a scan that ignored
    it would make its own fixtures unrepresentable."""
    repo = _scan_fixture(
        tmp_path, "exempt",
        offending='dest=/tmp\necho "目錄：$dest（已標記）"  # fw-allow: fixture\n')
    proc = subprocess.run([str(SHELL_SCAN), str(repo)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_shell_scan_has_a_help_surface():
    proc = subprocess.run([str(SHELL_SCAN), "--help"],
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert "Usage:" in proc.stdout


@pytest.fixture
def scratch(tmp_path):
    """A repo with a bare origin, main pushed. Chdir into the repo (the orchestrator
    derives repo_root + registry state from cwd's git context)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / ".git" / "info" / "exclude").write_text(".cache/\n", encoding="utf-8")
    (repo / "f").write_text("base\n")
    # A real, groomed, open ticket for the claim tests to take. Before the claim
    # gate existed these tests claimed `IMP-0001` out of thin air, which is exactly
    # the hole the gate closes — a claim on an id that is in no store. Seeding it
    # makes the fixture agree with the world the tests describe ("another worktree
    # already holds this TICKET").
    store = repo / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True)
    def _seed(entry_id, **over):
        payload = {
            "schema": "kg.backlog.entry.v1", "id": entry_id, "status": "open",
            "stream": "IMP", "severity": "med", "category": "tool",
            "date": "2026-08-08", "source": "fixture",
            "detail": f"a ticket the claim tests can take ({entry_id})",
            "plan": "do the thing", "acceptance": "red then green",
            "fix_site": "ops/x.py:1", "acceptance_cmd": "true",
            "acceptance_expect_rc": 0, "groomed_at": "2026-08-08",
            "groomed_by": "fixture"}
        payload.update(over)
        (store / f"{entry_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    # Every id the claim tests reach for. They are groomed and open because the
    # claim gate now requires both — which is the world those tests already
    # describe in prose ("another worktree already holds this TICKET").
    for _id in ("IMP-0002", "IMP-0007", "IMP-0100", "IMP-0101"):
        _seed(_id)
    (store / "IMP-0001.json").write_text(json.dumps({
        "schema": "kg.backlog.entry.v1", "id": "IMP-0001", "status": "open",
        "stream": "IMP", "severity": "med", "category": "tool", "date": "2026-08-08",
        "source": "fixture", "detail": "a ticket the claim tests can take",
        "plan": "do the thing", "acceptance": "red then green",
        "fix_site": "ops/x.py:1", "acceptance_cmd": "true", "acceptance_expect_rc": 0,
        "groomed_at": "2026-08-08", "groomed_by": "fixture",
    }), encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "base"], repo)

    remote = tmp_path / "remote.git"
    _git(["init", "-q", "--bare", str(remote)], repo)
    _git(["remote", "add", "origin", str(remote)], repo)
    _git(["push", "-q", "origin", "main"], repo)
    # seed origin/prod = origin/main (the release-plane ref deploy advances); the
    # switchover seeds it once, then only `deploy` moves it. Without it, deploy's noop
    # baseline is absent.
    _git(["update-ref", "refs/heads/prod", "main"], remote)

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
    scratch_dir = Path(opened["scratch_dir"])
    assert scratch_dir.is_dir()
    assert scratch_dir.parent == Path(wt) / ".cache"
    _git(["check-ignore", "-q", "--", str(scratch_dir)], wt)
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
    # Contract update (2026-08-03): the fixture's file is routed to no gate, so
    # the always-planned coverage gate warns. `warn` still lands; what changed is
    # that "nothing was checked" is now visible instead of reading as pass.
    assert gate["verdict"] == "warn"
    assert [g["name"] for g in gate["gates"] if g["status"] == "warn"] == ["coverage"]
    # Only the coverage bookkeeping gate runs; an empty gate list is no longer
    # reachable, which is the point (see test_plan_is_never_empty).
    assert [g["name"] for g in gate["gates"]] == ["coverage"]
    assert "notes.txt" in gate["changed_files"]
    # gate wrote a verdict cache beside the ledger (nit3 will strike it on resolve).
    gate_cache = MODULE._gate_record_path(state, wt)
    assert gate_cache.exists()
    # A failed gate ALSO leaves an output log beside that cache (IMP-20260808-c47253).
    # This run is green so there is none; plant one so the residue assertion below has
    # something to be about. Planted through the real path helper — a hand-spelled
    # filename would still pass while resolve cleaned a directory nobody writes to.
    stray_log = MODULE._gate_log_path(gate_cache, "ops-shell:test_devops.sh")
    stray_log.write_text("✗ some assertion\n", encoding="utf-8")

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
    assert not scratch_dir.exists()
    assert "debug/reader-crash" not in _local_branches(repo)
    assert res.get("gate_cache_removed") is True
    assert not gate_cache.exists()
    assert not stray_log.exists(), (
        "a failed gate's output log outlives the worktree it describes unless resolve "
        "strikes it too — same residue rule as the verdict cache")
    # ledger record struck to merged
    recs = {r["branch"]: r for r in json.loads(Path(state).read_text())["records"]}
    assert recs["debug/reader-crash"]["status"] == "merged"
    assert recs["debug/reader-crash"]["resolved_at"] is not None


@gitmark
def test_delegated_worktree_is_marked_and_cutover_refuses_before_gate(scratch):
    """A delegated child must be refused before a gate verdict is required."""
    tmp_path, _repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    wt = None
    try:
        rc, opened = _run_json([
            "open", "--intent", "delegated child", "--slug", "delegated-child",
            "--delegated", "--state", state, "--json",
        ])
        assert rc == MODULE.EXIT_OK, opened
        wt = opened["path"]
        records = json.loads(Path(state).read_text())["records"]
        assert next(r for r in records if r["path"] == wt)["delegated"] is True

        rc, refusal = _run_json([
            "cutover", "--worktree", wt, "--state", state, "--json",
        ])
        assert rc == MODULE.EXIT_BLOCK, refusal
        assert refusal["refusal"] == "delegated"
    finally:
        if wt and Path(wt).exists():
            MODULE.main([
                "resolve", "--worktree", wt, "--state", state,
                "--force", "--commit", "--json",
            ])


@gitmark
def test_two_open_worktrees_get_distinct_scratch_dirs_and_resolve_removes_them(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")

    opened = []
    for slug in ("scratch-alpha", "scratch-beta"):
        rc, payload = _run_json([
            "open", "--intent", "isolate agent scratch", "--slug", slug,
            "--state", state, "--json",
        ])
        assert rc == MODULE.EXIT_OK
        scratch_dir = Path(payload["scratch_dir"])
        assert scratch_dir.is_dir()
        _git(["check-ignore", "-q", "--", str(scratch_dir)], payload["path"])
        (scratch_dir / "same-name.log").write_text(slug, encoding="utf-8")
        opened.append((payload["path"], scratch_dir))

    assert opened[0][1] != opened[1][1]
    assert (opened[0][1] / "same-name.log").read_text(encoding="utf-8") == "scratch-alpha"
    assert (opened[1][1] / "same-name.log").read_text(encoding="utf-8") == "scratch-beta"

    for wt, scratch_dir in opened:
        rc, resolved = _run_json([
            "resolve", "--worktree", wt, "--state", state,
            "--force", "--commit", "--json",
        ])
        assert rc == MODULE.EXIT_OK, resolved
        assert not scratch_dir.exists()
        assert not Path(wt).exists()


def _advance_local_main(repo, name):
    """Add a commit to LOCAL main that origin does not have (origin is never pushed).

    Stages the one file BY NAME, not `add -A`: worktrees live under the primary's own
    `.claude/worktrees/`, and `add -A` in the primary commits each of them to main as a
    gitlink. That artifact is invisible to assertions about the trunk's own files, but
    it shows up verbatim in any measurement of what the base gained since a fork.
    """
    (repo / f"{name}.txt").write_text("local-only\n")
    _git(["add", f"{name}.txt"], repo)
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


# --- IMP-20260806-42d183: a refusal that coordinates instead of only refusing -------
#
# The dirty-primary refusal is a good message — it lists the files, gives options and
# points at session-mgmt. What it does NOT do is any of the coordination it describes,
# so the cost lands entirely on the blocked session: find the running sessions, work out
# whose files those are, go write in the shared mailbox. That got done BY HAND three
# times (broadcast.md, 2026-08-05 x2 and 2026-08-06), which is the definition of a
# friction the tool should absorb. Only direction (1) of the ticket is implemented here:
# leave the refusal exactly as it is, and post the notice automatically.

@gitmark
def test_a_dirty_primary_broadcast_names_the_blocked_branch_and_the_files(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "bcast",
                            "--state", state, "--json"])
    wt, branch = opened["path"], opened["branch"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])

    mailbox = repo / ".cache" / "coordination" / "broadcast.md"
    assert not mailbox.exists()
    (repo / "f").write_text("someone else's uncommitted work\n")
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK and cut["landed"] is False

    posted = mailbox.read_text()
    assert branch in posted, "a notice nobody can attribute is worse than none"
    # the dirty LINE, parsed — not a substring search over the whole record. `f` is one
    # character, and the 16-hex marker contains an `f` about 64% of the time, so the
    # loose version's discriminating power was a coin flip on the slug and the wording.
    line = next(ln for ln in posted.splitlines() if ln.startswith("dirty: "))
    assert [c.strip("`") for c in line.removeprefix("dirty: ").split(", ")] == ["f"]
    assert wt in posted, "the reader has to be able to find the blocked session"
    # the refusal itself is unchanged, and now says where it wrote
    assert "dirty" in cut["error"]
    assert "broadcast.md" in cut["error"]
    assert cut["broadcast"] == str(mailbox)


@gitmark
def test_a_dirty_primary_broadcast_is_not_repeated_for_the_same_block(scratch):
    """Polling is the expected usage — the refusal literally says "re-run cutover once
    the primary is clean". If each attempt appended, the mailbox other humans read would
    be flooded by the one participant that is a program."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", "bcast-idem",
                            "--state", state, "--json"])
    wt, branch = opened["path"], opened["branch"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])

    mailbox = repo / ".cache" / "coordination" / "broadcast.md"
    (repo / "f").write_text("dirty\n")
    for _ in range(3):
        rc, _cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                              "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
    assert mailbox.read_text().count(branch) == 1

    # but a DIFFERENT block is genuinely new information and must be posted.
    # `add g`, NOT `add -A`: the scratch fixture ships no .gitignore, so `-A` would
    # sweep in the tool's OWN mailbox and lock file and report them as someone's
    # uncommitted work — the exact inverse of production, where `.cache/` is ignored
    # (that is the premise the whole best-effort argument rests on).
    (repo / "g").write_text("a second dirty file\n")
    _git(["add", "g"], repo)
    rc, _cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                          "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert mailbox.read_text().count(branch) == 2


@gitmark
@pytest.mark.parametrize("break_it, which", [
    # a DIRECTORY where the file goes: read_text() raises before any write is attempted
    (lambda mb: (mb.parent.mkdir(parents=True, exist_ok=True), mb.mkdir()), "read"),
    # a read-only FILE: everything succeeds until `open("a")` — the write path itself.
    # Without this case the guard never reaches the append, and an implementation whose
    # write sits OUTSIDE the try/except passes anyway. Verified: moving the `open("a")`
    # block out of the `except OSError` arm leaves the directory case green and turns
    # this one red with a PermissionError traceback. Found by review of the first
    # version of this test, which had only the directory case.
    (lambda mb: (mb.parent.mkdir(parents=True, exist_ok=True),
                 mb.write_text("# mailbox\n"), mb.chmod(0o444)), "write"),
])
def test_a_dirty_primary_broadcast_failure_never_becomes_the_refusal(
        scratch, break_it, which):
    """`.cache/` is gitignored scratch, not a source of truth. If posting the notice
    fails, the operator must still be told the real reason — swapping a coordination
    courtesy in for the diagnosis would be strictly worse than not having it."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "do it", "--slug", f"bcast-ro-{which}",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])

    mailbox = repo / ".cache" / "coordination" / "broadcast.md"
    break_it(mailbox)
    try:
        (repo / "f").write_text("dirty\n")
        rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
        assert rc == MODULE.EXIT_BLOCK
        assert cut["landed"] is False
        assert "dirty" in cut["error"], "the diagnosis must survive a failed courtesy"
        assert "f" in cut["dirty_files"]
        assert "broadcast.md" not in cut["error"], \
            "do not point at a file that was not written"
        assert cut.get("broadcast") is None
        assert "notes.txt" not in _local_main_files(repo)
    finally:
        if mailbox.is_file():
            mailbox.chmod(0o644)


def test_a_dirty_primary_broadcast_keys_on_every_file_not_just_the_shown_ten(
        tmp_path, monkeypatch):
    """The record shows ten paths but the key must cover all of them: an 11th file
    changing is a different block, and suppressing it would make the docs' claim
    ("idempotent per branch + dirty set") false for exactly the diffs big enough to
    matter. Same reason the join is NUL rather than newline — `_c_unquote` returns real
    filenames, and a newline separator collides `["a\\nb"]` with `["a", "b"]`.
    Found by review of IMP-20260806-42d183."""
    primary = tmp_path / "p"
    primary.mkdir()
    mailbox = primary / MODULE.COORDINATION_BROADCAST_REL
    twelve = [f"f{i}.txt" for i in range(12)]

    # the day is part of the key, so a real clock makes this flake when UTC midnight
    # lands between two of the six calls below
    class _Fixed:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(MODULE, "datetime", _Fixed)

    assert MODULE._broadcast_cutover_block(primary, "feat/x", twelve)
    assert mailbox.read_text().count("kg-cutover-block") == 1
    # same input again: still one
    assert MODULE._broadcast_cutover_block(primary, "feat/x", twelve)
    assert mailbox.read_text().count("kg-cutover-block") == 1
    # the 12th file changes — invisible in the shown ten, but a different block
    assert MODULE._broadcast_cutover_block(primary, "feat/x", twelve[:11] + ["other.txt"])
    assert mailbox.read_text().count("kg-cutover-block") == 2
    # separator collision: these two dirty sets must not share a key
    assert MODULE._broadcast_cutover_block(primary, "feat/x", ["a\nb"])
    assert MODULE._broadcast_cutover_block(primary, "feat/x", ["a", "b"])
    assert mailbox.read_text().count("kg-cutover-block") == 4
    # the paths go into markdown a human reads, so they are backtick-quoted and their
    # newlines escaped: unquoted, `a\nb` splits the record's own dirty line in two and a
    # leading `#` renders as a heading. test_cutover_dirty_refusal_unquotes_special_paths
    # proves this path really does receive names like that.
    lines = mailbox.read_text().splitlines()
    assert "dirty: `a\\nb`" in lines
    assert MODULE._broadcast_cutover_block(primary, "feat/x", ["#h.txt", "-i.txt"])
    assert "dirty: `#h.txt`, `-i.txt`" in mailbox.read_text().splitlines()

    # and a branch we could not determine is named as such rather than guessed
    assert MODULE._broadcast_cutover_block(primary, None, ["z.txt"])
    assert "(unknown)" in mailbox.read_text()


def test_a_dirty_primary_broadcast_marker_expires_with_the_day(tmp_path, monkeypatch):
    """Nobody deletes these. The record asks the reader to remove it when handled; the
    real mailbox is 694 lines going back to 2026-08-05 with not one entry removed. So a
    marker that never expires means the same branch blocked by the same file next week —
    slugs repeat, and the recurring dirty file is the same `ops/release.sh` — posts
    NOTHING, and the second block is invisible. The day is part of the key for that
    reason, and this is the only test that can see it. Found by review."""
    primary = tmp_path / "p"
    primary.mkdir()
    mailbox = primary / MODULE.COORDINATION_BROADCAST_REL

    class _FrozenClock:
        stamp = datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.stamp

    monkeypatch.setattr(MODULE, "datetime", _FrozenClock)
    same = ("feat/x", ["ops/release.sh"])
    assert MODULE._broadcast_cutover_block(primary, *same)
    assert MODULE._broadcast_cutover_block(primary, *same)
    assert mailbox.read_text().count("kg-cutover-block") == 1, "same day: one notice"

    # a later time on the SAME day is still the same block
    _FrozenClock.stamp = datetime(2026, 8, 8, 23, 59, tzinfo=timezone.utc)
    assert MODULE._broadcast_cutover_block(primary, *same)
    assert mailbox.read_text().count("kg-cutover-block") == 1

    # the next day it is news again
    _FrozenClock.stamp = datetime(2026, 8, 9, 0, 1, tzinfo=timezone.utc)
    assert MODULE._broadcast_cutover_block(primary, *same)
    assert mailbox.read_text().count("kg-cutover-block") == 2


def test_a_dirty_primary_broadcast_names_the_blocked_worktree(tmp_path):
    primary = tmp_path / "p"
    primary.mkdir()
    mailbox = primary / MODULE.COORDINATION_BROADCAST_REL

    assert MODULE._broadcast_cutover_block(
        primary, "feat/x", ["a.txt"], worktree="/w/tr ee\nX")
    branch_lines = [line for line in mailbox.read_text().splitlines()
                    if line.startswith("被擋的分支")]
    assert branch_lines == ["被擋的分支:`feat/x` (worktree `/w/tr ee\\nX`)"]

    assert MODULE._broadcast_cutover_block(primary, "feat/x", ["b.txt"])
    branch_lines = [line for line in mailbox.read_text().splitlines()
                    if line.startswith("被擋的分支")]
    assert branch_lines[-1] == "被擋的分支:`feat/x`"


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
    # Contract update (2026-08-03): the fixture's file is routed to no gate, so
    # the always-planned coverage gate warns. `warn` still lands; what changed is
    # that "nothing was checked" is now visible instead of reading as pass.
    assert gate["verdict"] == "warn"
    assert [g["name"] for g in gate["gates"] if g["status"] == "warn"] == ["coverage"]

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
    _seed_python_scan(repo)
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
def test_cutover_refuses_while_a_gate_was_left_inconclusive(scratch):
    """An inconclusive gate folds the VERDICT to warn, and a warn LANDS — so on its own
    the fold turns "this red could not be attributed" into "shipped with a note". That
    is the disarm direction, and it is reachable without any tag surgery: every
    concurrent `preflight` / `catchup` / `sync` / `deploy` runs `git fetch --prune`,
    which imports new origin tags and moves the snapshot under an unrelated gate.

    The summary already told the operator to re-run the gate; nothing made that happen.
    cutover now refuses, which costs one gate re-run and makes the instruction real.
    Found by review of IMP-20260805-4ec901."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _seed_python_scan(repo)
    rc, opened = _run_json(
        ["open", "--intent", "add backend endpoint", "--slug", "inconc-refuse",
         "--state", state, "--json"])
    wt = opened["path"]
    src = Path(wt) / "backend" / "src" / "kg" / "app.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("x = 1\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "backend src"], wt)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK and gate["verdict"] == "warn"

    # poison exactly one row the way a real refs-changed run would, then re-fold
    rec_path = MODULE._gate_record_path(state, wt)
    rec = json.loads(rec_path.read_text())
    poisoned = rec["gates"][0]["name"]
    rec["gates"][0].update({"status": "inconclusive", "rc": 1, "refs_changed": True})
    rec["verdict"] = MODULE.aggregate_verdict(rec["gates"])
    # if this were "block" the test would prove nothing — the existing block refusal
    # would catch it and the new one would never be exercised
    assert rec["verdict"] == "warn"
    rec_path.write_text(json.dumps(rec))

    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False
    assert "inconclusive" in cut["error"]
    assert poisoned in cut["error"], "the refusal must name which gate to re-run"
    assert "backend/src/kg/app.py" not in _local_main_files(repo)


# --- IMP-20260806-945e01: the verdict must be bound to the tree that LANDS ---------
# `head_sha` pins a verdict to the code the gate READ. Nothing pinned it to the code
# it lands ALONGSIDE. cutover's first act is `rebase <local trunk>`, so for a branch
# behind the trunk the gate judges a tree that never lands — and the stale-HEAD guard
# cannot see it, because the HEAD did not move, only the base did.


@gitmark
def test_gate_refuses_to_judge_a_tree_that_is_behind_base(scratch):
    # The cheap half: refuse BEFORE spending a gate run on a tree that cannot land.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "behind2",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)
    _advance_local_main(repo, "peer")

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert gate["behind_commits"] == 1
    assert gate["base_changed_files"] == ["peer.txt"]
    # refused BEFORE running anything: no verdict cached for a later cutover to consume
    assert not MODULE._gate_record_path(state, wt).exists()


@gitmark
def test_gate_plan_only_still_previews_a_behind_tree(scratch):
    # --plan-only runs no gate and writes no verdict, so it must stay usable as the
    # preview the refusal message points at (a refusal whose own advice is blocked is
    # a lie).
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "behind3",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)
    _advance_local_main(repo, "peer")
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state,
                          "--plan-only", "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["verdict"] == "planned"


@gitmark
def test_cutover_refused_when_the_base_moved_under_a_fresh_verdict(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "behind",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK and gate["verdict"] == "warn"
    gated_head = gate["head_sha"]

    _advance_local_main(repo, "peer")
    # WHO PRODUCED THE REFUSAL: pin that the stale-HEAD guard CANNOT be what fires —
    # the worktree HEAD is byte-identical to the one the verdict recorded.
    assert _git(["rev-parse", "HEAD"], wt) == gated_head

    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False
    assert cut["behind_commits"] == 1
    assert cut["base_changed_files"] == ["peer.txt"]
    assert "peer.txt" in _local_main_files(repo)       # the peer's work is still there
    assert "notes.txt" not in _local_main_files(repo)  # ours did NOT land


@gitmark
def test_cutover_dry_run_also_refuses_when_the_base_moved(scratch):
    # A refusal that only exists under --commit teaches the dry-run to lie: the dry-run
    # is what an agent reads to decide whether cutover is ready.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "behind-dry",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    _advance_local_main(repo, "peer")

    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False
    assert cut["behind_commits"] == 1


@gitmark
def test_cutover_refuses_when_the_rebase_moves_head_off_the_gated_sha(scratch,
                                                                      monkeypatch):
    # The window the pre-flight containment check cannot close: a peer cutover lands on
    # local main AFTER the check and BEFORE the rebase (the rebase is deliberately taken
    # inside the trunk lock, against the CURRENT trunk). Injected at the lock seam —
    # real git, real rebase, no fake for the thing under test. The terminal invariant:
    # the sha that lands must be the sha that was gated.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "raced",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    gated_head = gate["head_sha"]

    real_lock = MODULE._main_advance_lock

    @contextmanager
    def racing_lock(primary):
        with real_lock(primary):
            _advance_local_main(repo, "peer")   # a peer landed inside the window
            yield

    monkeypatch.setattr(MODULE, "_main_advance_lock", racing_lock)
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert cut["landed"] is False
    assert cut["gated_sha"] == gated_head
    assert cut["rebased_sha"] != gated_head
    assert "notes.txt" not in _local_main_files(repo)  # main did NOT advance
    assert "peer.txt" in _local_main_files(repo)       # the peer's work is intact


@gitmark
def test_behind_base_refusal_renders_in_human_mode_too(scratch):
    # The refusal must be legible without --json: an operator reading the terminal is
    # the reader most likely to act on it, and a guard that only speaks JSON reads as
    # silence to them. Also pins that stdout carries the human line INSTEAD of JSON.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "behind-human",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    _advance_local_main(repo, "peer")

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = MODULE.main(["cutover", "--worktree", wt, "--state", state, "--commit"])
    out = buf.getvalue()
    assert rc == MODULE.EXIT_BLOCK
    assert out.startswith("✗ cutover refused:")
    assert "1 commit(s), 1 file(s) changed on main" in out
    # the remedy is spelled out verbatim — and it names `catchup`, not raw git.
    # (The original reason was that the rebase kept conflicting on a 280KB generated
    # file; that file left version control in IMP-20260807-b9526c. The routing still
    # holds for the reason that outlived it: an error message telling an agent to go
    # run `git rebase` hands off a step whose failure mode is unbounded, and neither
    # `land` nor the gate sees what happens next.)
    assert f"catchup --worktree {wt} --commit" in out
    with pytest.raises(json.JSONDecodeError):       # human mode, not a JSON dump
        json.loads(out)


@gitmark
def test_landed_sha_equals_gated_sha_when_base_is_contained(scratch):
    # The property the guard buys, stated positively: with the base already contained,
    # cutover's rebase is a no-op, so the sha that LANDS is the sha that was GATED.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix thing", "--slug", "same",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "notes.txt"], wt); _git(["commit", "-qm", "work"], wt)
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and cut["landed"] is True
    assert cut["sha"] == gate["head_sha"]


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


def _cripple_worktree(wt):
    """Reproduce the observed partial teardown (IMP-20260806-1359bd step 1).

    `git worktree remove --force` unlinks the worktree's `.git` file EARLY, then
    spends however long it takes to rm the tree itself (19 GB of iOS DerivedData in
    the incident). Interrupted in that window — a caller timeout — the directory
    survives with no `.git`, and git marks the entry `prunable`."""
    (Path(wt) / ".git").unlink()


def _landed_worktree(tmp_path, repo, state, slug):
    """open -> work -> gate -> cutover: a worktree whose branch IS landed, i.e. one
    that resolve's landed-floor will happily wave through to teardown."""
    rc, opened = _run_json(["open", "--intent", f"fix {slug}", "--slug", slug,
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("did the thing\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    rc, _ = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and cut["landed"] is True
    return wt, opened["branch"]


def _targets_a_protected_branch(payload, base="main"):
    """Any planned OR executed git step in a resolve payload that would delete the
    base branch, locally or on the remote."""
    steps = list(payload.get("plan") or []) + list(payload.get("executed") or [])
    bad = {f"git branch -D {base}", f"git push origin --delete {base}"}
    return [s["cmd"] for s in steps if s.get("cmd") in bad]


@gitmark
def test_resolve_after_a_partial_teardown_never_retargets_the_base_branch(scratch):
    # IMP-20260806-1359bd, the whole incident in one test.
    #
    # Root cause: resolve derived the branch with `git rev-parse --abbrev-ref HEAD`
    # run with cwd=<worktree>. With the worktree's `.git` gone, git's repository
    # DISCOVERY WALKS UP the directory tree, finds the primary repo (worktrees live
    # at <repo>/.claude/worktrees/<slug>), and answers with the PRIMARY's branch —
    # `main`. resolve then planned `branch -D main` and `push origin --delete main`.
    # Only git's own refusals (main was checked out; main is the remote's default
    # branch) stopped it. Neither refusal belongs to this tool.
    #
    # The authoritative answer was available the whole time: `git worktree list
    # --porcelain` still reports `branch refs/heads/<the real branch>` for a
    # prunable entry. Note the landed-floor cannot help here — it is asked about
    # `main`, and `main` is trivially landed in `main`.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, branch = _landed_worktree(tmp_path, repo, state, "partial-teardown")

    _cripple_worktree(wt)
    # git itself really does misreport here — asserted against git directly rather
    # than through MODULE._current_branch, so that hardening that helper later as
    # defence-in-depth improves the tool instead of breaking this test.
    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], wt) == "main"
    # ...while git's worktree list still knows the truth
    assert any(w.get("branch") == branch and MODULE._norm(w["path"]) == MODULE._norm(wt)
               for w in MODULE.wr._worktrees())

    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state, "--json"])
    assert _targets_a_protected_branch(res) == [], (
        f"dry-run planned a base-branch deletion: {res}")
    assert res.get("branch") != "main"

    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert _targets_a_protected_branch(res) == [], (
        f"resolve EXECUTED a base-branch deletion: {res}")
    assert res.get("branch") != "main"
    # the repository survived — these are the two things git refused for us before
    assert "main" in _local_branches(repo)
    assert "main" in _local_branches(remote)


@gitmark
def test_resolve_refuses_when_asked_to_delete_the_base_branch_outright(scratch):
    # Guard (b), independent of path resolution: `branch -D main` is never a
    # legitimate resolve outcome, so an explicit --branch main must be refused
    # rather than merely refused downstream by git. The registry already owns this
    # invariant for sweep (worktree_registry.sweep_guards / _step_touches_protected);
    # resolve simply did not consult it.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, _branch = _landed_worktree(tmp_path, repo, state, "explicit-base")

    rc, res = _run_json(["resolve", "--worktree", wt, "--branch", "main",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, res
    # assert the decision, not a prose substring, and not the mere ABSENCE of a plan
    # key — on a refusal payload neither `plan` nor `executed` exists, so
    # _targets_a_protected_branch() would be vacuously satisfied here.
    assert res.get("reason_code") == "branch-contradicts-git", res
    assert "main" in _local_branches(repo)
    assert "main" in _local_branches(remote)
    # refused BEFORE mutating: the worktree is untouched
    assert Path(wt).is_dir()


@gitmark
def test_resolve_stops_when_no_authority_vouches_for_the_named_branch(scratch):
    # Guard (c). The tool ALREADY printed "no active registry record for branch=main"
    # during the incident — it had detected that its target was wrong and walked into
    # the destructive steps anyway. A detected anomaly must halt before mutation.
    #
    # Asserted on an UNPROTECTED branch on purpose, so neither guard (a) nor (b) can
    # be what stops it: --branch names a real branch that git does not associate with
    # this path and that the ledger holds no active record for. The old code took the
    # explicit --branch at face value, and the landed-floor waves a landed branch
    # through, so this deleted a bystander branch outright.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, _branch = _landed_worktree(tmp_path, repo, state, "wrong-branch")
    _git(["branch", "feat/someone-elses-work"], repo)   # landed (it IS main), unprotected

    rc, res = _run_json(["resolve", "--worktree", wt, "--branch", "feat/someone-elses-work",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, res
    assert "feat/someone-elses-work" in _local_branches(repo)
    assert Path(wt).is_dir()


@gitmark
def test_resolve_proceeds_when_only_the_ledger_vouches(scratch):
    # The other side of the corroboration rule, so it cannot degenerate into "any
    # explicit --branch is refused": when the ledger DOES hold an active record for
    # the named branch, that is a sufficient authority on its own.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, branch = _landed_worktree(tmp_path, repo, state, "ledger-vouches")

    rc, res = _run_json(["resolve", "--worktree", wt, "--branch", branch,
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, res
    assert branch not in _local_branches(repo)


@gitmark
def test_resolve_of_a_live_worktree_survives_an_already_closed_ledger(scratch):
    # Regression guard for the rule's SHAPE. Requiring an active ledger record
    # unconditionally would look like a tighter safety net and would in fact strand
    # every interrupted teardown: resolve strikes the ledger BEFORE the git steps, so
    # by the time a run is interrupted the record is already closed. Finishing that
    # run is precisely what IMP-20260806-1359bd asks for, so git's worktree list must
    # be sufficient on its own.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, branch = _landed_worktree(tmp_path, repo, state, "closed-ledger")
    ledger = json.loads(Path(state).read_text())
    for r in ledger["records"]:
        r["status"] = "merged"
    Path(state).write_text(json.dumps(ledger))

    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, res
    assert res["branch"] == branch
    assert branch not in _local_branches(repo)
    assert not Path(wt).exists()


@gitmark
def test_resolve_finishes_an_interrupted_teardown_instead_of_stranding_it(scratch):
    # The flip side of guard (a): re-running resolve after a partial teardown is a
    # LEGITIMATE intent — the operator wants the teardown finished. Refusing to
    # misfire is necessary but not sufficient; the tool must still converge on zero
    # residue, targeting the branch git's worktree list names.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, branch = _landed_worktree(tmp_path, repo, state, "finish-teardown")
    _cripple_worktree(wt)

    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, res
    assert res["branch"] == branch
    assert branch not in _local_branches(repo)
    assert not Path(wt).exists()
    # git no longer carries a stale entry for it
    assert all(MODULE._norm(w["path"]) != MODULE._norm(wt)
               for w in MODULE.wr._worktrees())
    recs = {r["branch"]: r for r in json.loads(Path(state).read_text())["records"]}
    assert recs[branch]["status"] == "merged"


@gitmark
def test_resolve_protects_the_trunk_even_under_a_different_base(scratch):
    # The protected set used to be derived SOLELY from --base (plus the primary's
    # current checkout), so it was a floor the caller could lower. Executed during
    # review: with the primary checked out off main and `--base origin/prod` — a real
    # ref in this repo's release plane, so a plausible copy-paste — `main` was absent
    # from the protected set and `git branch -D main` SUCCEEDED. Only the bare repo's
    # HEAD protection stopped the remote half, which is exactly the external net this
    # entry exists to stop relying on.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _git(["update-ref", "refs/heads/prod", "refs/heads/main"], remote)
    # a primary parked elsewhere (repo surgery / hotfix / bisect), and a worktree that
    # has the trunk itself checked out. Order matters: main must be free first.
    _git(["checkout", "-q", "-b", "staging"], repo)
    mainwt = tmp_path / "mainwt"
    _git(["worktree", "add", "-q", str(mainwt), "main"], repo)

    rc, res = _run_json(["resolve", "--worktree", str(mainwt), "--base", "origin/prod",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, res
    assert res.get("reason_code") == "protected-branch", res
    assert "main" in _local_branches(repo)
    assert "main" in _local_branches(remote)


@gitmark
def test_resolve_refuses_when_git_contradicts_the_named_branch(scratch):
    # Executed during review: with two live worktrees, targeting alpha's PATH while
    # naming bravo's BRANCH tore down alpha and deleted origin/<bravo>. The ledger
    # vouched — because the record that matched belonged to a different path — and
    # `branch -D` was refused only by git's "used by worktree at ...".
    #
    # The structural error was collapsing "git has no information" and "git actively
    # contradicts you" into one condition. The second is strictly worse.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    alpha, _ = _landed_worktree(tmp_path, repo, state, "alpha")
    rc, bravo_opened = _run_json(["open", "--intent", "second stream", "--slug", "bravo",
                                  "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    bravo_branch = bravo_opened["branch"]
    _git(["push", "-q", "origin", bravo_branch], repo)
    assert bravo_branch in _local_branches(remote)

    rc, res = _run_json(["resolve", "--worktree", alpha, "--branch", bravo_branch,
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, res
    assert res.get("reason_code") == "branch-contradicts-git", res
    # neither worktree touched, and bravo's remote branch survives
    assert Path(alpha).is_dir()
    assert Path(bravo_opened["path"]).is_dir()
    assert bravo_branch in _local_branches(repo)
    assert bravo_branch in _local_branches(remote)


@gitmark
def test_resolve_reclaims_the_directory_when_git_has_lost_the_entry(scratch):
    # Silent false success, found in review: with the admin entry already gone (an
    # errored `worktree remove` drops it, and so does any prune elsewhere in the repo)
    # no directory-removal step was planned at all, yet resolve reported failures: 0
    # and exited 0 — while the whole tree, 19 GB of it in the incident's shape, stayed
    # on disk. The ledger still records the path, so the branch is derivable and the
    # directory is reclaimable.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, branch = _landed_worktree(tmp_path, repo, state, "lost-entry")
    _cripple_worktree(wt)
    _git(["worktree", "prune"], repo)                 # admin entry gone, tree remains
    assert Path(wt).is_dir()
    assert all(MODULE._norm(w["path"]) != MODULE._norm(wt)
               for w in MODULE.wr._worktrees())

    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, res
    assert res["branch"] == branch                    # derived from the ledger, not HEAD
    assert not Path(wt).exists(), "reported success while leaving the tree behind"
    assert branch not in _local_branches(repo)


@gitmark
def test_resolve_aborts_the_remaining_steps_when_a_critical_one_fails(scratch):
    # The other half of the incident's trace: `worktree remove --force` returned 128
    # and the loop ran `branch -D` and `push origin --delete` anyway. Correct targeting
    # makes those harmless; it does not make "carry on after a destructive step failed"
    # correct. Here the directory removal is made to fail (its parent is read-only), so
    # the admin strike and the branch deletions must not proceed.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt, branch = _landed_worktree(tmp_path, repo, state, "critical-abort")
    _cripple_worktree(wt)
    parent = Path(wt).parent
    parent.chmod(0o500)                               # rm cannot unlink inside it
    try:
        rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    finally:
        parent.chmod(0o700)

    assert rc == MODULE.EXIT_BLOCK, res
    assert res["aborted_after"] == "remove leftover worktree directory", res
    ran = [r["cmd"] for r in res["executed"]]
    assert not any("branch -D" in c for c in ran), ran
    assert not any("--delete" in c for c in ran), ran
    assert branch in _local_branches(repo)


@gitmark
def test_resolve_refuses_a_path_that_is_not_a_registered_worktree(scratch):
    # The general form of the walk-up bug: ANY directory inside the repo answers
    # `rev-parse --abbrev-ref HEAD` with the enclosing checkout's branch. Only paths
    # git actually lists as worktrees may be resolved.
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    stray = repo / "not-a-worktree"
    stray.mkdir()

    rc, res = _run_json(["resolve", "--worktree", str(stray), "--state", state,
                         "--commit", "--json"])
    # EXIT_USAGE, not EXIT_BLOCK: this is "you pointed me at the wrong thing", the
    # same class as cutover's own not-a-worktree and detached-HEAD refusals. The
    # safety refusals (protected branch, primary worktree, contradiction) are the
    # ones that carry EXIT_BLOCK.
    assert rc == MODULE.EXIT_USAGE, res
    assert res.get("reason_code") == "not-a-worktree", res
    assert "main" in _local_branches(repo)


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
def test_sync_main_commit_serializes_primary_advance(scratch, monkeypatch):
    """origin->local ff must share the primary-advance lock with cutover."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _advance_origin_main(tmp_path, repo, "locked")
    events = []
    real_lock = MODULE._main_advance_lock

    @contextmanager
    def observed_lock(primary):
        events.append(("enter", Path(primary).resolve()))
        with real_lock(primary):
            yield
        events.append(("exit", Path(primary).resolve()))

    monkeypatch.setattr(MODULE, "_main_advance_lock", observed_lock)
    rc, result = _run_json(["sync-main", "--state", state, "--commit", "--json"])

    assert rc == MODULE.EXIT_OK
    assert result["verdict"] == "ff"
    assert events == [("enter", repo.resolve()), ("exit", repo.resolve())]


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
    remote_only = _git(["rev-parse", "HEAD"], other)
    _git(["push", "-q", "origin", "HEAD:refs/heads/fixture-remote-only"], other)
    _git(["update-ref", "refs/heads/prod", remote_only], remote)
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


# ---------------------------------------------------------------------------
# orchestrator provenance (IMP-0045)
#
# `gate` runs each shell gate with the WORKTREE as cwd, so the TOOLS come from the
# worktree; `plan_gates` comes from whichever copy of this file the shell resolved.
# Those can be different commits, and the verdict record said nothing about which one
# produced it — so a lax-orchestrator green could be handed to a strict cutover at the
# same HEAD and be accepted. Provenance binds the verdict to its verifier.
# ---------------------------------------------------------------------------
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _run_text(argv):
    """Run the CLI in HUMAN mode and return (rc, stdout). The text report is a
    first-class surface: a field that exists only in --json is invisible to the agent
    reading the terminal."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = MODULE.main(argv)
    return rc, buf.getvalue()


def _open_wt(state, slug="prov"):
    rc, opened = _run_json(["open", "--intent", "add a thing", "--slug", slug,
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    return wt


@gitmark
def test_gate_record_carries_orchestrator_identity(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    orch = gate["orchestrator"]
    assert orch["path"] == "ops/worktree_orchestrate.py"
    assert _HEX64.match(orch["sha256"])
    assert orch["resolved"] == str(Path(MODULE.__file__).resolve())


@gitmark
def test_gate_names_the_empty_worktree(scratch):
    """An empty diff is a legal re-gate, but its record must say it verified nothing."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "check an empty tree", "--slug", "empty-gate",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK

    rc, gate = _run_json(["gate", "--worktree", opened["path"],
                          "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["changed_files"] == []
    assert gate["no_changed_files"] is True
    assert gate["verdict"] == "pass"

    rc, text = _run_text(["gate", "--worktree", opened["path"],
                          "--state", state])
    assert rc == MODULE.EXIT_OK
    assert "no changes in this worktree" in text
    assert opened["path"] in text

    rc, receipt = _run_text(["gate", "--worktree", opened["path"],
                             "--state", state, "--receipt-line"])
    assert rc == MODULE.EXIT_OK
    assert "no-changes" in receipt


@gitmark
def test_gate_plan_only_receipt_does_not_record_empty_signal(scratch):
    """Plan-only previews must not masquerade as a recorded empty verification."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "plan-reg.json")
    rc, opened = _run_json(
        ["open", "--intent", "preview empty tree", "--slug", "plan-empty",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK

    rc, receipt = _run_text(
        ["gate", "--worktree", opened["path"], "--state", state,
         "--plan-only", "--receipt-line"]
    )
    assert rc == MODULE.EXIT_OK
    assert "gate=planned" in receipt
    assert "record=<not recorded>" in receipt
    assert "no-changes" not in receipt
    assert not MODULE._gate_record_path(state, opened["path"]).exists()


@gitmark
def test_gate_marks_a_changed_worktree_as_nonempty(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state, slug="nonempty-gate")

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["changed_files"] == ["notes.txt"]
    assert gate["no_changed_files"] is False

    rc, receipt = _run_text(["gate", "--worktree", wt, "--state", state,
                             "--receipt-line"])
    assert rc == MODULE.EXIT_OK
    assert "no-changes" not in receipt


@gitmark
def test_gate_publishes_independent_progress_without_polluting_json(
        scratch, monkeypatch, capsys):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "progress-reg.json")
    _seed_python_scan(repo)
    wt = _open_wt(state, slug="progress-gate")
    # Make the impact plan contain two gates while keeping this regression offline.
    source = Path(wt) / "ops" / "tests" / "test_worktree_orchestrate.py"
    source.parent.mkdir(parents=True)
    source.write_text("# changed test fixture\n", encoding="utf-8")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "change orchestrator"], wt)

    def fake_run_gate(spec, worktree, *, record_path=None, state=None):
        return {"name": spec["name"], "category": spec["category"],
                "level": spec["level"], "status": "pass", "rc": 0,
                "summary": "stubbed gate"}

    progress_path = MODULE._gate_progress_path(state, wt)
    atomic_writes = []
    write_atomic = MODULE._write_atomic

    def recording_write_atomic(path, body):
        atomic_writes.append((path, body))
        write_atomic(path, body)

    monkeypatch.setattr(MODULE, "_run_gate", fake_run_gate)
    monkeypatch.setattr(MODULE, "_write_atomic", recording_write_atomic)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    stdout = json.dumps(gate)
    assert json.loads(stdout)["verdict"] == "pass"

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert len(atomic_writes) == len(gate["gates"]) + 1
    assert [path for path, _ in atomic_writes] == [progress_path] * len(atomic_writes)
    assert all(json.loads(body)["schema"] == MODULE.GATE_PROGRESS_SCHEMA
               for _, body in atomic_writes)
    assert progress["run_id"]
    assert progress["generation"] >= 1
    assert progress["head_sha"] == gate["head_sha"]
    assert progress["plan_total"] == len(gate["plan"]) == 3
    assert progress["done"] == progress["plan_total"]
    assert progress["current"] is None
    assert progress["completed"] == [
        {"name": result["name"], "status": result["status"]}
        for result in gate["gates"]
    ]

    stderr = capsys.readouterr().err
    assert f"phase=plan gates={progress['plan_total']}" in stderr
    for result in gate["gates"]:
        assert f"phase=gate gate={result['name']}" in stderr
        assert f"status={result['status']}" in stderr
    assert str(progress_path) in stderr


@gitmark
def test_newer_gate_owns_progress_sidecar_against_stale_run(scratch, monkeypatch):
    """A slower older gate must not publish after a newer run takes ownership."""
    tmp_path, repo, _remote = scratch
    state_path = str(tmp_path / "concurrent-progress.json")
    wt = _open_wt(state_path, slug="concurrent-progress")
    source = Path(wt) / "ops" / "tests" / "test_worktree_orchestrate.py"
    source.parent.mkdir(parents=True)
    source.write_text("# changed test fixture\n", encoding="utf-8")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "change orchestrator"], wt)

    nested = False
    runs = []
    newer_progress = []

    def fake_run_gate(spec, worktree, *, record_path=None, state=None):
        nonlocal nested
        if not nested:
            nested = True
            rc, newer = _run_json(["gate", "--worktree", wt, "--state", state_path,
                                   "--json"])
            assert rc == MODULE.EXIT_OK, newer
            runs.append(newer)
            newer_progress.append(json.loads(
                MODULE._gate_progress_path(state_path, wt).read_text()))
        return {"name": spec["name"], "category": spec["category"],
                "level": spec["level"], "status": "pass", "rc": 0,
                "summary": "stubbed gate"}

    monkeypatch.setattr(MODULE, "_run_gate", fake_run_gate)
    rc, older = _run_json(["gate", "--worktree", wt, "--state", state_path, "--json"])
    assert rc == MODULE.EXIT_OK, older
    assert len(runs) == 1
    newer = runs[0]
    progress = json.loads(MODULE._gate_progress_path(state_path, wt).read_text())
    assert newer_progress[0]["run_id"] == progress["run_id"]
    assert newer["head_sha"] == older["head_sha"]
    assert progress["generation"] > 1
    assert progress["done"] == progress["plan_total"] == len(newer["gates"])


@gitmark
def test_gate_warns_when_the_primary_is_dirty(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "primary-dirty.json")
    rc, opened = _run_json(
        ["open", "--intent", "observe primary drift", "--slug", "primary-dirty",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK

    (repo / "f").write_text("leaked edit\n")
    try:
        rc, gate = _run_json(["gate", "--worktree", opened["path"],
                              "--state", state, "--json"])
        assert rc == MODULE.EXIT_OK
        assert gate["primary_dirty"] == ["f"]
        assert gate["primary_dirty_error"] is None
        assert gate["verdict"] == "pass"

        rc, text = _run_text(["gate", "--worktree", opened["path"],
                              "--state", state])
        assert rc == MODULE.EXIT_OK
        assert "primary working tree has 1 uncommitted tracked file(s): f" in text
        assert "rather than this worktree" in text
    finally:
        (repo / "f").write_text("base\n")


@gitmark
def test_gate_reports_a_clean_primary(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "primary-clean.json")
    wt = _open_wt(state, slug="primary-clean")

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["primary_dirty"] == []
    assert gate["primary_dirty_error"] is None


@gitmark
def test_gate_reports_primary_status_failure(scratch, monkeypatch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "primary-status-failure.json")
    wt = _open_wt(state, slug="primary-status-failure")
    original_git = MODULE._git

    def fail_primary_status(argv, cwd=None):
        if list(argv) == ["status", "--porcelain", "--untracked-files=no"] \
                and Path(cwd).resolve() == repo.resolve():
            return 7, ""
        return original_git(argv, cwd=cwd)

    monkeypatch.setattr(MODULE, "_git", fail_primary_status)
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["primary_dirty"] == []
    assert "rc=7" in gate["primary_dirty_error"]

    rc, text = _run_text(["gate", "--worktree", wt, "--state", state])
    assert rc == MODULE.EXIT_OK
    assert "primary working tree status unavailable" in text
    assert "rc=7" in text


@gitmark
def test_gate_plan_only_does_not_probe_primary(scratch, monkeypatch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "primary-plan-only.json")
    rc, opened = _run_json(
        ["open", "--intent", "preview primary drift", "--slug", "primary-plan-only",
         "--state", state, "--json"]
    )
    assert rc == MODULE.EXIT_OK

    def unexpected_primary_probe():
        raise AssertionError("plan-only must not probe primary")

    monkeypatch.setattr(MODULE, "primary_root", unexpected_primary_probe)
    rc, gate = _run_json(["gate", "--worktree", opened["path"], "--state", state,
                          "--plan-only", "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["verdict"] == "planned"
    assert "primary_dirty" not in gate


@gitmark
def test_gate_orchestrator_identity_is_null_when_worktree_has_no_copy(scratch):
    """The synthetic fixture repo has no ops/ tree. Provenance must degrade to "cannot
    compare" rather than inventing a mismatch — otherwise every existing test, and every
    non-kg repo, would be refused."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    orch = gate["orchestrator"]
    assert orch["worktree_copy_sha256"] is None
    assert orch["matches_worktree_copy"] is None
    assert orch["source"] == "invoked"


@gitmark
def test_gate_provenance_is_pinned_to_the_same_computation_on_every_surface(scratch):
    """SOURCE PIN. A shared helper is not enough: someone can hand-write one output
    surface and the shared-source assertions all stay green (learned the hard way —
    reverting a call site while leaving a printer intact kept five assertions green).
    So assert the JSON block IS the helper's output, AND that the human report and the
    receipt line carry that same digest."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    expected = MODULE._orchestrator_identity(wt)
    assert gate["orchestrator"] == expected

    # The digest ALONE is not enough to pin: it reads the same whether the worktree
    # agreed, had nothing to compare, or could not be read. Pin the rendered token.
    token = f"{expected['sha256'][:8]} ({expected['source']})"
    rc, text = _run_text(["gate", "--worktree", wt, "--state", state])
    assert rc == MODULE.EXIT_OK
    assert f"orchestrator={token}" in text.splitlines()[0]

    rc, line = _run_text(["gate", "--worktree", wt, "--state", state, "--receipt-line"])
    assert rc == MODULE.EXIT_OK
    assert f"orch={token}" in line


@gitmark
def test_gate_report_last_line_is_the_pasteable_receipt_line(scratch):
    """One gate run supplies both the full report and its pasteable receipt."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    rc, text = _run_text(["gate", "--worktree", wt, "--state", state])
    assert rc == MODULE.EXIT_OK
    last = text.strip().splitlines()[-1]
    assert last.startswith("gate="), last

    rc, only = _run_text(["gate", "--worktree", wt, "--state", state, "--receipt-line"])
    assert rc == MODULE.EXIT_OK
    assert only.strip() == last
    assert len(only.strip().splitlines()) == 1

    rc, planned = _run_text(["gate", "--worktree", wt, "--state", state, "--plan-only"])
    assert rc == MODULE.EXIT_OK
    assert not planned.strip().splitlines()[-1].startswith("gate=")


def _plant_orchestrator(wt, body: str | None = None):
    """Give the scratch worktree its own copy of the orchestrator. `body=None` plants a
    byte-identical copy (the common case: the branch did not touch the tool)."""
    dst = Path(wt) / "ops" / "worktree_orchestrate.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if body is None:
        shutil.copyfile(Path(MODULE.__file__).resolve(), dst)
    else:
        dst.write_text(body)
    return dst


def _seed_python_scan(repo):
    """Seed the scanner in a scratch base so a Python diff can exercise its gate."""
    src = Path(MODULE.__file__).resolve().with_name("python_scan.py")
    dst = Path(repo) / "ops" / "python_scan.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    dst.chmod(dst.stat().st_mode | 0o111)
    for index in range(50):
        (dst.parent / f"scan_fixture_{index:02d}.py").write_text(
            f"value_{index} = {index}\n", encoding="utf-8"
        )
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "seed python scanner"], repo)
    _git(["push", "-q", "origin", "main"], repo)
    _git(["fetch", "-q", "origin", "main"], repo)


@gitmark
def test_gate_refuses_when_the_worktree_carries_a_different_orchestrator(scratch):
    """The incident this exists for: `gate` run from the primary checkout against a
    branch that changed the routing planned the OLD rule set and reported a green that
    read exactly like the new one's."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    _plant_orchestrator(wt, "# a different orchestrator\n")

    rc, text = _run_text(["gate", "--worktree", wt, "--state", state])
    assert rc == MODULE.EXIT_USAGE
    running = MODULE._orchestrator_identity(wt)
    # both digests named, so the reader can tell WHICH two things disagree
    assert running["sha256"][:8] in text
    assert running["worktree_copy_sha256"][:8] in text
    # and a remedy that can be pasted, not deduced
    assert f"{wt}/ops/worktree_orchestrate.py" in text
    # refusing must be free of side effects: no verdict may be recorded
    assert not MODULE._gate_record_path(state, wt).exists()


@gitmark
def test_gate_does_not_refuse_a_byte_identical_worktree_orchestrator(scratch):
    """The gate must be NARROW: it fires only when the branch actually modified the
    tool. Refusing on a byte-identical copy would be pure friction — the plan is the
    same plan — and friction is what teaches people to route around a gate."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    _plant_orchestrator(wt)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["orchestrator"]["matches_worktree_copy"] is True
    assert gate["orchestrator"]["source"] == "worktree"


@gitmark
def test_gate_names_unavailable_ops_tests_in_a_synthetic_worktree(scratch, monkeypatch):
    """A scratch tree with only an orchestrator copy cannot run the ops suite.

    The gate still needs to see the untracked orchestrator for omission/provenance
    checks, but invoking ``pytest ops/tests`` there exits rc=4 because that tree has
    no test directory.  This is unavailable infrastructure, not a failed change.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _seed_python_scan(repo)
    wt = _open_wt(state)
    _plant_orchestrator(wt)
    monkeypatch.setattr(
        MODULE, "_changed_vs_base",
        lambda _worktree, _base: ["ops/worktree_orchestrate.py"],
    )

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK, gate
    assert gate["verdict"] == "warn"
    assert not any(row["name"] == "ops-pytest" for row in gate["gates"])
    unavailable = next(row for row in gate["gates"]
                       if row["name"] == "ops-pytest-unavailable")
    assert unavailable["status"] == "warn"
    assert "ops/tests" in unavailable["summary"]


@gitmark
def test_gate_keeps_ops_pytest_block_when_an_ops_test_path_changed(scratch, monkeypatch):
    """A missing test tree is not advisory when the diff itself names an ops test."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    _plant_orchestrator(wt)
    monkeypatch.setattr(
        MODULE, "_changed_vs_base",
        lambda _worktree, _base: [
            "ops/worktree_orchestrate.py", "ops/tests/test_missing.py",
        ],
    )

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK, gate
    assert gate["verdict"] == "block"
    ops_gate = next(row for row in gate["gates"] if row["name"] == "ops-pytest")
    assert ops_gate["status"] == "block"
    assert "ops/tests" in next(
        plan["cmd"] for plan in gate["plan"] if plan["name"] == "ops-pytest"
    )
    assert not any(row["name"] == "ops-pytest-unavailable" for row in gate["gates"])


@gitmark
def test_cutover_refuses_a_verdict_produced_by_a_different_orchestrator(scratch):
    """Defence in depth for a record that predates the gate-side refusal, or one that
    was edited. Same family as the stale-HEAD refusal: a verdict is only usable if it
    is bound BOTH to the code it judged and to the judge."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    _plant_orchestrator(wt)

    rc, _ = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK

    rec_path = MODULE._gate_record_path(state, wt)
    rec = json.loads(rec_path.read_text())
    rec["orchestrator"]["sha256"] = "0" * 64
    rec_path.write_text(json.dumps(rec))

    rc, res = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert res["landed"] is False
    assert "orchestrator" in res["error"]
    assert "notes.txt" not in _local_main_files(repo)


@gitmark
def test_cutover_accepts_a_verdict_when_the_orchestrator_cannot_be_compared(scratch):
    """No ops/ tree in the target (synthetic fixtures, any non-kg checkout) means
    "cannot compare", which must not be reported as a mismatch — otherwise every such
    caller is refused for a question that was never asked."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["orchestrator"]["worktree_copy_sha256"] is None

    rc, res = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["landed"] is True


# ---------------------------------------------------------------------------
# gate history (IMP-0044)
#
# The per-worktree verdict file is a SINGLE file, overwritten on every gate run and
# deleted by `resolve` ("zero residue"). So there is no record of how a gate has
# BEHAVED over time — and "this gate has never once gone green" is the only signal that
# separates a broken check from a broken change. `ios-build-catalyst` blocked every iOS
# cutover for two months while passing "can it go red".
# ---------------------------------------------------------------------------
def _history_lines(state):
    p = MODULE._gate_history_path(state)
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


def test_gate_history_records_duration_and_stable_run_order(tmp_path, monkeypatch):
    moments = iter([
        datetime(2026, 8, 9, 1, 2, 3, 1, tzinfo=timezone.utc),
        datetime(2026, 8, 9, 1, 2, 3, 2, tzinfo=timezone.utc),
        datetime(2026, 8, 9, 1, 2, 3, 3, tzinfo=timezone.utc),
    ])

    class SequencedDatetime:
        @classmethod
        def now(cls, tz):
            assert tz is timezone.utc
            return next(moments)

    monkeypatch.setattr(MODULE, "datetime", SequencedDatetime)
    state = str(tmp_path / "reg.json")
    orch = {"sha256": "a" * 64}
    results = [
        {"name": "first", "status": "pass", "rc": 0, "level": "block", "dur_s": 1.25},
        {"name": "second", "status": "warn", "rc": 0, "level": "warn", "dur_s": 2.5},
    ]

    assert MODULE._append_gate_history(state, str(tmp_path), "b" * 40, orch, results) is None
    assert MODULE._append_gate_history(state, str(tmp_path), "c" * 40, orch, results[:1]) is None
    rows = _history_lines(state)

    assert [row["dur_s"] for row in rows] == [1.25, 2.5, 1.25]
    assert [row["idx"] for row in rows] == [0, 1, 0]
    assert rows[0]["run_id"] == rows[1]["run_id"]
    assert rows[2]["run_id"] != rows[0]["run_id"]
    assert len({(row["run_id"], row["idx"]) for row in rows}) == len(rows)
    assert [row["ts"] for row in rows] == [
        "2026-08-09T01:02:03.000001Z",
        "2026-08-09T01:02:03.000002Z",
        "2026-08-09T01:02:03.000003Z",
    ]


@gitmark
def test_gate_appends_one_history_line_per_executed_gate(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    rows = _history_lines(state)
    assert [r["gate"] for r in rows] == [g["name"] for g in gate["gates"]]
    assert [r["dur_s"] for r in rows] == [g["dur_s"] for g in gate["gates"]]
    assert all(isinstance(g["dur_s"], float) and g["dur_s"] >= 0 for g in gate["gates"])
    assert [r["idx"] for r in rows] == list(range(len(rows)))
    assert len({r["run_id"] for r in rows}) == 1
    row = rows[0]
    assert row["status"] == "warn" and row["level"] == "warn"
    assert row["head8"] == gate["head_sha"][:8]
    assert row["orch8"] == gate["orchestrator"]["sha256"][:8]
    assert row["ts"].endswith("Z")


@gitmark
def test_gate_history_accumulates_and_survives_resolve(scratch):
    """Teardown strikes the per-worktree verdict (that one describes a worktree that no
    longer exists). The behavioural history must NOT go with it — deleting it would
    erase exactly the evidence that proves a gate is capable of passing."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert len(_history_lines(state)) == 2

    _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    rc, res = _run_json(["resolve", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert res["gate_cache_removed"] is True
    assert len(_history_lines(state)) == 2


@gitmark
def test_gate_survives_an_unwritable_history(scratch):
    """Bookkeeping must never fail the caller — a gate that refuses because its own
    logging broke would be a new way for a green change to read as red."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)

    # occupy the history path with a DIRECTORY: every append will raise
    hist = MODULE._gate_history_path(state)
    hist.parent.mkdir(parents=True, exist_ok=True)
    hist.mkdir()

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["verdict"] == "warn"


def _write_history(state, rows):
    p = MODULE._gate_history_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _row(base_name, status, head8, level="block", wt="0" * 16, gate=None):
    return {"ts": "2026-08-03T00:00:00Z", "gate": gate or base_name,
            "base_name": base_name, "status": status, "rc": 1, "level": level,
            "head8": head8, "orch8": "abcdef01", "wt": wt}


def test_never_green_fires_only_when_a_gate_has_never_passed(tmp_path):
    state = str(tmp_path / "reg.json")
    _write_history(state, [_row("ios-build-catalyst", "block", h)
                           for h in ("aaaaaaaa", "bbbbbbbb", "cccccccc")])
    assert MODULE._never_green(state, "ios-build-catalyst") == {
        "attempts": 3, "heads": 3, "worktrees": 1}


def test_never_green_is_silenced_by_a_single_historical_pass(tmp_path):
    """One green ever is enough: the gate is PROVEN capable, and later reds are the
    change's problem, not the gate's."""
    state = str(tmp_path / "reg.json")
    _write_history(state, [
        _row("ios-build", "block", "aaaaaaaa"),
        _row("ios-build", "pass", "bbbbbbbb"),
        _row("ios-build", "block", "cccccccc"),
        _row("ios-build", "block", "dddddddd"),
    ])
    assert MODULE._never_green(state, "ios-build") is None


def test_never_green_ignores_a_single_head_streak(tmp_path):
    """Someone hammering one broken commit is not evidence about the GATE."""
    state = str(tmp_path / "reg.json")
    _write_history(state, [_row("ios-test-unit", "block", "aaaaaaaa")] * 5)
    assert MODULE._never_green(state, "ios-test-unit") is None


def test_never_green_needs_enough_attempts(tmp_path):
    state = str(tmp_path / "reg.json")
    _write_history(state, [_row("docs-lint", "block", "aaaaaaaa"),
                           _row("docs-lint", "block", "bbbbbbbb")])
    assert MODULE._never_green(state, "docs-lint") is None


def test_never_green_on_absent_history_is_silent(tmp_path):
    """A fresh clone knows nothing; "no data" must never be reported as "never green"."""
    assert MODULE._never_green(str(tmp_path / "reg.json"), "ios-build") is None


@gitmark
def test_a_gate_that_has_never_passed_says_so_at_the_moment_it_blocks(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "add a thing", "--slug", "nevergreen",
                            "--state", state, "--json"])
    wt = opened["path"]
    # The fixture repo has no ops/ tree; docs-lint therefore routes to a tool that does
    # not exist. Before IMP-0047 that raised and killed the whole run, so this test had
    # to plant a stub to reach the never-green annotation at all. It now reports as a
    # block, which is what a synthetic repo should look like — no stub needed.
    docs = Path(wt) / "docs"
    # exist_ok: the scratch fixture now commits docs/runbook/backlog (the claim gate
    # needs a real store), so `docs/` is checked out into every worktree.
    docs.mkdir(exist_ok=True)
    (docs / "x.md").write_text("<!-- doc-meta -->\n<<<<<<< HEAD\nours\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "docs: conflicted"], wt)

    rc, first = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    marker = _by_name(first["gates"])["docs-conflict-markers"]
    assert "never green" not in marker["summary"]  # one attempt proves nothing

    (docs / "y.md").write_text("<!-- doc-meta -->\n>>>>>>> theirs\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "docs: more conflict"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, third = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])

    assert rc == MODULE.EXIT_BLOCK
    marker = _by_name(third["gates"])["docs-conflict-markers"]
    assert marker["never_green"] == {"attempts": 3, "heads": 2, "worktrees": 1}
    assert "3 block attempt(s) across 2 HEAD(s) / 1 worktree(s)" in marker["summary"]
    # A hypothesis, never a verdict — the data cannot distinguish a structurally-red
    # gate from three honest reds while fixing a real bug.
    assert "worth checking whether it can pass at all" in marker["summary"]
    assert "suspect the gate" not in marker["summary"]


@gitmark
def test_an_unreadable_worktree_orchestrator_is_a_mismatch_not_an_absence(scratch):
    """"Present but unreadable" must never render identically to "no ops/ tree at all".
    If it did, the guard (`matches_worktree_copy is not False`) would wave it through —
    reinstating the exact silent bypass this whole change exists to close, with a
    different trigger."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    planted = _plant_orchestrator(wt)
    planted.chmod(0o000)
    try:
        orch = MODULE._orchestrator_identity(wt)
        assert orch["matches_worktree_copy"] is False        # fail CLOSED
        assert orch["worktree_copy_sha256"] is None
        assert orch["source"] == "unreadable"
        assert "PermissionError" in orch["worktree_copy_error"]

        rc, text = _run_text(["gate", "--worktree", wt, "--state", state])
        assert rc == MODULE.EXIT_USAGE
        assert "could not be read" in text
    finally:
        planted.chmod(0o644)


@gitmark
def test_absent_and_unreadable_orchestrators_do_not_render_identically(scratch):
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    absent = MODULE._orchestrator_identity(wt)

    planted = _plant_orchestrator(wt)
    planted.chmod(0o000)
    try:
        unreadable = MODULE._orchestrator_identity(wt)
    finally:
        planted.chmod(0o644)
    assert absent != unreadable
    assert absent["matches_worktree_copy"] is None
    assert unreadable["matches_worktree_copy"] is False


def test_never_green_survives_one_corrupt_journal_line(tmp_path):
    """The journal is append-only and never rotated, so a single truncated write (disk
    full, SIGKILL mid-flush) must not disable the detector FOREVER, silently. That
    failure shape is the one this whole mechanism exists to find."""
    state = str(tmp_path / "reg.json")
    _write_history(state, [_row("ios-build-catalyst", "block", h)
                           for h in ("aaaaaaaa", "bbbbbbbb", "cccccccc")])
    p = MODULE._gate_history_path(state)
    p.write_text('{"base_name": "ios-build-cat\n' + p.read_text() + '{"truncated')
    assert MODULE._never_green(state, "ios-build-catalyst") == {
        "attempts": 3, "heads": 3, "worktrees": 1}


def test_never_green_counts_only_block_level_rows(tmp_path):
    """A gate promoted from advisory to block would otherwise inherit the entire streak
    it built up while nobody was obliged to act on it, and trip on its first real block."""
    state = str(tmp_path / "reg.json")
    _write_history(state, [
        _row("ui-quality-fast", "warn", "aaaaaaaa", level="warn"),
        _row("ui-quality-fast", "warn", "bbbbbbbb", level="warn"),
        _row("ui-quality-fast", "block", "cccccccc"),
    ])
    assert MODULE._never_green(state, "ui-quality-fast") is None


def test_never_green_reports_how_many_worktrees_the_streak_spans(tmp_path):
    """The journal is repo-wide, so three reds can be three unrelated worktrees. Say so,
    rather than letting it read as one persistent failure."""
    state = str(tmp_path / "reg.json")
    _write_history(state, [_row("ios-build", "block", h, wt=w) for h, w in
                           (("aaaaaaaa", "w1"), ("bbbbbbbb", "w2"), ("cccccccc", "w3"))])
    assert MODULE._never_green(state, "ios-build") == {
        "attempts": 3, "heads": 3, "worktrees": 3}


def test_never_green_folds_colon_suffixed_instances_into_one_capability(tmp_path):
    """`ios-test-ui:<Class>` names are per-diff instances of ONE check. Without folding,
    attempts never reach the threshold and the whole iOS UI family silently opts out —
    and a green from any instance must silence the rest."""
    state = str(tmp_path / "reg.json")
    _write_history(state, [
        _row("ios-test-ui", "block", "aaaaaaaa", gate="ios-test-ui:FooTests"),
        _row("ios-test-ui", "block", "bbbbbbbb", gate="ios-test-ui:BarTests"),
        _row("ios-test-ui", "block", "cccccccc", gate="ios-test-ui:BazTests"),
    ])
    assert MODULE._never_green(state, "ios-test-ui") == {
        "attempts": 3, "heads": 3, "worktrees": 1}

    _write_history(state, [
        _row("ios-test-ui", "block", "aaaaaaaa", gate="ios-test-ui:FooTests"),
        _row("ios-test-ui", "pass", "bbbbbbbb", gate="ios-test-ui:BarTests"),
        _row("ios-test-ui", "block", "cccccccc", gate="ios-test-ui:FooTests"),
    ])
    assert MODULE._never_green(state, "ios-test-ui") is None


@gitmark
def test_history_rows_carry_the_folded_base_name(scratch):
    """Pins the fold at the WRITE site too: recording the full instance name would make
    every row its own capability and the threshold unreachable."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    MODULE._append_gate_history(state, wt, "f" * 40, {"sha256": "a" * 64}, [
        {"name": "ios-test-ui:FooTests", "status": "block", "rc": 1, "level": "block"}])
    row = _history_lines(state)[-1]
    assert row["gate"] == "ios-test-ui:FooTests"
    assert row["base_name"] == "ios-test-ui"


@gitmark
def test_a_broken_journal_is_reported_not_swallowed(scratch):
    """A permanently unwritable journal and a fresh clone both look like "no history".
    If they render identically, the detector can die with zero signal."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    wt = _open_wt(state)
    hist = MODULE._gate_history_path(state)
    hist.parent.mkdir(parents=True, exist_ok=True)
    hist.mkdir()

    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert gate["history_error"] and "IsADirectory" in gate["history_error"]
    rc, text = _run_text(["gate", "--worktree", wt, "--state", state])
    assert "gate history not written" in text


# ---------------------------------------------------------------------------
# a routed-to tool that isn't there (IMP-0047)
# ---------------------------------------------------------------------------
def _diagnosis(summary: str) -> str:
    """The clause after the em dash — the ONLY part of a spawn-failure summary derived
    from the exception. Everything before it is echoed from the spec, so asserting
    `"<path>" in summary` proves nothing about what the OS actually reported: a mutant
    that reports the command where the missing directory belongs still contains the
    directory, in the `cwd=` segment."""
    head, sep, tail = summary.partition("—")
    assert sep, f"summary has no diagnosis clause: {summary}"
    return tail.strip()


# --- a blocked branch must say WHICH assertion failed (IMP-20260808-c47253) ---
#
# Measured 2026-08-08: `ops-shell:test_devops.sh` blocked `feat/devops-rsync-flavor`
# and the summary kept for it was 94 characters long, in full —
#     exit 1: ══════════════════════════════
#       passed: 104  failed: 1
#     ══════════════════════════════
# — while that test prints `✗ <name>` for every failure it finds. The name was
# dozens of lines above the tail and nothing kept it; `history.jsonl` stores
# metadata only. The one move left was to re-run and hope for a repro, which cost
# ten minutes and still did not identify the assertion. A gate that fails closed
# but cannot say why keeps its safety and spends the operator's time instead.

def _gate_from_script(tmp_path, body, name="noisy-gate"):
    tool = tmp_path / "ops" / "noisy.sh"
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text("#!/bin/sh\n" + textwrap.dedent(body))
    tool.chmod(0o755)
    return MODULE._shell(name, "ops", ["ops/noisy.sh"], "block")


def _log_pointer(summary):
    """The path the summary tells an operator to open, read back the way one would."""
    for line in summary.splitlines():
        if line.strip().startswith("full output:"):
            return Path(line.split("full output:", 1)[1].strip())
    raise AssertionError(f"summary names no output log:\n{summary}")


def test_a_failing_gate_names_its_failing_lines_and_keeps_the_whole_output(tmp_path):
    spec = _gate_from_script(tmp_path, """\
        echo "OPENING-LINE-UNIQUE"
        i=0; while [ $i -lt 60 ]; do echo "  ✓ passing check $i"; i=$((i+1)); done
        echo "  ✗ named assertion"
        echo "══════════════════════════════"
        echo "  passed: 60  failed: 1"
        echo "══════════════════════════════"
        exit 1
    """)
    result = MODULE._run_gate(spec, str(tmp_path),
                              record_path=tmp_path / "gates" / "deadbeef.json")

    assert result["status"] == "block" and result["rc"] == 1
    # (1) the failing assertion's NAME reaches the operator, which is the whole ticket
    assert "named assertion" in result["summary"], result["summary"]
    # (2) the framing tail is still there — the new lines are added, not swapped in
    assert "passed: 60  failed: 1" in result["summary"]

    # (3) the rest survives on disk. Proven with a line that is neither failure-marked
    # nor inside the tail, so only a real capture of the child's output can contain
    # it: a log built by echoing the summary back would not.
    log = _log_pointer(result["summary"])
    assert log.is_file(), f"{log} does not exist"
    body = log.read_text(encoding="utf-8")
    assert "OPENING-LINE-UNIQUE" in body
    assert body.count("passing check") == 60
    assert "OPENING-LINE-UNIQUE" not in result["summary"], \
        "the summary stays a summary — the log is what holds everything"


def test_a_failing_gate_with_no_failure_markers_says_so_rather_than_going_quiet(
        tmp_path):
    """The negative control, and the reason it is not optional.

    Without it, "summary contains the failing line" is also satisfied by an
    implementation that simply kept printing the tail — because for many gates the
    tail IS where the failure marker sits. This one has no marker anywhere, so the
    only way to be right about it is to have actually looked and found nothing.
    """
    spec = _gate_from_script(tmp_path, """\
        echo "nothing here resembles a failure"
        echo "the last line, which is the tail"
        exit 3
    """)
    result = MODULE._run_gate(spec, str(tmp_path),
                              record_path=tmp_path / "gates" / "deadbeef.json")

    assert result["rc"] == 3
    assert "no failure-marked lines found" in result["summary"], result["summary"]
    assert "the last line, which is the tail" in result["summary"]
    assert _log_pointer(result["summary"]).is_file()

    # The tail is still shown — but it must NOT be presented under the same heading a
    # real extraction uses. When the scanner matched nothing, the lines below it are
    # "the last lines of the log", not "the failure". Measured cost of conflating the
    # two (IMP-20260808-8b4690): `review-receipts` went red, matched zero markers, and
    # its tail was `[review][ok]` / `Reviewed-by:` — so a BLOCKED gate displayed
    # passing lines in the slot an operator reads as evidence, and the operator
    # (correctly reading a green-looking summary) concluded the red was spurious.
    assert "NOT failure lines" in result["summary"], \
        "a zero-match tail must be labelled as not-evidence: " + result["summary"]
    assert "\n  tail:\n" not in result["summary"], \
        "the zero-match tail must not reuse the plain heading a real extraction uses"


def test_a_matched_failure_still_labels_its_tail_plainly(tmp_path):
    """The other half of the pair, and the reason the label is conditional.

    If the warning heading were unconditional it would be noise on every ordinary
    red — and a warning that fires on the happy path is one people stop reading,
    which is the failure mode this whole ticket is about, one level up.
    """
    spec = _gate_from_script(tmp_path, """\
        echo "  ✗ a marker the scanner knows"
        echo "the last line, which is the tail"
        exit 1
    """)
    result = MODULE._run_gate(spec, str(tmp_path),
                              record_path=tmp_path / "gates" / "deadbeef.json")

    assert "failure-marked lines" in result["summary"]
    assert "\n  tail:\n" in result["summary"], result["summary"]
    assert "NOT failure lines" not in result["summary"]


@pytest.mark.parametrize("marker,line", [
    ("cross", "  ✗ shell scan found a violation"),
    # U+2718, NOT the U+2717 above. Swift Testing prints this one, so every iOS test
    # failure was invisible to the extractor while the list looked complete — measured
    # on `.cache/worktree_gates/*.ios-test-unit.log`: 4 lines carry U+2718, 1 carries
    # U+2717 (IMP-20260808-8b4690). Two codepoints that render nearly identically is
    # exactly the shape a by-eye review of the tuple cannot catch.
    ("heavy-cross", "  ✘ Test testGuestGate() recorded an issue"),
    # `ops/review_audit.sh`'s verdict prefix. `review-receipts` is a BLOCK-level gate
    # whose red output contained none of the other markers at all, so its summary
    # fell through to the tail — and its tail is `[review][ok]` lines.
    ("review-block", "[review][block] deadbeef01 ops: a commit with no receipt"),
    ("FAIL", "FAIL tests/test_thing.py::test_case"),
    ("AssertionError", "E   AssertionError: expected 3, got 4"),
    ("not ok", "not ok 7 - the tap-style failure"),
    ("error:", "ops/x.sh:12: error: unbound variable"),
])
def test_every_declared_failure_marker_is_actually_extracted(tmp_path, marker, line):
    """One case per marker the docstring promises.

    A single-marker test would let all but one be dropped silently, and the ones
    most likely to rot are the ones this repo uses least often day to day.

    The marker is printed FAR above the tail, and the first draft of this test did
    not do that — it sat two lines from the end, so every case passed against the
    old tail-only summary. The assertion was reading a string the OLD code had put
    there. Twenty filler lines is what makes the extractor the only possible source.
    """
    spec = _gate_from_script(tmp_path, f"""\
        echo "filler line one"
        echo "{line}"
        i=0; while [ $i -lt 20 ]; do echo "  ✓ unrelated passing line $i"; i=$((i+1)); done
        echo "filler tail line"
        exit 1
    """)
    result = MODULE._run_gate(spec, str(tmp_path),
                              record_path=tmp_path / "gates" / "deadbeef.json")
    assert line.strip() in result["summary"], f"{marker!r} not extracted: {result['summary']}"
    assert "no failure-marked lines found" not in result["summary"]


def test_the_failure_line_list_is_capped_and_says_how_many_it_shows(tmp_path):
    """The cap is what keeps the summary a summary.

    It travels into the gate record JSON and into `land`'s stdout payload, so an
    uncapped list lets one chatty gate bloat both. Untested, the slice could be
    deleted or widened and nothing would notice — the log is where the rest belongs,
    and it is one line away in the pointer.
    """
    # The three closing lines carry NO marker on purpose: the tail is reproduced in
    # the summary too, so a marker-bearing tail would make the count 23 and the test
    # would be measuring the fixture instead of the cap. (Measured — the first draft
    # did exactly that.)
    spec = _gate_from_script(tmp_path, """\
        i=0; while [ $i -lt 30 ]; do echo "  ✗ failure number $i"; i=$((i+1)); done
        echo "──────────────"
        echo "  passed: 0  failed: 30"
        echo "──────────────"
        exit 1
    """)
    summary = MODULE._run_gate(spec, str(tmp_path),
                               record_path=tmp_path / "gates" / "deadbeef.json")["summary"]
    assert summary.count("✗ failure number") == MODULE.GATE_MAX_FAILURE_LINES == 20
    assert f"({MODULE.GATE_MAX_FAILURE_LINES} shown)" in summary
    # the ones it dropped are still in the log it points at
    assert _log_pointer(summary).read_text(encoding="utf-8").count(
        "✗ failure number") == 30


def test_a_gate_going_green_clears_the_log_its_last_red_left(tmp_path):
    """A stale log outlives the failure it describes and nothing marks it stale.

    The verdict cache is overwritten on every run; its log has to obey the same rule
    or an operator opens a file describing a failure that was fixed hours ago — a
    fresh way to lose the ten minutes this ticket is about.
    """
    rec = tmp_path / "gates" / "deadbeef.json"
    red = MODULE._run_gate(_gate_from_script(tmp_path, 'echo "  ✗ boom"\nexit 1\n'),
                           str(tmp_path), record_path=rec)
    log = _log_pointer(red["summary"])
    assert log.is_file()

    green = MODULE._run_gate(_gate_from_script(tmp_path, "echo fine\nexit 0\n"),
                             str(tmp_path), record_path=rec)
    assert green["status"] == "pass"
    assert "full output" not in green["summary"], "a green gate points at no log"
    assert not log.exists(), "a green run must not leave the previous red's log behind"


def test_a_gate_run_without_a_record_path_still_reports_normally(tmp_path):
    """`_run_gate` is called directly by tests and could be by future callers; the
    log is an enhancement, not a precondition. No path, no log, no crash."""
    result = MODULE._run_gate(
        _gate_from_script(tmp_path, """\
            echo "  ✗ named thing"
            i=0; while [ $i -lt 20 ]; do echo "  ✓ filler $i"; i=$((i+1)); done
            exit 1
        """),
        str(tmp_path))
    assert result["status"] == "block" and result["rc"] == 1
    # far above the tail, so this still testifies about the extractor
    assert "named thing" in result["summary"]
    assert "full output" not in result["summary"]


def test_a_missing_gate_tool_is_a_readable_block_not_a_traceback(tmp_path):
    """The router and the tools it routes to can be different generations (IMP-0045):
    a branch that deletes a script leaves a stale router still pointing at it. Letting
    FileNotFoundError escape costs more than readability — it aborts the whole run, so
    every OTHER gate's result is lost too, and the operator is told nothing about which
    gate died."""
    spec = MODULE._shell("ghost", "ops", ["ops/definitely_not_here.sh"], "block")
    result = MODULE._run_gate(spec, str(tmp_path))
    assert result["status"] == "block"
    assert result["rc"] == 127
    assert result["executed"] is False
    # startswith, not `in`: the exception's own repr already contains the path, so
    # `"ops/... " in summary` is satisfied with the entire message deleted. Verified
    # by mutation — that assertion passed the whole suite against a stripped summary.
    assert result["summary"].startswith(
        "gate tool not runnable: cmd=ops/definitely_not_here.sh"), result["summary"]
    assert _diagnosis(result["summary"]) == \
        "FileNotFoundError on ops/definitely_not_here.sh"


def test_a_missing_gate_CWD_is_not_reported_as_a_missing_tool(tmp_path):
    """With spec["cwd"] set, the OS names the missing DIRECTORY, not the command — so
    a message built from the exception alone accuses a tool that is perfectly fine."""
    tool = tmp_path / "ops" / "docs_lint.sh"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(0o755)
    spec = MODULE._shell("ghost", "ops", ["ops/docs_lint.sh"], "block", cwd="backend")
    summary = MODULE._run_gate(spec, str(tmp_path))["summary"]
    assert not (tmp_path / "backend").exists(), (
        "a missing gate cwd must not be created by task-registry bookkeeping"
    )
    assert summary.startswith("gate tool not runnable: cmd=ops/docs_lint.sh")
    # `"backend" in summary` would pass against a mutant that reports the COMMAND here,
    # because the code echoes `cwd=` from the spec and "backend" appears twice. Only the
    # diagnosis clause comes from the exception, so only it can testify.
    assert _diagnosis(summary) == f"FileNotFoundError on {tmp_path}/backend"
    assert "docs_lint" not in _diagnosis(summary)


def test_an_unexecutable_gate_tool_is_reported_the_same_way(tmp_path):
    """Pins the breadth downward: narrowing the handler to FileNotFoundError silently
    reopens the hole for a script whose permission bit was lost."""
    tool = tmp_path / "ops" / "noexec.sh"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(0o644)
    result = MODULE._run_gate(
        MODULE._shell("ghost", "ops", ["ops/noexec.sh"], "block"), str(tmp_path))
    assert result["status"] == "block" and result["executed"] is False
    assert result["summary"].startswith("gate tool not runnable: cmd=ops/noexec.sh")
    # the OS names the command as GIVEN (relative), where the cwd case names an absolute
    # directory — which is exactly the distinction the diagnosis clause has to carry
    assert _diagnosis(result["summary"]) == "PermissionError on ops/noexec.sh"


def test_a_machine_that_cannot_fork_is_not_blamed_on_the_tool(tmp_path, monkeypatch):
    """EMFILE/ENOMEM are OSErrors that say nothing about the tool. Asserting the strong
    cause on weak evidence sends the operator hunting a stale router while a sibling
    worktree leaks fds — this repo has already lived that failure once, as pty
    exhaustion presenting as "the simulator is broken"."""
    def boom(*a, **k):
        raise OSError(errno.EMFILE, "Too many open files")
    monkeypatch.setattr(MODULE, "_run_streamed_command", boom)
    summary = MODULE._run_gate(
        MODULE._shell("ghost", "ops", ["ops/ios_ops.sh"], "block"), str(tmp_path))["summary"]
    assert "not runnable" not in summary
    assert f"errno {errno.EMFILE}" in summary
    assert "ops/ios_ops.sh" in summary


def test_a_non_oserror_from_the_runner_still_propagates(tmp_path, monkeypatch):
    """Pins the breadth upward: widening to `except Exception` would turn a genuine bug
    in this module into a confident "gate tool not runnable" block."""
    def boom(*a, **k):
        raise ValueError("a bug in the runner, not a missing tool")
    monkeypatch.setattr(MODULE, "_run_streamed_command", boom)
    with pytest.raises(ValueError):
        MODULE._run_gate(MODULE._shell("ghost", "ops", ["x"], "block"), str(tmp_path))


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_the_tag_probe_reads_real_tags_and_reports_unreadable_as_unmeasured(tmp_path):
    """The positive control the whole mechanism rests on. Every test below monkeypatches
    `_tag_snapshot`, so a probe that silently returned None on every real repo would
    leave all of them green while the feature never fired once in production — a
    detector that cannot be observed failing is the disease this repo keeps catching.

    The other half is just as load-bearing: a path that is not a repo must come back
    UNMEASURED, not as an empty tag set. Empty-vs-populated would read as "every tag was
    just deleted" and turn honest reds into inconclusives."""
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True,  # noqa: E731
                                    capture_output=True)
    run("init", "-q")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
        "--allow-empty", "-m", "x")
    run("tag", "v1")
    before = MODULE._tag_snapshot(repo)
    assert before is not None and "refs/tags/v1" in before
    run("tag", "v2")
    one_added = MODULE._tag_snapshot(repo)
    assert MODULE._tag_delta(before, one_added) == 1
    assert MODULE._tag_delta(before, before) == 0

    # the count is a count, not the constant 1: two more tags must read as two
    run("tag", "v3")
    run("tag", "v4")
    assert MODULE._tag_delta(one_added, MODULE._tag_snapshot(repo)) == 2
    # and a MOVED tag is one removal plus one addition — the docstring's claim, pinned
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
        "--allow-empty", "-m", "y")
    four = MODULE._tag_snapshot(repo)
    run("tag", "-f", "v1")
    assert MODULE._tag_delta(four, MODULE._tag_snapshot(repo)) == 2

    # unmeasured never counts as a change — BOTH ways it can happen:
    # a path that does not exist at all, and a real directory that is not a repo.
    missing = MODULE._tag_snapshot(tmp_path / "does-not-exist")
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    outside = MODULE._tag_snapshot(not_a_repo)
    assert missing is None and outside is None
    assert MODULE._tag_delta(before, outside) == 0
    assert MODULE._tag_delta(outside, four) == 0


def test_a_failing_gate_during_a_tag_change_is_inconclusive_not_block(tmp_path, monkeypatch):
    """A linked worktree shares `refs/` with the primary, so `release.sh` creating a tag
    over there changes what a child gate reads over here. Measured 2026-08-05: a batch
    gate saw `ops/test_ios_ops.sh` report 371 passed / 1 failed, rc=1; the same input
    rerun alone was 371 green, exit 0. In the gate's eyes that red was indistinguishable
    from a real one — the colour was a function of machine state, not of the branch.

    So the orchestrator says which one it measured. `inconclusive` is neither pass nor
    block: block would kill work for someone else's tag surgery, pass would let a real
    red through."""
    snaps = iter(["a1 refs/tags/v1",
                  "a1 refs/tags/v1\nb2 refs/tags/v2\nc3 refs/tags/v3"])
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: next(snaps))
    monkeypatch.setattr(MODULE, "_run_streamed_command",
                        lambda *a, **k: (1, "  passed: 371  failed: 1", 1.0))
    spec = MODULE._shell("ops-shell:test_ios_ops.sh", "ops", ["ops/test_ios_ops.sh"], "block")
    r = MODULE._run_gate(spec, str(tmp_path))
    assert r["status"] == "inconclusive"
    assert r["rc"] == 1, "the real rc must survive — the point is attribution, not amnesia"
    assert r["refs_changed"] is True
    # the count comes from the two snapshots THIS test supplied, not from a constant:
    # two tags appear, so a hard-coded "1" in the summary fails here
    assert "2 tag(s)" in r["summary"]
    assert MODULE.aggregate_verdict([r]) == "warn"


def test_a_failing_gate_with_stable_tags_still_blocks(tmp_path, monkeypatch):
    """The reverse guard, and the reason the pair is the acceptance rather than the one
    above alone: `_run_gate` rewritten to return `inconclusive` unconditionally would
    satisfy the positive test and disarm every block gate in the repo."""
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "a1 refs/tags/v1")
    monkeypatch.setattr(MODULE, "_run_streamed_command",
                        lambda *a, **k: (1, "  ✗ boom", 1.0))
    spec = MODULE._shell("ops-shell:test_ios_ops.sh", "ops", ["ops/test_ios_ops.sh"], "block")
    r = MODULE._run_gate(spec, str(tmp_path))
    assert r["status"] == "block"
    assert r.get("refs_changed") is not True
    assert MODULE.aggregate_verdict([r]) == "block"


def test_contention_machine_state_detects_ios_processes_and_active_worktrees(
        tmp_path, monkeypatch):
    """The machine snapshot must be executable evidence, not an agent guess.

    Keep the process probe synthetic: starting a process whose argv merely contains
    ``xcodebuild`` would make this test slow and would not prove the parser's shape.
    The registry count is read from the same state file the orchestrator receives, so
    the result is scoped to the machine/workflow that produced the verdict.
    """
    state = tmp_path / "registry.json"
    state.write_text(json.dumps({"records": [
        {"status": "active", "path": "/tmp/a"},
        {"status": "merged", "path": "/tmp/b"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(MODULE.os, "getloadavg", lambda: (3.0, 2.0, 1.0))

    def fake_run(argv, **kwargs):
        assert argv == ["ps", "-axo", "pid=,command="]
        return subprocess.CompletedProcess(
            argv, 0,
            stdout="123 xcodebuild -scheme BooksAndVocab\n"
                   "456 /bin/bash ops/ios_test.sh --unit\n"
                   "789 python unrelated.py\n",
            stderr="",
        )

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    snapshot = MODULE._machine_state(str(state))

    assert snapshot["load_average"] == [3.0, 2.0, 1.0]
    assert snapshot["active_worktrees"] == 1
    assert snapshot["active_ios_process_count"] == 2
    assert snapshot["active_ios_processes"] == [
        {"pid": 123, "kind": "xcodebuild"},
        {"pid": 456, "kind": "ios_test.sh"},
    ]
    assert snapshot["probe_errors"] == []


def test_contention_sensitive_red_names_machine_and_rerun_command(tmp_path, monkeypatch):
    """A red under iOS contention stays red but explains how to reproduce it quietly."""
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "stable")
    monkeypatch.setattr(MODULE, "_run_streamed_command",
                        lambda *a, **k: (1, "  ✗ concurrency assertion", 1.0))
    busy = {
        "load_average": [8.0, 7.0, 6.0],
        "active_worktrees": 3,
        "active_ios_process_count": 1,
        "active_ios_processes": [{"pid": 123, "kind": "xcodebuild"}],
        "probe_errors": [],
    }
    monkeypatch.setattr(MODULE, "_machine_state", lambda _state=None: busy)

    spec = MODULE._shell("ios-test-unit", "ios",
                         ["ops/ios_ops.sh", "test", "--unit", "--lease"], "block")
    result = MODULE._run_gate(spec, str(tmp_path))

    assert result["status"] == "block", "contention must not downgrade a real red"
    assert result["machine_state"]["contention"] is True
    assert result["machine_state"]["contention_processes"] == busy["active_ios_processes"]
    assert "machine contention detected" in result["summary"]
    assert "may be non-reproducible" in result["summary"]
    assert "xcodebuild" in result["summary"]
    assert "Re-run when quiet" in result["summary"]
    assert "ops/ios_ops.sh test --unit --lease" in result["summary"]
    assert result["contention_warning"] is True

    state = tmp_path / "history-state.json"
    assert MODULE._append_gate_history(
        str(state), str(tmp_path), "a" * 40, {"sha256": "b" * 64}, [result]
    ) is None
    row = MODULE.gate_history_rows(str(state))[-1]
    assert row["machine_state"]["contention"] is True


def test_contention_warning_is_absent_when_machine_is_quiet(tmp_path, monkeypatch):
    """The warning must not become boilerplate that operators learn to ignore."""
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "stable")
    monkeypatch.setattr(MODULE, "_run_streamed_command",
                        lambda *a, **k: (1, "  ✗ real assertion", 1.0))
    quiet = {
        "load_average": [0.1, 0.2, 0.3],
        "active_worktrees": 1,
        "active_ios_process_count": 0,
        "active_ios_processes": [],
        "probe_errors": [],
    }
    monkeypatch.setattr(MODULE, "_machine_state", lambda _state=None: quiet)

    result = MODULE._run_gate(
        MODULE._shell("ops-shell:test_ios_test_discovery.sh", "ops",
                      ["ops/test_ios_test_discovery.sh"], "block"),
        str(tmp_path),
    )

    assert result["status"] == "block"
    assert result["machine_state"]["contention"] is False
    assert "machine contention detected" not in result["summary"]
    assert result.get("contention_warning") is not True


def test_a_red_whose_refs_probe_failed_says_so_instead_of_going_quiet(tmp_path, monkeypatch):
    """Fail-safe is the right direction — an unreadable probe must not downgrade a red —
    but silent fail-safe is not what this module does anywhere else. `history_error`,
    `log_error` and `executed: False` all exist for one reason: "could not measure" must
    not look identical to "measured, nothing happened". Without this, the probe going
    permanently blind on some machine reinstates the whole bug with zero signal.
    Found by review of IMP-20260805-4ec901."""
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: None)
    monkeypatch.setattr(MODULE, "_run_streamed_command",
                        lambda *a, **k: (1, "  ✗ boom", 1.0))
    spec = MODULE._shell("ops-shell:test_ios_ops.sh", "ops", ["ops/test_ios_ops.sh"], "block")
    r = MODULE._run_gate(spec, str(tmp_path))
    # the red still counts — fail-safe direction is unchanged
    assert r["status"] == "block"
    assert r.get("refs_changed") is not True
    # but the inability to attribute it is on the record, not swallowed
    assert r["refs_probe"] == "unmeasured"
    assert "unmeasured" in r["summary"]

    # control: when the probe DOES work and sees nothing, there is no such noise
    monkeypatch.setattr(MODULE, "_tag_snapshot", lambda _anchor: "a1 refs/tags/v1")
    clean = MODULE._run_gate(spec, str(tmp_path))
    assert clean["status"] == "block"
    assert "refs_probe" not in clean
    assert "unmeasured" not in clean["summary"]


def test_an_inconclusive_gate_is_not_evidence_that_it_can_never_pass(tmp_path):
    """Same family as the spawn-failure exclusion below, and the same reasoning: a red
    that was contaminated by someone else's tag surgery is not a data point about
    whether this gate can pass. It is journalled at `level: block` and `executed: True`,
    so without an explicit exclusion it would count toward the never-green streak and
    the NEXT genuine red would arrive carrying "no green ever recorded" — steering the
    reader away from their own bug, which is the exact harm `executed: False` exists to
    prevent."""
    state = str(tmp_path / "reg.json")
    orch = {"sha256": "a" * 64}
    poisoned = [{"name": "ops-shell:test_ios_ops.sh", "level": "block",
                 "status": "inconclusive", "rc": 1, "refs_changed": True}]
    for head in ("aaaaaaaa", "bbbbbbbb", "cccccccc"):
        assert MODULE._append_gate_history(state, str(tmp_path), head, orch,
                                           poisoned) is None
    assert MODULE._never_green(state, "ops-shell") is None

    # positive control: three ordinary reds on the same gate DO make the streak
    real = [{"name": "ops-shell:test_ios_ops.sh", "level": "block", "status": "block",
             "rc": 1}]
    for head in ("dddddddd", "eeeeeeee", "ffffffff"):
        MODULE._append_gate_history(state, str(tmp_path), head, orch, real)
    assert MODULE._never_green(state, "ops-shell") == {
        "attempts": 3, "heads": 3, "worktrees": 1}


def test_a_gate_that_never_started_is_not_evidence_about_whether_it_can_pass(tmp_path):
    """`_never_green` reads level and status, never rc — so spawn failures would count
    as block attempts and push a healthy gate over the 3-attempt threshold. The next
    genuine red would then arrive carrying "no green ever recorded", which is exactly
    the wrong hypothesis to hand someone."""
    state = str(tmp_path / "reg.json")
    unexecuted = [{"name": "docs-lint", "level": "block", "status": "block",
                   "rc": 127, "executed": False}]
    orch = {"sha256": "a" * 64}
    for head in ("aaaaaaaa", "bbbbbbbb", "cccccccc"):
        assert MODULE._append_gate_history(state, str(tmp_path), head, orch,
                                           unexecuted) is None
    assert MODULE._never_green(state, "docs-lint") is None

    ran = [{"name": "docs-lint", "level": "block", "status": "block", "rc": 1}]
    for head in ("dddddddd", "eeeeeeee", "ffffffff"):
        MODULE._append_gate_history(state, str(tmp_path), head, orch, ran)
    assert MODULE._never_green(state, "docs-lint") == {
        "attempts": 3, "heads": 3, "worktrees": 1}


def test_gate_history_ignores_unestablished_rows_for_attempts_and_greens(tmp_path):
    """A producer that checked nothing must not prove a gate or inflate its streak."""
    state = str(tmp_path / "reg.json")
    orch = {"sha256": "a" * 64}
    for head in ("aaaaaaaa", "bbbbbbbb", "cccccccc"):
        MODULE._append_gate_history(
            state, str(tmp_path), head, orch,
            [{"name": "ops-shell-syntax", "level": "block",
              "status": "block", "rc": 1, "established": False}],
        )
    MODULE._append_gate_history(
        state, str(tmp_path), "dddddddd", orch,
        [{"name": "ops-shell-syntax", "level": "block",
          "status": "pass", "rc": 0, "established": False}],
    )
    assert MODULE.gate_history_verdicts(state, ["ops-shell-syntax"])["ops-shell-syntax"] == {
        "verdict": "unproven", "attempts": 0, "heads": 0,
        "worktrees": 0, "last_green": None,
    }


def test_both_journal_consumers_read_it_through_the_same_function(tmp_path):
    """`gate_history_verdicts` is THE reader. The shell side used to parse the journal
    itself, and the two copies disagreed the moment `executed` was added: identical rows
    read as "never green" in one and "no data" in the other."""
    state = str(tmp_path / "reg.json")
    orch = {"sha256": "a" * 64}
    unexecuted = [{"name": "ios-build", "level": "block", "status": "block",
                   "rc": 127, "executed": False}]
    for head in ("11111111", "22222222", "33333333"):
        MODULE._append_gate_history(state, str(tmp_path), head, orch, unexecuted)
    v = MODULE.gate_history_verdicts(state, ["ios-build"])["ios-build"]
    assert v == {"verdict": "unproven", "attempts": 0, "heads": 0,
                 "worktrees": 0, "last_green": None}
    assert len(MODULE.gate_history_rows(state)) == 3   # the rows ARE there, just mute

    MODULE._append_gate_history(state, str(tmp_path), "44444444", orch,
                                [{"name": "ios-build", "level": "block",
                                  "status": "pass", "rc": 0}])
    v = MODULE.gate_history_verdicts(state, ["ios-build"])["ios-build"]
    assert v["verdict"] == "proven" and v["attempts"] == 1 and v["last_green"]


def test_gate_can_fail_does_not_keep_its_own_copy_of_the_journal_reader():
    """Pins the single-reader property itself. Without this, the duplicate simply comes
    back the next time someone needs one more field out of the journal — which is how it
    arrived the first time."""
    src = (ROOT / "ops" / "tests" / "test_gate_can_fail.sh").read_text()
    assert "gate_history_verdicts" in src, "the shell side must call the shared reader"
    assert "json.loads" not in src, "a second journal parser has reappeared"


def test_a_missing_warn_level_tool_stays_advisory(tmp_path):
    """Level is the disposition; a missing tool must not promote an advisory into a
    blocker (nor the reverse — see the rc!=0 branch it mirrors)."""
    spec = MODULE._shell("ghost", "ops", ["ops/definitely_not_here.sh"], "warn")
    assert MODULE._run_gate(spec, str(tmp_path))["status"] == "warn"


LEDGER_VIEW_REL = "docs/runbook/improvement_backlog.md"


def _install_ledger_stub(repo: Path, marker: Path, *, fail: str = "",
                         probe_lock: bool = False, render_noop: bool = False,
                         doc_reanchor: bool = False,
                         fail_with_doc_plan: bool = False) -> None:
    """A stand-in for ops/backlog.py that records HOW it was called and behaves like
    the real generator: `render` rebuilds the view from the entry files, `--check`
    compares, `reanchor` rewrites an anchor field.

    The ledger half (does `reanchor` actually re-point an orphaned sha) is already
    witnessed by ops/tests/test_backlog.py; what is unwitnessed here is the
    orchestrator's side of the contract — which subcommands, with which flags, in
    which order, from which directory, and under which lock.

    Each invocation appends `<cwd>\t<argv...>` to `marker`, so a test can assert all
    four. `fail` names a subcommand that should exit 2 (the real `render`'s
    entry-loss refusal is an exit 2, not a crash). `probe_lock` makes the stub try
    the trunk lock non-blockingly and record whether it was already held.
    """
    (repo / "ops").mkdir(exist_ok=True)
    (repo / "docs" / "runbook" / "backlog").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "runbook" / "backlog" / "E1.json").write_text(
        "anchor=old\n", encoding="utf-8")
    if doc_reanchor or fail_with_doc_plan:
        (repo / "docs" / "reference").mkdir(parents=True, exist_ok=True)
        (repo / "docs" / "reference" / "E.md").write_text(
            "verified_against: old\n", encoding="utf-8")
    (repo / LEDGER_VIEW_REL).write_text("stale\n", encoding="utf-8")
    stub = repo / "ops" / "backlog.py"
    stub.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env python3
        import sys, pathlib, importlib.util, json
        # Anchored on THIS FILE, exactly like the real tool's ROOT. Hard-coding the
        # primary's path here made the worktree's copy read and write the primary's
        # store, so the branch never diverged and the conflict fixture quietly
        # stopped reproducing the thing it was named after.
        repo = pathlib.Path(__file__).resolve().parents[1]
        store = repo / "docs" / "runbook" / "backlog"
        view = repo / {LEDGER_VIEW_REL!r}
        note = ""
        if {probe_lock!r}:
            # Ask the same two functions the orchestrator uses, rather than
            # re-deriving the lock path here. The hand-copied version of this probe
            # watched `.cache/kg-main-advance` while the code locks
            # `.cache/kg-main-advance.lock`, so it reported FREE unconditionally —
            # a green light wired to nothing.
            def _load(name, path):
                spec = importlib.util.spec_from_file_location(name, path)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
                return mod
            _wr = _load("wr_probe", {str(ROOT / "ops" / "worktree_registry.py")!r})
            free = _wr._try_acquire_ledger_lock_nb(repo / ".cache" / "kg-main-advance")
            note = "\\ttrunk-lock=" + ("FREE" if free else "HELD")
        m = pathlib.Path({str(marker)!r})
        line = str(pathlib.Path.cwd()) + "\\t" + " ".join(sys.argv[1:]) + note + "\\n"
        m.write_text((m.read_text() if m.exists() else "") + line)
        sub = sys.argv[1]
        if sub == {fail!r}:
            if {fail_with_doc_plan!r} and "--json" in sys.argv:
                doc = repo / "docs" / "reference" / "E.md"
                doc.write_text("verified_against: new\\n")
                print(json.dumps({{"ok": False, "doc_paths": [
                    "docs/reference/E.md"
                ]}}))
            print("REFUSED: stub was told to refuse", file=sys.stderr)
            sys.exit(2)
        expected = "".join(sorted(p.read_text() for p in store.glob("*.json")))
        if sub == "reanchor" and "--commit" in sys.argv:
            for p in sorted(store.glob("*.json")):
                p.write_text(p.read_text().replace("anchor=old", "anchor=new"))
            if {doc_reanchor!r}:
                doc = repo / "docs" / "reference" / "E.md"
                doc.write_text("verified_against: new\\n")
            if "--json" in sys.argv:
                print(json.dumps({{"doc_plan": ([{{"path": "docs/reference/E.md", "old": "old", "new": "new"}}] if {doc_reanchor!r} else []), "doc_unmatched": [], "doc_landed": (["docs/reference/E.md"] if {doc_reanchor!r} else [])}}))
        elif sub == "render" and "--check" in sys.argv:
            sys.exit(0 if view.read_text() == expected else 1)
        elif sub == "render" and "--commit" in sys.argv:
            if not {render_noop!r}:
                view.write_text(expected)
        """), encoding="utf-8")
    stub.chmod(0o755)
    # Touching docs/** routes the docs gates; this scratch repo has no real ones and
    # a `block` verdict would stop the cutover before the rebase this test is about.
    lint = repo / "ops" / "docs_lint.sh"
    lint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    lint.chmod(0o755)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "install ledger stub"], repo)


@gitmark
def test_post_landing_repair_commits_only_reanchored_doc_paths(scratch):
    """Docs rewritten by reanchor share the repair commit's path contract."""
    _tmp, repo, _remote = scratch
    marker = repo / "invocations.txt"
    _install_ledger_stub(repo, marker, doc_reanchor=True)

    repair = MODULE._post_landing_repair(repo)

    assert repair["ok"] is True
    assert repair["committed"] is True
    assert "docs/reference/E.md" in repair["repair_paths"]
    changed = _git(["show", "--format=", "--name-only", "HEAD"], repo)
    assert "docs/runbook/backlog/E1.json" in changed
    assert "docs/reference/E.md" in changed
    assert (repo / "docs/reference/E.md").read_text() == "verified_against: new\n"


@gitmark
def test_cutover_repairs_the_ledger_it_just_rewrote(scratch, tmp_path):
    """cutover's rebase mutates the tree AFTER the gate last looked at it.

    Measured in a clone of the real repo: a `fixed_by` sha recorded on a branch
    becomes `fixed-by-orphaned` once main has moved under it — `validate` went
    0 problems -> 1 problems. The correct sha does not exist until the landing has
    happened, so the landing step owns the repair.

    Every flag here is load-bearing and every one of them was, at some point, not
    asserted: dropping `--commit` from both invocations left 294 tests green while
    the repair silently did nothing but dry-runs.
    """
    _tmp, repo, _remote = scratch
    marker = tmp_path / "invocations.txt"
    _install_ledger_stub(repo, marker, probe_lock=True)
    state = str(tmp_path / "reg.json")

    rc, opened = _run_json(["open", "--intent", "do the thing", "--slug", "thing",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and cut["landed"] is True

    calls = [ln.split("\t") for ln in
             marker.read_text(encoding="utf-8").splitlines()]
    argvs = [c[1] for c in calls]
    # the flags, not just the subcommand names
    assert "reanchor --docs --commit --json" in argvs, argvs
    assert "validate --baseline-check" in argvs, argvs
    # `render` is NOT here any more: the generated view left version control
    # (IMP-20260807-b9526c), so there is no tracked derived file for the trunk to
    # keep in step. `reanchor` stays — orphaned `fixed_by` shas are a fact about the
    # STORE, which the rebase really does invalidate.
    assert not any(a.startswith("render") for a in argvs), argvs
    # the ORDER: validating before the write would grade the old data
    assert argvs.index("reanchor --docs --commit --json") < argvs.index(
        "validate --baseline-check"
    ), argvs
    # the DIRECTORY: the repair is about the trunk, which lives in the primary
    assert {c[0] for c in calls} == {str(repo.resolve())}, calls
    # and the LOCK: the repair rewrites the same trunk files the ff just moved, so
    # it belongs to the same critical section. Run outside it, two concurrent
    # repairs raced in the atomic-write helper and one died, leaving the primary
    # dirty — which blocks every later cutover.
    assert all("trunk-lock=HELD" in ln
               for ln in marker.read_text(encoding="utf-8").splitlines()), \
        marker.read_text(encoding="utf-8")

    # and what the repair produced is COMMITTED — a repair left uncommitted just
    # moves the failure to the next cutover, which refuses on a dirty primary.
    # tracked-clean specifically: untracked residue does not block the next cutover,
    # a tracked leftover does.
    assert _git(["status", "--porcelain", "--untracked-files=no"], repo).strip() == ""
    assert (repo / "docs" / "runbook" / "backlog" / "E1.json").read_text() == "anchor=new\n"
    assert cut["repair"]["committed"] is True
    assert cut["trunk_tip"] == _git(["rev-parse", "HEAD"], repo).strip()
    assert cut["trunk_tip"] != cut["sha"]


@gitmark
def test_a_failed_repair_puts_the_primary_back_rather_than_blocking_every_later_cutover(
        scratch, tmp_path):
    """A repair step that exits non-zero must not leave its edits in the primary.

    Measured before this was handled: the first repair step wrote its edit, the
    second refused, the repair returned early, and the edit stayed in the primary's
    working tree. The next cutover then refused with "primary working tree is dirty …
    likely another session is working in the primary" — pointing the next agent at a
    co-tenant who does not exist, for residue this code left. In a round of ten
    branches that is nine of them dead on the first landing.

    The refusing step used to be `render` (its entry-loss guard exits 2 by design).
    That step is gone with the view, so the failure is injected into `reanchor`,
    which is the step that remains — the invariant under test is "a failed repair
    restores", not "render is the one that fails".
    """
    _tmp, repo, _remote = scratch
    marker = tmp_path / "invocations.txt"
    _install_ledger_stub(repo, marker, fail="reanchor")
    state = str(tmp_path / "reg.json")
    before = (repo / "docs" / "runbook" / "backlog" / "E1.json").read_text()

    rc, opened = _run_json(["open", "--intent", "do the thing", "--slug", "thing",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])

    # the landing itself still succeeded — a completed ff is not rolled back
    assert rc == MODULE.EXIT_OK and cut["landed"] is True
    assert cut["repair"]["ok"] is False and cut["repair"]["committed"] is False
    assert "exited 2" in cut["repair"]["error"]
    assert cut["repair"]["restored"] is True
    # the whole point: the next cutover is not blocked by this one's debris
    assert _git(["status", "--porcelain", "--untracked-files=no"], repo).strip() == ""
    assert (repo / "docs" / "runbook" / "backlog" / "E1.json").read_text() == before


@gitmark
def test_a_failed_reanchor_reports_and_restores_an_arbitrary_document_path(
        scratch, tmp_path):
    """A failed child command must still identify every document it touched.

    The real reanchor transaction rolls its own writes back.  This companion
    fixture covers the orchestrator boundary: even when the child exits before
    a success payload, its failure JSON carries the document path so the
    primary restore is not narrowed to the ledger directory.
    """
    _tmp, repo, _remote = scratch
    marker = tmp_path / "invocations.txt"
    _install_ledger_stub(repo, marker, fail="reanchor", fail_with_doc_plan=True)
    before = (repo / "docs" / "reference" / "E.md").read_text(encoding="utf-8")

    repair = MODULE._post_landing_repair(repo)

    assert repair["ok"] is False
    assert repair["restored"] is True
    assert "docs/reference/E.md" in repair["repair_paths"]
    assert (repo / "docs" / "reference" / "E.md").read_text(encoding="utf-8") == before
    assert _git(["status", "--porcelain", "--untracked-files=no"], repo).strip() == ""


def _stub_repo_commit(repo: Path, msg: str) -> None:
    subprocess.run([sys.executable, str(repo / "ops" / "backlog.py"), "render",
                    "--commit"], cwd=str(repo), check=True, capture_output=True)
    _git(["add", "--", "docs/runbook"], repo)
    _git(["commit", "-qm", msg], repo)


def _seed_neighbouring_rows(repo: Path) -> None:
    """Rows that sort either side of what the branch and the trunk are about to add.

    Without them both sides append at end-of-file and git merges the two appends
    without complaint — the fixture would silently stop testing anything. With them,
    both sides insert a line into the SAME gap, which is the collision the real
    ledger produces once its rows are content-hash-scattered.
    """
    (repo / "docs" / "runbook" / "backlog" / "A.json").write_text("aaa\n")
    (repo / "docs" / "runbook" / "backlog" / "Z.json").write_text("zzz\n")


def _diverge_on_the_generated_view(repo: Path, wt: Path, *, also: str = "") -> None:
    """Branch and trunk each file an entry, so both rewrite the generated view at the
    same place — the shape that conflicts. `also` additionally puts a real (ungenerated)
    conflict in `f`."""
    (wt / "docs" / "runbook" / "backlog" / "E2.json").write_text("e2\n")
    if also:
        (wt / "f").write_text("branch edit\n")
        _git(["add", "--", "f"], wt)
    _stub_repo_commit(wt, "branch files E2")
    (repo / "docs" / "runbook" / "backlog" / "E3.json").write_text("e3\n")
    if also:
        (repo / "f").write_text("trunk edit\n")
        _git(["add", "--", "f"], repo)
    _stub_repo_commit(repo, "trunk files E3")


@gitmark
def test_catchup_leaves_a_conflict_in_an_ungenerated_file_for_a_human(scratch, tmp_path):
    """The narrowness is the safety. A conflict in any file the repo has not declared
    generated is a decision, and a tool that resolves decisions by regenerating one
    side of them is worse than one that stops."""
    _tmp, repo, _remote = scratch
    _install_ledger_stub(repo, tmp_path / "invocations.txt")
    _seed_neighbouring_rows(repo)
    _stub_repo_commit(repo, "seed view")
    state = str(tmp_path / "reg.json")

    rc, opened = _run_json(["open", "--intent", "file entries", "--slug", "entries",
                            "--state", state, "--json"])
    wt = Path(opened["path"])
    _diverge_on_the_generated_view(repo, wt, also="f")

    rc, out = _run_json(["catchup", "--worktree", str(wt), "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, out
    assert out["error"] == "rebase failed (aborted)", out
    assert out["rebased"] is False
    # aborted cleanly: no half-rebase left for the next command to trip over
    rc_state, _ = MODULE._git(["rev-parse", "--verify", "--quiet", "REBASE_HEAD"],
                              cwd=str(wt))
    assert rc_state != 0, "a rebase was left in progress"
    assert _git(["status", "--porcelain"], wt).strip() == ""


@gitmark
def test_catchup_on_an_up_to_date_worktree_changes_nothing(scratch, tmp_path):
    """A no-op has to be a cheap no-op, not a rewrite: `catchup` is the command the
    refusals name, so agents will run it speculatively."""
    _tmp, repo, _remote = scratch
    _install_ledger_stub(repo, tmp_path / "invocations.txt")
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "nothing", "--slug", "nothing",
                            "--state", state, "--json"])
    wt = Path(opened["path"])
    before = _git(["rev-parse", "HEAD"], wt).strip()
    rc, out = _run_json(["catchup", "--worktree", str(wt), "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and out["behind"] is False and out["rebased"] is False
    assert _git(["rev-parse", "HEAD"], wt).strip() == before


def test_the_behind_base_refusal_names_a_command_that_exists():
    """The refusal used to say `git -C <path> rebase main`. A refusal is a routing
    decision, and pointing it at raw git routes the agent out of the flow at exactly
    the moment the step can fail. (It was originally argued from a generated file
    that no longer exists — IMP-20260807-b9526c — but the routing argument does not
    depend on it.)"""
    msg = MODULE._behind_base_refusal("/w", "main",
                                      {"behind_commits": 2, "base_changed_files": ["a"]})
    assert "catchup" in msg and "git -C" not in msg, msg
    names = {a.dest for a in MODULE.build_parser()._subparsers._group_actions}
    assert MODULE.build_parser().parse_args(
        ["catchup", "--worktree", "/w"]).func is MODULE.cmd_catchup


@gitmark
def test_the_repair_never_commits_or_destroys_a_co_tenants_untracked_entry(
        scratch, tmp_path):
    """An untracked entry JSON sitting in the primary is a LEGAL, common state — an
    agent filed one and has not committed it — and `_primary_ff_ready` deliberately
    ignores it (`--untracked-files=no`), so it does not block anyone's cutover.

    Measured before this was fixed, both directions from that one state:
      * the repair's `git add -- docs/runbook/backlog` staged it, and the resulting
        commit — the one whose message says everything in it was re-derived by a
        tool, carrying a review exemption — CONTAINED someone else's unfinished work;
      * on the failing path, `git checkout HEAD -- <dir>` is a silent no-op for a
        staged-new path absent from HEAD, so the restore reported success over a
        primary that was still dirty. Which blocks every later cutover.
    """
    _tmp, repo, _remote = scratch
    marker = tmp_path / "invocations.txt"
    _install_ledger_stub(repo, marker)
    state = str(tmp_path / "reg.json")
    cotenant = repo / "docs" / "runbook" / "backlog" / "COTENANT.json"
    cotenant.write_text("someone else is mid-thought\n", encoding="utf-8")

    rc, opened = _run_json(["open", "--intent", "x", "--slug", "co", "--state", state,
                            "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK and cut["repair"]["committed"] is True, cut

    landed = _git(["show", "--pretty=", "--name-only", "HEAD"], repo).split()
    assert "docs/runbook/backlog/COTENANT.json" not in landed, landed
    assert cotenant.exists(), "the repair deleted a co-tenant's file"
    assert cotenant.read_text() == "someone else is mid-thought\n"
    # untracked residue is fine; tracked residue is what blocks the next cutover
    assert _git(["status", "--porcelain", "--untracked-files=no"], repo).strip() == ""


@gitmark
def test_a_failed_repair_restores_even_when_a_co_tenants_file_is_present(
        scratch, tmp_path):
    """The failing half of the same state. `restored` must come from re-reading
    git's status, not from the restore command's exit code — the command can succeed
    while the tree is still dirty."""
    _tmp, repo, _remote = scratch
    # `reanchor` rather than `render`: the render step left the repair with the view
    # (IMP-20260807-b9526c). What is under test is "a failed repair restores", not
    # which subcommand happened to be the failing one.
    _install_ledger_stub(repo, tmp_path / "inv.txt", fail="reanchor")
    state = str(tmp_path / "reg.json")
    cotenant = repo / "docs" / "runbook" / "backlog" / "COTENANT.json"
    cotenant.write_text("mid-thought\n", encoding="utf-8")

    rc, opened = _run_json(["open", "--intent", "x", "--slug", "co2", "--state", state,
                            "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])

    assert rc == MODULE.EXIT_OK and cut["landed"] is True
    assert cut["repair"]["ok"] is False and cut["repair"]["restored"] is True
    assert _git(["status", "--porcelain", "--untracked-files=no"], repo).strip() == ""
    assert cotenant.exists() and cotenant.read_text() == "mid-thought\n"


def test_a_hostile_git_editor_cannot_freeze_a_git_mutation(tmp_path):
    """`git -c core.editor=true` does NOT prevent this: git reads `GIT_EDITOR` FIRST.

    Measured with `GIT_EDITOR` pointing at a 25-second sleep: the editor really ran
    (`elapsed=25.6s`). These runs carry no timeout and `cutover` holds the trunk lock
    while it works, so one operator's editor preference freezes every cutover in the
    repo. This machine's own `GIT_EDITOR=true` is exactly why the hole was invisible
    here, so the test sets a hostile one rather than trusting the environment.

    Driven through a `git commit --amend` with no `-m` — a command that opens the
    editor unconditionally — rather than through a conflicted rebase. The old version
    rode on `catchup`'s generated-view conflict RESOLVER, which called
    `rebase --continue`; that resolver is gone with the view (IMP-20260807-b9526c),
    and a guarantee must not disappear because the scenario that happened to exercise
    it did. `_noninteractive_env` is the site; this asserts at the site.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "seed"], cwd=repo, check=True)

    trap = tmp_path / "editor_trap.sh"
    trap.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    trap.chmod(0o755)
    prev = os.environ.get("GIT_EDITOR")
    os.environ["GIT_EDITOR"] = str(trap)
    try:
        # positive control: the trap is real and git does honour GIT_EDITOR, so a
        # green result below is the hardening and not a broken trap
        bare = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                               "commit", "--amend"], cwd=repo,
                              capture_output=True, text=True)
        assert bare.returncode != 0, "the editor trap did not fire — this test proves nothing"

        rc, out = MODULE._git_mutation(
            ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "--amend"],
            cwd=repo, label="editor-probe")
    finally:
        if prev is None:
            os.environ.pop("GIT_EDITOR", None)
        else:
            os.environ["GIT_EDITOR"] = prev

    assert rc == 0, f"a hostile GIT_EDITOR reached a tool-run git command: {out}"
    assert MODULE._noninteractive_env()["GIT_EDITOR"] == "true"
    assert MODULE._noninteractive_env()["GIT_SEQUENCE_EDITOR"] == "true"


@gitmark
def test_catchup_is_blocked_by_freeze(scratch, tmp_path):
    """`freeze` is the stop-the-world lock for repo surgery. `catchup` rewrites
    history — that is what a rebase is — so it belongs on the blocked side. It was
    missed only because it is the newest verb, and a lock a new verb can walk past
    is not a lock."""
    _tmp, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "x", "--slug", "frozen", "--state",
                            state, "--json"])
    wt = opened["path"]
    rc, _ = _run_json(["freeze", "on", "--reason", "history rewrite", "--state", state,
                       "--json"])
    assert rc == MODULE.EXIT_OK
    rc, out = _run_json(["catchup", "--worktree", wt, "--state", state, "--commit",
                         "--json"])
    assert rc == MODULE.EXIT_BLOCK, out
    assert "history rewrite" in json.dumps(out, ensure_ascii=False), out


@gitmark
def test_a_restore_that_did_not_work_is_reported_as_a_failure(tmp_path, monkeypatch):
    """`restored` must describe the TREE, not the exit code of the command that tried.

    Measured on the shape that motivated this: `git checkout HEAD -- <dir>` returns 0
    for a path that is staged-new and absent from HEAD, having changed nothing. A
    version that trusted that rc reported a clean primary over a dirty one — and a
    dirty primary is what blocks every later cutover. Here the restore is stubbed out
    entirely, so the only thing that can produce the right answer is re-reading git.
    """
    repo = tmp_path / "repo"; repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "docs" / "runbook" / "backlog").mkdir(parents=True)
    (repo / "docs" / "runbook" / "backlog" / "E1.json").write_text("committed\n")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "base"], repo)
    (repo / "docs" / "runbook" / "backlog" / "E1.json").write_text("half-written\n")

    real_git = MODULE._git

    def _git_without_restore(args, **kwargs):
        if args and args[0] in ("checkout", "reset"):
            return 0, ""          # succeeds loudly, does nothing
        return real_git(args, **kwargs)

    monkeypatch.setattr(MODULE, "_git", _git_without_restore)
    out: dict = {"error": "the repair failed"}
    MODULE._repair_restore(repo, out)

    assert out["restored"] is False, out
    assert "could not be restored" in out["error"], out
    assert "E1.json" in out["error"], out


# ===========================================================================
# open claims before it builds
# ===========================================================================

@gitmark
def test_open_refuses_a_ticket_another_worktree_already_holds(scratch):
    """And refuses with a non-zero code.

    `cmd_open` used to read the registry's return value only to pick which of two
    sentences to print, then `return EXIT_OK` unconditionally — so a caller that
    checked the exit code (which is the only thing a script or an agent's `&&`
    checks) was told the open had succeeded no matter what the ledger said.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")

    rc, first = _run_json(["open", "--intent", "fix it", "--slug", "first",
                           "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert first["backlog"] == ["IMP-0001"]

    rc, second = _run_json(["open", "--intent", "fix it too", "--slug", "second",
                            "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK, "a losing claimant was told the open succeeded"
    assert second["step"] == "open"
    # actionable: the loser has to be able to say WHO has it without reading the ledger
    assert second["conflicts"][0]["branch"] == "debug/first"


@gitmark
def test_a_losing_claimant_is_left_with_no_worktree_and_no_branch(scratch):
    """The reason `open` had to be reordered rather than just fixed.

    With `git worktree add` running first, the loser ended up holding a real
    directory and a real branch that no ledger record pointed at — residue that
    only `sweep` would find, and only if it happened to look. Claiming first means
    the loser never reaches the part that creates anything.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _run_json(["open", "--intent", "x", "--slug", "winner",
               "--backlog", "IMP-0001", "--state", state, "--json"])

    rc, _ = _run_json(["open", "--intent", "x", "--slug", "loser",
                       "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK

    assert not (repo / ".claude" / "worktrees" / "loser").exists()
    branches = subprocess.run(["git", "branch", "--list", "feat/loser"],
                              cwd=repo, capture_output=True, text=True).stdout
    assert branches.strip() == "", f"the refused open left a branch behind: {branches!r}"
    records = json.loads(Path(state).read_text())["records"]
    assert [r["branch"] for r in records if r["status"] == "active"] == ["feat/winner"]


@gitmark
def test_open_gives_the_claim_back_when_the_worktree_cannot_be_created(scratch):
    """Claiming first buys atomicity at the cost of a new failure window.

    Between the claim and the `git worktree add` there is now a moment where the
    ledger says a ticket is held by a worktree that does not exist. If `add` fails
    the claim has to be handed back, or the ticket is stuck until a human notices
    a record whose path is not there.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    # The branch already exists, so `worktree add -b` fails. Deliberately NOT
    # "occupy the path": `open` checks for an existing path before it claims, so
    # that route never reaches the window this test is about.
    _git(["branch", "feat/blocked"], repo)

    rc, payload = _run_json(["open", "--intent", "x", "--slug", "blocked",
                             "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert payload.get("claim_released") is True

    records = json.loads(Path(state).read_text())["records"]
    assert [r for r in records if r["status"] == "active"] == [], (
        "a failed open left an active record holding the ticket"
    )
    # and the ticket is immediately claimable again
    rc, _ = _run_json(["open", "--intent", "x", "--slug", "retry",
                       "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK


@gitmark
def test_open_without_a_ticket_still_works_and_claims_nothing(scratch):
    """Most opens are not backlog work; the flag is optional and stays that way."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, payload = _run_json(["open", "--intent", "poke at something", "--slug",
                             "explore", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    assert payload["backlog"] == []
    rec = json.loads(Path(state).read_text())["records"][0]
    assert rec["backlog"] == [] and rec["claimed_at"] is None


@gitmark
def test_open_next_backlog_claims_the_next_available_ticket_instead_of_racing_on_a_stale_list(
        scratch):
    """Two coordinators must not both read the same dispatch head and make one lose.

    The selection and the registry claim are one operation: after the first caller
    takes the worst-first head, the second caller moves to the next still-unclaimed
    entry without being handed the first id and refused.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")

    rc1, first = _run_json([
        "open", "--intent", "round four lane", "--slug", "round-four-01",
        "--next-backlog", "--state", state, "--json",
    ])
    rc2, second = _run_json([
        "open", "--intent", "round five lane", "--slug", "round-five-01",
        "--next-backlog", "--state", state, "--json",
    ])

    assert (rc1, rc2) == (MODULE.EXIT_OK, MODULE.EXIT_OK)
    assert first["backlog"] == ["IMP-0001"], first
    assert second["backlog"] == ["IMP-0002"], second
    assert first["selection"]["mode"] == "dispatch-head"
    assert second["selection"]["skipped_claimed"] == 1

    active = [r for r in json.loads(Path(state).read_text())["records"]
              if r["status"] == "active"]
    assert {r["backlog"][0] for r in active} == {"IMP-0001", "IMP-0002"}


def test_next_backlog_uses_its_owning_repo_for_contract_preflight(tmp_path):
    repo = tmp_path / "external-repo"
    store = repo / "docs" / "runbook" / "backlog"
    (repo / "ops").mkdir(parents=True)
    (repo / "ops" / "d4d05e_next_fix.py").write_text("# fix\n", encoding="utf-8")
    (repo / "ops" / "d4d05e_next_test.py").write_text("# test\n", encoding="utf-8")
    store.mkdir(parents=True)
    ticket = "IMP-20260810-abc123"
    (store / f"{ticket}.json").write_text(json.dumps({
        "schema": "kg.backlog.entry.v1", "id": ticket, "status": "triaged",
        "stream": "IMP", "severity": "med", "category": "tool",
        "date": "2026-08-10", "source": "test", "detail": "external next",
        "brief": "external dispatch contract", "scope": "small test-only guard",
        "plan": "run the guard", "acceptance": "red then green",
        "acceptance_cmd": "test -f ops/d4d05e_next_test.py",
        "acceptance_expect_rc": 0, "fix_site": "ops/d4d05e_next_fix.py:1",
        "groomed_at": "2026-08-10", "groomed_by": "test",
        "contract_status": "ready", "contract_baseline": "red",
        "contract_checked_at": "2026-08-10", "contract_checked_by": "test",
        "contract_evidence": "fix_site=pass; dependency=pass; baseline=RED",
    }), encoding="utf-8")
    state = str(tmp_path / "registry.json")
    worktree = repo / ".claude" / "worktrees" / "external-next"
    worktree.parent.mkdir(parents=True)

    rc, _claim, claimed, _selection = MODULE._claim_next_backlog(
        root=repo, state_arg=state, path=worktree,
        branch="feat/external-next", intent="external next", base="main",
    )

    assert rc == MODULE.EXIT_OK
    assert claimed == [ticket]


@gitmark
def test_parallel_next_backlog_claims_are_distinct_inside_the_ledger_critical_section(
        scratch):
    """Pin the lock boundary, not merely the happy sequential result."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")

    def take(lane):
        return MODULE._claim_next_backlog(
            root=repo, state_arg=state,
            path=repo / ".claude" / "worktrees" / lane,
            branch=f"feat/{lane}", intent=lane, base="main",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(take, ["r4-1", "r4-2", "r5-1", "r5-2"]))

    assert [r[0] for r in results] == [MODULE.EXIT_OK] * 4
    claimed = [r[2][0] for r in results]
    assert len(set(claimed)) == 4, claimed
    records = [r for r in json.loads(Path(state).read_text())["records"]
               if r["status"] == "active"]
    assert len(records) == 4
    assert len({ticket for r in records for ticket in r["backlog"]}) == 4


@gitmark
def test_adopting_a_live_worktree_does_not_quietly_release_its_ticket(scratch):
    """The invariant this whole change adds, broken by the change itself.

    `open`/`adopt` used to forward `--backlog` unconditionally. With no ids the argv
    is `["--backlog", "--json"]`, and argparse's nargs="*" resolves that to `[]` —
    not None — which is the "replace the claim" branch. So the registry's
    "omit = leave it alone" rule was unreachable through the only two callers that
    exist, and the registry test pinning it was pinning dead semantics.

    Measured end to end before the fix: a LIVE worktree holding IMP-0001, a plain
    `adopt` elsewhere, and the ledger came back `backlog: []`, `claimed_at: None` —
    with a second agent able to take the ticket while the first was still working.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, live = _run_json(["open", "--intent", "x", "--slug", "live",
                          "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK

    # Re-registering THIS worktree with no --backlog. `adopt` is the reachable way
    # to do that (`open` refuses an existing path), and re-adopting a live worktree
    # is ordinary: it is the bootstrap path and it is idempotent by design.
    #
    # It has to be the SAME record. An earlier version of this test adopted an
    # unrelated second worktree and passed against the bug, because the empty list
    # overwrites the claim of the record being registered — so wiping the unrelated
    # record's (already empty) claim changed nothing and proved nothing.
    rc, _ = _run_json(["adopt", "--worktree", live["path"], "--intent", "x",
                       "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK

    records = json.loads(Path(state).read_text())["records"]
    held = {r["branch"]: r.get("backlog") for r in records if r["status"] == "active"}
    assert held.get("feat/live") == ["IMP-0001"], (
        f"the live worktree's claim was released by an unrelated adopt: {held}"
    )
    # and the ticket is still not available to anyone else
    rc, _ = _run_json(["open", "--intent", "x", "--slug", "thief",
                       "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK


@gitmark
def test_when_the_claim_cannot_be_handed_back_open_says_what_to_run(scratch):
    """The failure path of the failure path.

    `open` releases the claim when `git worktree add` fails. If THAT release also
    fails the ticket is stuck, and the only thing standing between the operator and
    a ledger read is this message — which had no test, so nothing checked that it
    named a command that exists.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    _git(["branch", "feat/stuck"], repo)   # makes `worktree add -b` fail

    real = MODULE._registry
    calls = []

    def only_the_release_fails(argv):
        calls.append(argv[0])
        if argv[0] == "resolve":
            return MODULE.EXIT_USAGE, None
        return real(argv)

    MODULE._registry = only_the_release_fails
    try:
        rc, payload = _run_json(["open", "--intent", "x", "--slug", "stuck",
                                 "--backlog", "IMP-0001", "--state", state, "--json"])
    finally:
        MODULE._registry = real

    assert rc == MODULE.EXIT_BLOCK
    assert calls == ["register", "resolve"]
    assert payload["claim_released"] is False
    # the ticket really is still held — the payload is not being optimistic
    records = json.loads(Path(state).read_text())["records"]
    assert [r["backlog"] for r in records if r["status"] == "active"] == [["IMP-0001"]]


@gitmark
def test_a_refused_adopt_tells_the_operator_who_holds_the_ticket(scratch):
    """The human channel, which is the one a person actually reads.

    `_registry` is called with --json, so the registry's own "already claimed by
    [...]" line goes out as JSON and never reaches the terminal. `open` rebuilds
    that sentence; `adopt` printed a bare "register failed", which tells a losing
    agent nothing it can act on.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, _ = _run_json(["open", "--intent", "x", "--slug", "holder",
                       "--backlog", "IMP-0001", "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK

    other = Path(repo) / ".claude" / "worktrees" / "contender"
    _git(["worktree", "add", "-b", "feat/contender", str(other), "main"], repo)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = MODULE.main(["adopt", "--worktree", str(other), "--intent", "same work",
                          "--backlog", "IMP-0001", "--state", state])
    human = buf.getvalue()
    assert rc == MODULE.EXIT_BLOCK
    assert "IMP-0001" in human and "feat/holder" in human, (
        f"the refusal names neither the ticket nor its holder:\n{human}"
    )


def _queue_rows(primary) -> list[dict]:
    q = Path(primary) / ".cache" / "backlog_anchor_queue.jsonl"
    if not q.exists():
        return []
    return [json.loads(ln) for ln in q.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _stage_row(primary, branch: str, entry_id: str) -> None:
    """What `backlog.py stage` leaves behind, written directly.

    Direct rather than by driving backlog.py: this test is about what CUTOVER does
    to a queue, and shelling out to the real stager would make it depend on a store
    fixture and on backlog.py's own validation staying green.
    """
    q = Path(primary) / ".cache" / "backlog_anchor_queue.jsonl"
    q.parent.mkdir(parents=True, exist_ok=True)
    with q.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": entry_id, "verdict": "CONFIRMED-FIXED", "by": "t",
                             "evidence": "ran it", "status": "fixed", "at": "2026-08-07",
                             "branch": branch, "landed_sha": None}) + "\n")


@gitmark
def test_cutover_stamps_the_landed_sha_onto_this_branchs_staged_closures(scratch):
    """The sha only becomes knowable at the moment of landing.

    A hunter stages a closure before its branch has been rebased, so it cannot know
    which commit will carry the fix — and recording the pre-rebase sha is exactly
    the orphaned `fixed_by` the reanchor repair exists to clean up after. Stamping
    here means the closure names the commit that actually reached the trunk.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix a thing", "--slug", "stamped",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)

    _stage_row(repo, "debug/stamped", "IMP-0001")
    _stage_row(repo, "debug/other-branch", "IMP-0002")   # someone else's, untouched

    assert _run_json(["gate", "--worktree", wt, "--state", state, "--json"])[0] == MODULE.EXIT_OK
    rc, payload = _run_json(["cutover", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    assert rc == MODULE.EXIT_OK

    rows = {r["id"]: r for r in _queue_rows(repo)}
    assert rows["IMP-0001"]["landed_sha"] == payload["sha"]
    assert rows["IMP-0002"]["landed_sha"] is None, "stamped a row belonging to another branch"
    assert payload["staged_closures"] == ["IMP-0001"]


@gitmark
def test_a_cutover_refused_before_it_starts_stamps_nothing(scratch):
    """The easy half: a refusal so early the trunk is never touched.

    Kept, but named for what it actually exercises. It used to be the ONLY guard on
    the stamp's position and it cannot do that job: with no gate verdict recorded,
    `cmd_cutover` returns before it resolves the primary and before it takes the
    advance lock, so it never reaches the ff at all — every possible stamp position
    passes it. Moving the stamp to just after the rebase, which is exactly the
    dangerous placement, left this test green (mutant survived, measured). The
    post-ff half is the test below.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix a thing", "--slug", "refused",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    _stage_row(repo, "debug/refused", "IMP-0001")

    # no gate verdict recorded -> cutover refuses before it does anything
    rc, _ = _run_json(["cutover", "--worktree", wt, "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert _queue_rows(repo)[0]["landed_sha"] is None


@gitmark
def test_a_cutover_that_gets_past_the_gate_and_then_fails_the_ff_stamps_nothing(scratch):
    """The half that actually pins the stamp's position.

    This drives the branch all the way through `gate` and the rebase, and then makes
    the fast-forward itself fail — an untracked file in the primary that the branch
    also adds, which `git merge --ff-only` refuses to overwrite and which the
    tracked-clean readiness check deliberately allows through. So the run reaches
    the inside of the advance lock, rebases, and returns EXIT_BLOCK with local main
    unmoved.

    That is the window the stamp must stay out of. `make_commit_state` accepts a sha
    reachable from HEAD *or* main, so a sha written here would still validate when
    `anchor` runs from a worktree that has not been torn down — and the entry would
    close against a commit sitting on no trunk, with nothing downstream to complain.

    Mutation-checked: moving `_stamp_anchor_queue` to just after the rebase makes
    this red and every other test in the suite stay green.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix a thing", "--slug", "ffblocked",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "collide.txt").write_text("from the branch\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: collide"], wt)
    _stage_row(repo, "debug/ffblocked", "IMP-0001")

    assert _run_json(["gate", "--worktree", wt, "--state", state, "--json"])[0] == MODULE.EXIT_OK

    # untracked in the primary: passes the tracked-clean check, blocks the ff.
    (Path(repo) / "collide.txt").write_text("already here, untracked\n")
    before_main = _git(["rev-parse", "main"], repo)

    rc, payload = _run_json(["cutover", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, f"expected the ff to be refused, got {payload}"
    assert _git(["rev-parse", "main"], repo) == before_main, \
        "local main moved; this test no longer exercises a refused landing"
    assert _queue_rows(repo)[0]["landed_sha"] is None, (
        "a cutover that did not land stamped a sha onto the queue — `anchor` would "
        "close the entry against a commit on no trunk")


@gitmark
def test_a_concurrent_stage_cannot_wipe_the_sha_cutover_just_stamped(scratch):
    """The stamp is a read-modify-write of the same file `stage` appends to.

    Both sides now take the same lock, and this is the side where losing matters
    more. `_stamp_anchor_queue` runs exactly once, during its branch's cutover; by
    the time anyone notices, the branch is in the trunk and `resolve` has torn the
    worktree down, so the sha is never re-derivable. `anchor` would then file the
    row under "its branch has not landed", which is false, and the only other copy
    of the answer was in a payload nobody kept.

    The window is widened on purpose — the same method this repo's `_view_lock`
    docstring uses — because the real stamp is shorter than one process start, so
    "it did not happen at N=4" is not "it cannot happen".
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix a thing", "--slug", "stampsafe",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    _stage_row(repo, "debug/stampsafe", "IMP-0001")
    assert _run_json(["gate", "--worktree", wt, "--state", state, "--json"])[0] == MODULE.EXIT_OK

    queue = Path(repo) / ".cache" / "backlog_anchor_queue.jsonl"
    import threading

    def slow_appender():
        """A peer hunter staging its own row, holding the lock across the window."""
        with MODULE.wr._ledger_lock(queue):
            rows = [json.loads(ln) for ln in queue.read_text(encoding="utf-8").splitlines()
                    if ln.strip()]
            # Wide enough that cutover certainly reaches the stamp inside it. Erring
            # long is the safe direction: too short and an unlocked stamp simply
            # finishes first, the windows never overlap, and the mutant survives for
            # a timing reason rather than a correctness one.
            time.sleep(6.0)
            rows.append({"id": "IMP-0002", "verdict": "CONFIRMED-FIXED", "by": "peer",
                         "evidence": "ran it", "status": "fixed", "at": "2026-08-08",
                         "branch": "debug/peer", "landed_sha": None})
            queue.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                encoding="utf-8")

    thread = threading.Thread(target=slow_appender)
    thread.start()
    time.sleep(0.3)                              # let it read and settle into the gap
    rc, payload = _run_json(["cutover", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    thread.join(timeout=60)
    assert rc == MODULE.EXIT_OK, payload

    rows = {r["id"]: r for r in _queue_rows(repo)}
    assert rows["IMP-0001"]["landed_sha"] == payload["sha"], (
        "the peer's unlocked-era write would have restored landed_sha to null while "
        "cutover still reported the stamp as done")
    assert "IMP-0002" in rows, "the peer's own row was lost instead"


@gitmark
def test_resolve_names_the_landed_closures_still_waiting_on_the_wave_anchor(scratch):
    """Said out loud, and NOT blocking — a handoff note, not a warning.

    The queue is gitignored and lives on this machine only, so nothing downstream
    of `resolve` can notice a row nobody anchored: not the gate, not the docs lint,
    and not any reader of the ledger — `list`, `show` and the generated view all
    read the store, where the entry just looks open. (Not "the board": the planned
    bounty board does not exist yet, and the only board this repo ever had,
    `converge_board.py`, is retired. The earlier docstring's "(measured)" had
    nothing behind it.)

    Blocking would be wrong: the closure HAS landed, the entry is merely not closed
    yet, and a teardown that refuses strands the worktree instead of fixing it. So
    would `⚠ never anchored`, which is what the first draft printed — stamped-but-
    unanchored is the documented normal state at this point, and a gate that reds on
    the normal path is one that gets switched off. What earns the line is that this
    is the last moment the worktree exists to say it.
    """
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "fix a thing", "--slug", "unanchored",
                            "--state", state, "--json"])
    wt = opened["path"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "work: notes"], wt)
    _stage_row(repo, "debug/unanchored", "IMP-0001")
    assert _run_json(["gate", "--worktree", wt, "--state", state, "--json"])[0] == MODULE.EXIT_OK
    assert _run_json(["cutover", "--worktree", wt, "--state", state,
                      "--commit", "--json"])[0] == MODULE.EXIT_OK

    rc, payload = _run_json(["resolve", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, "an unanchored closure must not block teardown"
    assert payload["pending_anchor"] == ["IMP-0001"]


@gitmark
def test_gate_refuses_a_worktree_with_an_operation_in_flight(scratch, tmp_path):
    """A conflicted tree must not be able to record a green verdict.

    Measured, and it is how this guard was found: a `git rebase` stopped on a
    delete-vs-modify conflict, and `gate` run over that tree reported
    `verdict: pass` with `changed_files: []` and two gates run. `git diff` against
    the trunk on a half-applied rebase describes the PARTIAL state, so `plan_gates`
    routed nothing and `aggregate_verdict([])` is "pass". That verdict is bound to
    the current HEAD and is exactly what `cutover` demands as proof.

    The signal is the OPERATION, not the empty diff: a branch already contained in
    the trunk legitimately has nothing to gate, and refusing on empty-diff alone
    would break that case.
    """
    tmp, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "x", "--slug", "midflight",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = Path(opened["path"])

    # branch and trunk both touch the same line, so the rebase is guaranteed to stop
    (wt / "clash.txt").write_text("branch side\n", encoding="utf-8")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "branch: clash"], wt)
    (repo / "clash.txt").write_text("trunk side\n", encoding="utf-8")
    _git(["add", "-A"], repo); _git(["commit", "-qm", "trunk: clash"], repo)

    rebase = subprocess.run(["git", "rebase", "main"], cwd=str(wt),
                            capture_output=True, text=True,
                            env={**os.environ, "GIT_EDITOR": "true"})
    assert rebase.returncode != 0, "the fixture failed to produce a stopped rebase"
    assert MODULE._interrupted_operation(wt) == "rebase"

    rc, payload = _run_json(["gate", "--worktree", str(wt), "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK, f"gate did not refuse a mid-rebase tree: {payload}"
    assert payload.get("interrupted") == "rebase", payload
    assert "verdict" not in payload, "a refused gate must not record a verdict"

    # and the refusal lifts once the tree is coherent again
    subprocess.run(["git", "rebase", "--abort"], cwd=str(wt), check=True,
                   capture_output=True)
    assert MODULE._interrupted_operation(wt) is None


def test_a_doc_deleted_in_the_diff_does_not_block_the_docs_gate():
    """Removing a doc must not be un-gateable.

    All three docs gates READ the file, and a deleted path is still a changed path.
    `docs_lint --files <gone>` exits 2 with "--files 路徑不存在" — so before this,
    **every commit that removed a doc was blocked**, by an error phrased as if the
    caller had mistyped. Measured on the commit that removed the generated ledger
    view (IMP-20260807-b9526c): that was the second gate defect this repo's own
    dogfooding turned up in one session.

    The removal is NAMED rather than silently dropped, matching `ops-shell-untested`
    and `data-plane-unowned`: a gate list that quietly shrinks reads as "everything
    was checked".
    """
    gone, live = "docs/sop/removed.md", "docs/sop/kept.md"
    gates = _by_name(plan_gates([gone, live], ops_test_exists=lambda rel: rel != gone))

    assert "docs-lint" in gates
    assert gone not in gates["docs-lint"]["cmd"], "the deleted doc was handed to docs_lint"
    assert live in gates["docs-lint"]["cmd"]
    for name in ("docs-conflict-markers", "docs-verified-against"):
        assert gates[name]["files"] == [live], f"{name} still points at a deleted file"

    assert gates["docs-removed"]["files"] == [gone]
    assert gates["docs-removed"]["level"] == "warn", "a deletion is not a failure"

    # and with nothing left to lint, the reading gates do not appear at all rather
    # than running over an empty list
    only_gone = _by_name(plan_gates([gone], ops_test_exists=lambda rel: False))
    assert "docs-lint" not in only_gone
    assert only_gone["docs-removed"]["files"] == [gone]


@gitmark
def test_resolve_names_claimed_tickets_that_were_never_staged(scratch, tmp_path):
    """The failure this tool had on its own flagship task.

    `open --backlog X` claimed it, the work landed, `resolve` printed
    `pending_anchor: []`, the worktree vanished, and X was still `open`. Five other
    tickets in the same session closed correctly — every one of them FILED mid-work.
    The claim is taken at the start and the closure happens at the end, and nothing
    carried the obligation across; teardown is the last moment anyone knows the claim
    existed.

    `pending_anchor` cannot cover this: it asks "did someone who remembered to close
    it finish the job". Both report `[]` on the happy path, which is exactly why the
    second question needs its own answer — an unclosed claim and a clean teardown
    were byte-identical in the output.
    """
    tmp, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "x", "--slug", "unclosed",
                            "--backlog", "IMP-0001", "IMP-0002",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK, opened
    wt, wt_branch = opened["path"], opened["branch"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)

    # one of the two gets a closure; the other is the one that would vanish.
    # Branch name from the payload, never guessed: `open` derives the prefix from
    # the intent text, so a hardcoded "debug/…" stages a row nothing will match and
    # the test passes for the wrong reason.
    _stage_row(repo, wt_branch, "IMP-0001")

    assert _run_json(["gate", "--worktree", wt, "--state", state, "--json"])[0] == MODULE.EXIT_OK
    assert _run_json(["cutover", "--worktree", wt, "--state", state,
                      "--commit", "--json"])[0] == MODULE.EXIT_OK

    rc, payload = _run_json(["resolve", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, "an unclosed claim must not block teardown"
    assert payload["claimed_without_closure"] == ["IMP-0002"], payload
    assert payload["pending_anchor"] == ["IMP-0001"], (
        "the two questions must not collapse into one another")


def test_the_claim_is_read_before_the_ledger_record_is_struck(scratch, tmp_path):
    """Order is the whole trick.

    `resolve` closes the ledger record ahead of the git steps, and every reader of
    that ledger filters on `status == active`. Reading the claim afterwards would
    always answer "nothing was claimed" — a check that can only ever pass, which is
    worse than no check because it looks like one.
    """
    tmp, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "x", "--slug", "ordering",
                            "--backlog", "IMP-0007", "--state", state, "--json"])
    wt, wt_branch = opened["path"], opened["branch"]
    assert MODULE._claimed_tickets(state, wt_branch) == ["IMP-0007"]

    _run_json(["resolve", "--worktree", wt, "--state", state, "--commit", "--force",
               "--json"])
    assert MODULE._claimed_tickets(state, wt_branch) == [], (
        "a struck record still reported its claim — then the guard would fire after "
        "teardown instead of before it")


@gitmark
def test_a_claim_already_closed_in_the_store_is_not_reported(scratch, tmp_path):
    """The guard false-positived on its own first real teardown.

    `anchor --commit` DRAINS the queue. The documented order leaves the row in place
    when `resolve` looks (stage → cutover → resolve → wave-end anchor), but
    anchoring first is equally legitimate — and then the row that proved the closure
    is gone, so a queue-only predicate reports a correctly-closed ticket as
    abandoned. Measured: the teardown that landed this guard named its own ticket.

    A warning that fires on a normal path gets switched off, and takes the real
    signal with it. So the predicate is "claimed, AND not staged, AND not already
    resolved in the store".
    """
    tmp, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "x", "--slug", "drained",
                            "--backlog", "IMP-0100", "IMP-0101",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK, opened
    wt, wt_branch = opened["path"], opened["branch"]
    (Path(wt) / "notes.txt").write_text("work\n")
    _git(["add", "-A"], wt); _git(["commit", "-qm", "work"], wt)
    assert _run_json(["gate", "--worktree", wt, "--state", state, "--json"])[0] == MODULE.EXIT_OK
    assert _run_json(["cutover", "--worktree", wt, "--state", state,
                      "--commit", "--json"])[0] == MODULE.EXIT_OK

    # IMP-0100 was closed and its queue row consumed; IMP-0101 was simply forgotten.
    store = Path(repo) / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True, exist_ok=True)
    (store / "IMP-0100.json").write_text(json.dumps({"id": "IMP-0100", "status": "fixed"}),
                                         encoding="utf-8")
    (store / "IMP-0101.json").write_text(json.dumps({"id": "IMP-0101", "status": "open"}),
                                         encoding="utf-8")

    rc, payload = _run_json(["resolve", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    assert rc == MODULE.EXIT_OK
    assert payload["claimed_without_closure"] == ["IMP-0101"], (
        f"a ticket already resolved in the store was reported as abandoned: {payload}")


def test_an_unreadable_entry_keeps_the_guard_talking(tmp_path):
    """Fail-OPEN, and the direction is the point.

    `_entry_is_closed` answering False for a file it could not read means the guard
    still speaks up. The opposite default would let a missing or corrupt entry
    silence a real abandoned claim — silence being the failure this guard exists to
    end.
    """
    root = tmp_path / "repo"
    (root / "docs" / "runbook" / "backlog").mkdir(parents=True)
    assert MODULE._entry_is_closed(root, "IMP-9999") is False          # absent
    (root / "docs" / "runbook" / "backlog" / "IMP-8888.json").write_text(
        "{not json", encoding="utf-8")
    assert MODULE._entry_is_closed(root, "IMP-8888") is False          # corrupt
    (root / "docs" / "runbook" / "backlog" / "IMP-7777.json").write_text(
        json.dumps({"id": "IMP-7777", "status": "wont-fix"}), encoding="utf-8")
    assert MODULE._entry_is_closed(root, "IMP-7777") is True           # closed counts


# --- land: the fair queue -------------------------------------------------
#
# The verb's throughput claim is established by measurement, not by unit test:
# ten concurrent worktrees in a throwaway clone went from 2/10 landed (driving
# catchup/gate/cutover by hand, with retries) to 10/10 in exactly 10 gate runs.
# A race cannot be pinned by a passing test. What these DO pin is everything a
# later edit could delete without the measurement noticing — a first pass at
# these tests left the gate-verdict guard, the catchup guard, the ticket release
# and the whole liveness probe deletable with the suite still green.


def _land_stub(name, rc=0, payload=None, boom=None):
    """A stand-in for cmd_catchup / cmd_gate / cmd_cutover.

    It must print its JSON to stdout, because that is the contract `_land_step`
    reads it through; a stub that merely returns a dict would test a code path
    that does not exist.
    """
    def run(_args, _n=name):
        _land_stub.calls.append(_n)
        if boom is not None:
            raise boom
        print(json.dumps(payload if payload is not None else {}))
        return rc
    return run


def _land_harness(monkeypatch, tmp_path, catchup=None, gate=None, cutover=None,
                  ff_ready=None):
    primary = tmp_path / "primary"
    primary.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    _land_stub.calls = []
    monkeypatch.setattr(MODULE, "primary_root", lambda: primary)
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *a, **k: None)
    # The harness primary is a bare directory, not a checkout, so the REAL
    # `_primary_ff_ready` would refuse every lane here on "detached HEAD". Default
    # it to "ready" and let the tests that care inject a refusal; that injection is
    # also what proves `cmd_land` consults this helper rather than a private copy
    # of the same judgement (a duplicated check would ignore the patch).
    # Recording default, not `lambda *a, **k: None`: with a blind stub nothing in the
    # suite ever observes the ARGUMENTS cmd_land passes, so reverting the branch source
    # to `_current_branch` left 22 tests green (review of 233c78039). A stub that
    # swallows its inputs silently un-tests every one of them.
    _land_harness.ff_ready_calls = []

    def _recording_ff_ready(primary, local, branch=None, worktree=None):
        _land_harness.ff_ready_calls.append({"primary": str(primary), "local": local,
                                             "branch": branch, "worktree": worktree})
        return None
    monkeypatch.setattr(MODULE, "_primary_ff_ready",
                        ff_ready if ff_ready is not None else _recording_ff_ready)
    monkeypatch.setattr(MODULE, "cmd_catchup",
                        catchup or _land_stub("catchup", 0, {"ok": True}))
    monkeypatch.setattr(MODULE, "cmd_gate",
                        gate or _land_stub("gate", 0, {"verdict": "pass"}))
    monkeypatch.setattr(MODULE, "cmd_cutover",
                        cutover or _land_stub("cutover", 0,
                                              {"landed": True, "sha": "abc1234"}))
    args = argparse.Namespace(worktree=str(wt), commit=True, json=True,
                              state=str(tmp_path / "registry.json"),
                              base="main", queue_timeout=5.0)
    return primary, args


def _recording_gate_stub(state, worktree):
    """A gate stub that leaves the artefact a real gate run leaves behind.

    `_land_stub.calls` reports whether the FUNCTION was entered; the ticket's
    question is the operator's — did a gate actually run, i.e. is there a verdict on
    disk that cost wall-clock time to produce. Asserting on the record file answers
    it in the currency the real system uses. An absent file is evidence only when
    something was capable of writing it, which is what the clean-primary companion
    test below establishes with the very same stub.
    """
    rec = MODULE._gate_record_path(state, worktree)

    def run(_args):
        _land_stub.calls.append("gate")
        rec.parent.mkdir(parents=True, exist_ok=True)
        rec.write_text(json.dumps({"verdict": "pass"}), encoding="utf-8")
        print(json.dumps({"verdict": "pass"}))
        return 0
    return run


def _queued(primary):
    with MODULE._land_lock(primary):
        return MODULE._land_tickets(MODULE._land_queue_dir(primary))


def test_the_landing_queue_hands_out_turns_in_arrival_order(tmp_path):
    primary = tmp_path
    a, fa = MODULE._land_enqueue(primary, "/wt/a")
    b, fb = MODULE._land_enqueue(primary, "/wt/b")
    c, fc = MODULE._land_enqueue(primary, "/wt/c")
    assert a < b < c
    assert MODULE._land_position(primary, a)[0] == 0
    assert MODULE._land_position(primary, b)[0] == 1
    assert MODULE._land_position(primary, c)[0] == 2
    MODULE._land_release(primary, a, fa)
    assert MODULE._land_position(primary, b)[0] == 0
    assert MODULE._land_position(primary, c)[0] == 1
    MODULE._land_release(primary, b, fb)
    MODULE._land_release(primary, c, fc)


def test_a_ticket_whose_owner_actually_died_stops_holding_the_queue(tmp_path):
    """An owner really dies here.

    The previous version of this test hand-wrote {"pid": 0} and called that a
    dead owner. It was not: it was a CORRUPT ticket, and it left the liveness
    probe itself untested — the whole `os.kill` body could be deleted and this
    test still passed. Liveness is now the kernel's answer to "is the flock
    free", so the honest way to ask is to have a real process take the lock and
    then kill it.
    """
    primary = tmp_path
    qdir = MODULE._land_queue_dir(primary)
    qdir.mkdir(parents=True, exist_ok=True)
    ticket = qdir / f"{1:012d}.json"
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl,os,sys\n"
         "fd=os.open(sys.argv[1], os.O_CREAT|os.O_RDWR, 0o644)\n"
         "fcntl.flock(fd, fcntl.LOCK_EX)\n"
         "os.write(fd, b'{\"pid\": 1, \"worktree\": \"/wt/dead\"}')\n"
         "sys.stdout.write('held'); sys.stdout.flush()\n"
         "import time; time.sleep(120)\n",
         str(ticket)],
        stdout=subprocess.PIPE)
    try:
        assert child.stdout.read(4) == b"held"
        mine, fd = MODULE._land_enqueue(primary, "/wt/mine")
        assert mine > 1, "the dead lane's ticket must sort ahead of ours"
        # ALIVE: the holder is in front of us and stays there.
        assert MODULE._land_position(primary, mine)[0] == 1
        assert ticket.exists()
    finally:
        child.kill()
        child.wait()
    # DEAD: the kernel dropped the flock with the process, so the turn moves.
    assert MODULE._land_position(primary, mine)[0] == 0
    assert not ticket.exists(), "a dead owner's ticket must be evicted, not skipped"
    MODULE._land_release(primary, mine, fd)


def test_a_corrupt_ticket_ahead_of_us_is_evicted_not_stepped_over(tmp_path):
    """Planted AHEAD of ours on purpose: a bad ticket behind us cannot change our
    position, so asserting position 0 with it behind would assert nothing at all.
    """
    primary = tmp_path
    mine, fd = MODULE._land_enqueue(primary, "/wt/mine")
    # planted AFTER we queue, at a LOWER sequence, so it really is in front of us
    # (planting it first is no good: enqueue sweeps it before picking our number,
    # and then the test proves only that enqueue ran).
    bad = MODULE._land_queue_dir(primary) / f"{mine - 1:012d}.json"
    bad.write_text("{not json")
    with MODULE._land_lock(primary):
        seqs_before = sorted(p.stem for p in
                             MODULE._land_queue_dir(primary).glob("*.json"))
    assert len(seqs_before) == 2, "the bad ticket should be sitting ahead of ours"
    assert MODULE._land_position(primary, mine)[0] == 0
    assert not bad.exists()
    MODULE._land_release(primary, mine, fd)


def test_land_refuses_a_blocking_gate_and_never_reaches_cutover(tmp_path, monkeypatch,
                                                                capsys):
    primary, args = _land_harness(
        monkeypatch, tmp_path,
        gate=_land_stub("gate", MODULE.EXIT_BLOCK, {"verdict": "block"}))
    rc = MODULE.cmd_land(args)
    assert rc == MODULE.EXIT_BLOCK
    assert "cutover" not in _land_stub.calls, \
        "a block verdict must not reach cutover"
    assert json.loads(capsys.readouterr().out)["landed"] is False
    assert _queued(primary) == [], "the turn must be released on refusal"


def test_land_refuses_when_catchup_fails_and_never_reaches_the_gate(tmp_path,
                                                                    monkeypatch,
                                                                    capsys):
    primary, args = _land_harness(
        monkeypatch, tmp_path,
        catchup=_land_stub("catchup", MODULE.EXIT_BLOCK, {"error": "conflict"}))
    rc = MODULE.cmd_land(args)
    assert rc == MODULE.EXIT_BLOCK
    assert _land_stub.calls == ["catchup"], \
        f"nothing may run after a failed catchup, ran: {_land_stub.calls}"
    assert json.loads(capsys.readouterr().out)["landed"] is False
    assert _queued(primary) == []


def test_land_releases_its_turn_even_when_a_step_raises(tmp_path, monkeypatch):
    """The failure that wedges every other lane. Without the `finally`, one
    exception parks the queue head until the process exits."""
    primary, args = _land_harness(
        monkeypatch, tmp_path,
        gate=_land_stub("gate", boom=RuntimeError("gate exploded")))
    with pytest.raises(RuntimeError):
        MODULE.cmd_land(args)
    assert _queued(primary) == [], "an exception must not leave the turn held"


def test_land_shouts_when_cutovers_exit_code_and_payload_disagree(tmp_path,
                                                                  monkeypatch,
                                                                  capsys):
    """Reachable when a payload fails to parse: `landed` reads False while the
    trunk has already moved. Reporting a plain refusal there would be a lie."""
    primary, args = _land_harness(
        monkeypatch, tmp_path,
        cutover=_land_stub("cutover", 0, {"no_landed_key": True}))
    rc = MODULE.cmd_land(args)
    assert rc == MODULE.EXIT_BLOCK
    payload = json.loads(capsys.readouterr().out)
    assert payload["landed"] is None
    assert "disagree" in payload["error"]
    assert _queued(primary) == []


def test_land_dry_run_takes_no_turn_and_runs_nothing(tmp_path, monkeypatch, capsys):
    """A dry run that enqueued would make `land --json` — the natural way to ask
    'how deep is the queue' — lengthen the queue it is reporting on."""
    primary, args = _land_harness(monkeypatch, tmp_path)
    args.commit = False
    rc = MODULE.cmd_land(args)
    assert rc == MODULE.EXIT_OK
    assert _land_stub.calls == [], "a dry run must not execute any step"
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry-run" and payload["landed"] is False
    assert _queued(primary) == []


# --- land: the primary-clean pre-check (IMP-20260808-636848) ---------------
#
# Measured 2026-08-08: a batch integrator wrote four backlog closures into the
# primary while a `land` loop was running. The `ui-fixture-lint` gate ran 574
# seconds, and only THEN did cutover reach its pre-ff primary-clean check and
# refuse. The refusal was correct; its POSITION was not. The conflict was created
# by the same operator three seconds before the gate started, so the whole cost was
# avoidable by asking the question first.
#
# What these tests pin is the position, not the judgement: the judgement is
# `_primary_ff_ready`'s and is pinned by the cutover tests above.

def _dirty_primary(reason="primary working tree is dirty (tracked changes)"):
    calls = []

    def ff_ready(primary, local, branch=None, worktree=None):
        calls.append((str(primary), local))
        return (reason, {"dirty_files": ["docs/runbook/backlog/IMP-0023.json"],
                         "broadcast": None})
    ff_ready.calls = calls
    return ff_ready


@gitmark
def test_land_does_not_guess_the_branch_from_a_path_that_is_not_a_worktree(
        tmp_path, monkeypatch, capsys):
    """`cmd_land` only checks that `--worktree` is a directory. `_current_branch` answers
    by asking git from inside that path, and git discovery walks UP — so a directory that
    is merely INSIDE the repo (or a worktree that lost its `.git`) answers with the
    ENCLOSING checkout's branch, i.e. `main`. Feeding that to the coordination notice
    posts "blocked branch: `main`", which is worse than posting nothing: it names an
    innocent branch. `_worktree_entry` reads `git worktree list --porcelain`, which
    cannot invent a membership. Found by review of 233c78039, where the fix shipped with
    nothing able to observe a revert."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for a in (["init", "-q", "-b", "main"], ["-c", "user.email=t@t", "-c", "user.name=t",
                                             "commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    inside = repo / "not-a-worktree"
    inside.mkdir()
    # the trap, demonstrated rather than asserted from memory
    assert MODULE._current_branch(str(inside)) == "main"

    primary, args = _land_harness(monkeypatch, tmp_path)
    args.worktree = str(inside)
    assert MODULE.cmd_land(args) == MODULE.EXIT_OK
    capsys.readouterr()

    assert _land_harness.ff_ready_calls, "the pre-gate primary check must have been asked"
    passed = _land_harness.ff_ready_calls[0]["branch"]
    assert passed != "main", (
        "cmd_land handed the ENCLOSING checkout's branch to the coordination notice")
    assert passed is None


def test_land_refuses_primary_dirty_before_gate_leaving_no_gate_record(
        tmp_path, monkeypatch, capsys):
    """The refusal has to arrive before anything expensive has been spent.

    Two independent witnesses, because each alone is weak: `_land_stub.calls`
    proves the step functions were never entered, and the absent gate record proves
    no verdict was produced. rc alone would prove neither — `land` already exits
    EXIT_BLOCK for a red gate, i.e. the number this refusal shares with the very
    outcome it is supposed to be distinguishable from.
    """
    state, wt = str(tmp_path / "registry.json"), str(tmp_path / "wt")
    rec = MODULE._gate_record_path(state, wt)
    primary, args = _land_harness(
        monkeypatch, tmp_path,
        gate=_recording_gate_stub(state, wt),
        ff_ready=_dirty_primary())

    rc = MODULE.cmd_land(args)

    assert rc == MODULE.EXIT_BLOCK
    assert not rec.exists(), \
        "a gate verdict on disk means a gate ran — the whole cost this check avoids"
    assert _land_stub.calls == [], \
        f"nothing may run once the primary is known dirty, ran: {_land_stub.calls}"
    payload = json.loads(capsys.readouterr().out)
    assert payload["landed"] is False
    assert "dirty" in payload["error"]
    # The refusal must name WHICH files, or the operator is back to guessing which
    # of their own writes is in the way.
    assert payload["dirty_files"] == ["docs/runbook/backlog/IMP-0023.json"]
    assert _queued(primary) == [], "the turn must be released on refusal"


def test_land_precheck_lets_a_clean_primary_through_to_the_gate(
        tmp_path, monkeypatch, capsys):
    """The positive control for the test above.

    Without it, "no gate record was written" is satisfied by a stub that cannot
    write one at all, and by a `cmd_land` that refuses every lane for any reason.
    Same harness, same stub, one field flipped.
    """
    state, wt = str(tmp_path / "registry.json"), str(tmp_path / "wt")
    rec = MODULE._gate_record_path(state, wt)
    primary, args = _land_harness(
        monkeypatch, tmp_path, gate=_recording_gate_stub(state, wt))

    rc = MODULE.cmd_land(args)

    assert rc == MODULE.EXIT_OK
    assert _land_stub.calls == ["catchup", "gate", "cutover"]
    assert rec.exists(), "the stub must be able to write the record it is judged by"
    assert json.loads(capsys.readouterr().out)["landed"] is True
    assert _queued(primary) == []


def test_land_asks_the_primary_dirty_before_gate_question_exactly_once(
        tmp_path, monkeypatch, capsys):
    """`land` owns the CHEAP check; `cutover` owns the load-bearing one.

    The pre-check is not a replacement for cutover's pre-ff check and must not grow
    into one: the primary can be dirtied WHILE the gate runs — 2026-08-08 is exactly
    that story — so the answer this call gets expires. Anyone tempted to treat one of
    the two as redundant should read this test and
    `test_cutover_refused_when_primary_is_dirty`, which pins the other one.
    """
    asked = []

    def ff_ready(primary, local, branch=None, worktree=None):
        asked.append(local)
        return None
    primary, args = _land_harness(monkeypatch, tmp_path, ff_ready=ff_ready)

    assert MODULE.cmd_land(args) == MODULE.EXIT_OK
    capsys.readouterr()
    assert asked == ["main"], (
        "exactly one pre-check, against the LOCAL trunk `land` is heading for; "
        f"got {asked}")


def test_close_wave_does_not_block_on_foreign_active_worktrees(
        tmp_path, monkeypatch, capsys):
    """A Delivery Team may finish while another team still owns worktrees.

    The resolver still receives only this wave's explicit branches; unrelated
    active records are not a reason to make every team communicate manually.
    """
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *args: None)
    monkeypatch.setattr(MODULE, "primary_root", lambda: tmp_path)
    monkeypatch.setattr(MODULE, "_delivery_primary_dirty", lambda _primary: [])
    monkeypatch.setattr(
        MODULE,
        "_delivery_registry_records",
        lambda _args, **_kwargs: (MODULE.EXIT_OK, [
            {"status": "active", "branch": "feat/source", "path": "/wt/source"},
            {"status": "active", "branch": "feat/catalog-agent-tool",
             "path": "/wt/catalog", "intent": "Catalog cutover"},
        ]),
    )
    args = argparse.Namespace(
        state=None,
        json=True,
        base="main",
        slug="delivery-wave",
        branches=["feat/source"],
        commit=False,
        sync=False,
    )

    rc = MODULE.cmd_close_wave(args)

    assert rc == MODULE.EXIT_OK
    output = capsys.readouterr().out
    assert "feat/catalog-agent-tool" not in output
    assert "foreign active" not in output


def test_close_wave_expected_ticket_set_is_derived_only_from_named_sources():
    records = [
        {"status": "active", "branch": "feat/source-a",
         "backlog": ["IMP-0002", "IMP-0001"]},
        {"status": "active", "branch": "feat/source-b",
         "backlog": ["IMP-0003"]},
        {"status": "active", "branch": "feat/foreign",
         "backlog": ["IMP-9999"]},
        {"status": "merged", "branch": "feat/source-a",
         "backlog": ["IMP-8888"]},
    ]

    assert MODULE._delivery_expected_ticket_ids(
        records, ["feat/source-b", "feat/source-a"]
    ) == ["IMP-0001", "IMP-0002", "IMP-0003"]
    records.append({
        "status": "active", "branch": "feat/source-c", "backlog": "IMP-0004",
    })
    assert MODULE._delivery_expected_ticket_reservation_errors(
        records, ["feat/source-c"]
    ) == [{
        "branch": "feat/source-c",
        "reason": "backlog must be a list of non-empty ticket ids",
    }]


def test_close_wave_expected_ticket_closure_requires_fixed_by_and_confirmed_verdict(
        tmp_path):
    store = tmp_path / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True)
    (store / "IMP-0001.json").write_text(json.dumps({
        "id": "IMP-0001", "status": "fixed", "verdict": "CONFIRMED-FIXED",
        "fixed_by": ["abc123"],
    }), encoding="utf-8")
    (store / "IMP-0002.json").write_text(json.dumps({
        "id": "IMP-0002", "status": "fixed", "verdict": "CONFIRMED-FIXED",
        "fixed_by": [],
    }), encoding="utf-8")
    (store / "IMP-0003.json").write_text(json.dumps({
        "id": "IMP-0003", "status": "fixed", "verdict": "CONFIRMED-FIXED",
        "fixed_by": [""],
    }), encoding="utf-8")

    result = MODULE._delivery_expected_ticket_closure(
        tmp_path, ["IMP-0001", "IMP-0002", "IMP-0003", "IMP-0004"]
    )

    assert result["ok"] is False
    assert result["expected_ticket_ids"] == [
        "IMP-0001", "IMP-0002", "IMP-0003", "IMP-0004"
    ]
    assert result["failures"] == [
        {"id": "IMP-0002", "reason": "fixed_by is empty"},
        {"id": "IMP-0003", "reason": "fixed_by contains an empty sha"},
        {"id": "IMP-0004", "reason": "entry is missing or unreadable"},
    ]


def test_independent_no_ticket_default_closure_still_refuses_empty_set(tmp_path):
    """No-ticket closure is opt-in; the ordinary closure predicate stays fail-closed."""
    result = MODULE._delivery_expected_ticket_closure(tmp_path, [])

    assert result == {
        "ok": False,
        "expected_ticket_ids": [],
        "failures": [{"reason": "expected ticket set is empty"}],
    }


def test_independent_no_ticket_parser_and_provenance_are_explicit():
    parser = MODULE.build_parser()
    args = parser.parse_args([
        "close-wave", "--slug", "wave", "--branches", "feat/source",
        "--independent",
    ])
    assert args.independent is True

    provenance = MODULE._delivery_independent_no_ticket_provenance(
        state={
            "independent": True,
            "branch": "feat/integration",
            "gate": {"head_sha": "abc123", "verdict": "warn"},
        },
        manifest={
            "independent": True,
            "branch": "feat/integration",
            "head_sha": "abc123",
        },
        integration_record={
            "branch": "feat/integration",
            "independent": True,
            "intent": "independent-no-ticket: explicit fixture",
        },
        current_head="abc123",
        primary_dirty=[],
        queue=[],
    )
    assert provenance["ok"] is True, provenance
    assert provenance["mode"] == "independent-no-ticket"


@gitmark
def test_independent_no_ticket_integrate_resume_opt_in_is_consistent(scratch, monkeypatch):
    """Every append/continuation hint must preserve the wave's explicit opt-in."""
    tmp_path, repo, _remote = scratch

    ordinary_state = str(tmp_path / "ordinary.json")
    ordinary_sha = _make_branch(repo, "feat/src-ordinary", {"ordinary.txt": "x\n"},
                                "work: ordinary")
    rc, ordinary = _run_integrate_json([
        "integrate", "--slug", "ordinary", "--branches", "feat/src-ordinary",
        "--state", ordinary_state, "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_OK, ordinary
    assert "--independent" not in ordinary["next_step"], ordinary

    late_ordinary = _make_branch(repo, "feat/late-ordinary", {"late.txt": "x\n"},
                                 "work: late ordinary")
    rc, refused = _run_integrate_json([
        "integrate", "--slug", "ordinary", "--append", "--branches",
        "feat/late-ordinary", "--state", ordinary_state, "--independent", "--json",
    ])
    assert rc == MODULE.EXIT_USAGE, refused
    assert refused["persisted_independent"] is False, refused
    assert refused["requested_independent"] is True, refused
    assert ordinary_sha and late_ordinary

    independent_state = str(tmp_path / "independent.json")
    independent_sha = _make_branch(repo, "feat/src-independent", {"independent.txt": "x\n"},
                                    "work: independent")
    rc, independent = _run_integrate_json([
        "integrate", "--slug", "independent", "--branches", "feat/src-independent",
        "--state", independent_state, "--commit", "--no-gate", "--independent", "--json",
    ])
    assert rc == MODULE.EXIT_OK, independent
    assert independent["independent"] is True, independent
    assert independent["next_step"].endswith("--continue --commit --independent"), independent

    rc, existing = _run_integrate_json([
        "integrate", "--slug", "independent", "--branches", "feat/src-independent",
        "--state", independent_state, "--commit", "--independent", "--json",
    ])
    assert rc == MODULE.EXIT_USAGE, existing
    assert "--continue --commit --independent" in existing["error"], existing

    conflict_independent = _make_branch(
        repo, "feat/conflict-independent", {"conflict.txt": "x\n"},
        "work: conflict independent",
    )
    monkeypatch.setattr(MODULE, "_unmerged_paths", lambda _wt: ["conflict.txt"])
    monkeypatch.setattr(MODULE, "_interrupted_operation", lambda _wt: None)
    rc, conflict = _run_integrate_json([
        "integrate", "--slug", "independent", "--append", "--branches",
        "feat/conflict-independent", "--state", independent_state,
        "--independent", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, conflict
    assert conflict["next_step"].endswith("integrate --continue --independent"), conflict
    assert conflict_independent

    drive_independent = _make_branch(
        repo, "feat/drive-independent", {"drive.txt": "x\n"},
        "work: drive independent",
    )
    monkeypatch.setattr(MODULE, "_unmerged_paths", lambda _wt: [])
    state_path = MODULE._integrate_state_path(independent_state, "independent")
    saved = json.loads(state_path.read_text())
    saved["queue"] = [{
        "branch": "feat/drive-independent", "sha": drive_independent,
        "subject": "work: drive independent",
    }]
    saved["planned_total"] = int(saved.get("planned_total") or 0) + 1
    state_path.write_text(json.dumps(saved), encoding="utf-8")
    real_mutation = MODULE._git_mutation

    def fail_pick(argv, *, cwd, label):
        if label.startswith("integrate-cherry-pick:"):
            return 1, "empty-pick fixture"
        return real_mutation(argv, cwd=cwd, label=label)

    monkeypatch.setattr(MODULE, "_git_mutation", fail_pick)
    rc, drive = _run_integrate_json([
        "integrate", "--slug", "independent", "--state", independent_state,
        "--continue", "--commit", "--independent", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, drive
    assert "--continue --commit --independent" in drive["error"], drive
    assert drive_independent
    monkeypatch.setattr(MODULE, "_git_mutation", real_mutation)

    late_independent = _make_branch(repo, "feat/late-independent", {"late-independent.txt": "x\n"},
                                     "work: late independent")
    rc, refused = _run_integrate_json([
        "integrate", "--slug", "independent", "--append", "--branches",
        "feat/late-independent", "--state", independent_state, "--json",
    ])
    assert rc == MODULE.EXIT_USAGE, refused
    assert refused["persisted_independent"] is True, refused
    assert refused["requested_independent"] is False, refused
    assert independent_sha and late_independent

    (Path(repo) / "ops").mkdir()
    bad_sha = _make_branch(repo, "feat/src-independent-bad", {"ops/bad-round.sh": "if then\n"},
                           "work: independent bad")
    blocked_state = str(tmp_path / "blocked-independent.json")
    rc, blocked = _run_integrate_json([
        "integrate", "--slug", "blocked-independent", "--branches",
        "feat/src-independent-bad", "--state", blocked_state, "--commit", "--independent", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, blocked
    assert "--continue --commit --independent" in blocked["next_step"], blocked
    assert bad_sha


@pytest.mark.parametrize("independent, expected_rc", [(False, MODULE.EXIT_BLOCK),
                                                       (True, MODULE.EXIT_OK)])
def test_independent_no_ticket_close_wave_completed_manifest_route(
        tmp_path, monkeypatch, capsys, independent, expected_rc):
    """A resumed completed manifest keeps the ordinary refusal and explicit route."""
    primary = tmp_path / "primary"
    primary.mkdir()
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "slug": "delivery-wave",
        "base": "main",
        "branches": ["feat/source"],
        "worktree": str(tmp_path / "removed-integration"),
        "branch": "feat/integration",
        "status": "gated",
        "independent": independent,
        "close_wave": {
            "status": "completed",
            "expected_ticket_ids": [],
            "independent_provenance": (
                {"ok": True, "mode": "independent-no-ticket"}
                if independent else None
            ),
        },
    }), encoding="utf-8")
    state = tmp_path / "state.json"
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *args: None)
    monkeypatch.setattr(MODULE, "primary_root", lambda: primary)
    monkeypatch.setattr(MODULE, "_delivery_primary_dirty", lambda _primary: [])
    monkeypatch.setattr(
        MODULE, "_delivery_state_paths", lambda _args: (state, [manifest])
    )
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records",
        lambda _args, **_kwargs: (MODULE.EXIT_OK, [{
            "status": "merged", "branch": "feat/source", "backlog": [],
        }]),
    )
    monkeypatch.setattr(
        MODULE, "_delivery_sync_close_wave",
        lambda *_args, **_kwargs: (MODULE.EXIT_OK, None),
    )
    args = argparse.Namespace(
        state=str(state), json=True, base="main", slug="delivery-wave",
        branches=["feat/source"], commit=True, sync=False,
        independent=independent,
    )

    rc = MODULE.cmd_close_wave(args)
    payload = json.loads(capsys.readouterr().out)
    assert rc == expected_rc, payload
    if independent:
        assert payload["mode"] == "already-closed"
        assert payload["steps"][0]["ok"] is True
    else:
        assert payload["steps"][0]["ok"] is False
        assert payload["steps"][0]["failures"] == [
            {"reason": "expected ticket set is empty"}
        ]


@pytest.mark.parametrize("marker_status", ["completed", "validated"])
def test_close_wave_recovery_guard_refuses_open_expected_ticket(
        tmp_path, monkeypatch, capsys, marker_status):
    primary = tmp_path / "primary"
    store = primary / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True)
    ticket_id = "IMP-0001"
    (store / f"{ticket_id}.json").write_text(json.dumps({
        "id": ticket_id, "status": "triaged", "verdict": "CONFIRMED-OPEN",
        "fixed_by": [],
    }), encoding="utf-8")
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "slug": "delivery-wave",
        "base": "main",
        "branches": ["feat/source"],
        "worktree": str(tmp_path / "already-removed"),
        "branch": "feat/integration",
        "status": "gated",
        "close_wave": {
            "status": marker_status,
            "expected_ticket_ids": [ticket_id],
        },
    }), encoding="utf-8")
    state = tmp_path / "state.json"
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *args: None)
    monkeypatch.setattr(MODULE, "primary_root", lambda: primary)
    monkeypatch.setattr(MODULE, "_delivery_primary_dirty", lambda _primary: [])
    monkeypatch.setattr(
        MODULE, "_delivery_state_paths", lambda _args: (state, [manifest])
    )
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records",
        lambda _args, **_kwargs: (MODULE.EXIT_OK, [{
            "status": "merged", "branch": "feat/source", "backlog": [ticket_id],
        }]),
    )
    monkeypatch.setattr(
        MODULE, "_delivery_sync_close_wave",
        lambda *_args, **_kwargs: pytest.fail("recovery must stop before sync"),
    )
    args = argparse.Namespace(
        state=str(state), json=True, base="main", slug="delivery-wave",
        branches=["feat/source"], commit=True, sync=True,
    )

    rc = MODULE._cmd_close_wave_impl(args)

    assert rc == MODULE.EXIT_BLOCK
    payload = json.loads(capsys.readouterr().out)
    assert "not fixed" in payload["error"]
    assert payload["steps"][0]["name"] == "expected-ticket-closure"


def test_delivery_json_tool_rejects_invalid_success_receipt_and_relays_stderr(
        tmp_path, monkeypatch, capsys):
    def fake_runner(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["fake"], returncode=0, stdout="{}\n", stderr="child diagnostic\n"
        )

    monkeypatch.setattr(MODULE, "run_streamed_command", fake_runner)
    rc, payload = MODULE._delivery_json_tool(
        tmp_path / "fake.py", tmp_path, ["probe"], label="receipt-probe",
        expected_schema="expected.v1", required_keys=("records",),
    )

    assert rc == MODULE.EXIT_BLOCK
    assert "invalid success receipt" in payload["error"]
    assert "schema" in payload["contract_errors"][0]
    assert payload["receipt"] == {}
    assert "child diagnostic" in capsys.readouterr().err


def test_delivery_json_tool_rejects_semantically_invalid_success_receipt(
        tmp_path, monkeypatch):
    def fake_runner(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["fake"], returncode=0,
            stdout=json.dumps({"schema": "expected.v1", "mode": "dry-run",
                               "landed": False, "sha": "stale"}),
            stderr="",
        )

    monkeypatch.setattr(MODULE, "run_streamed_command", fake_runner)
    rc, payload = MODULE._delivery_json_tool(
        tmp_path / "fake.py", tmp_path, ["probe"], label="receipt-probe",
        expected_schema="expected.v1", required_keys=("landed",),
        receipt_validator=MODULE._delivery_require_cutover_landed,
    )

    assert rc == MODULE.EXIT_BLOCK
    assert "mode" in payload["contract_errors"][0]
    assert payload["receipt"]["landed"] is False


def test_delivery_registry_records_rejects_malformed_record(
        tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE, "primary_root", lambda: tmp_path)
    monkeypatch.setattr(
        MODULE,
        "_delivery_json_tool",
        lambda *_args, **_kwargs: (MODULE.EXIT_OK, {
            "schema": "kg.worktree.registry.v1",
            "records": [{"path": str(tmp_path), "status": "active"}],
        }),
    )

    rc, records = MODULE._delivery_registry_records(argparse.Namespace(state=None))

    assert rc == MODULE.EXIT_BLOCK
    assert records == []


def test_delivery_registry_records_uses_explicit_primary_after_coordinator_teardown(
        tmp_path, monkeypatch):
    """A close-wave may remove the caller's source worktree mid-command."""
    primary = tmp_path / "primary"
    (primary / "ops").mkdir(parents=True)
    deleted_coordinator = tmp_path / "deleted" / "ops" / "worktree_orchestrate.py"
    seen = {}

    def fake_tool(script, cwd, argv, **_kwargs):
        seen.update(script=Path(script), cwd=Path(cwd), argv=argv)
        return MODULE.EXIT_OK, {"schema": "kg.worktree.registry.v1", "records": []}

    monkeypatch.setattr(MODULE, "__file__", str(deleted_coordinator))
    monkeypatch.setattr(MODULE, "primary_root", lambda: pytest.fail(
        "explicit primary must avoid rediscovering a deleted coordinator cwd"
    ))
    monkeypatch.setattr(MODULE, "_delivery_json_tool", fake_tool)

    rc, records = MODULE._delivery_registry_records(
        argparse.Namespace(state=None), primary=primary
    )

    assert rc == MODULE.EXIT_OK
    assert records == []
    assert seen["script"] == primary / "ops" / "worktree_registry.py"
    assert seen["cwd"] == primary
    assert "--json" in seen["argv"], (
        "registry-list must request the machine-readable receipt explicitly"
    )


def test_delivery_json_tool_large_ledger_is_not_truncated(tmp_path, monkeypatch):
    """A real registry ledger can exceed the old 256 KiB capture ceiling."""
    payload = {
        "schema": "kg.worktree.registry.v1",
        "records": [{"path": f"/tmp/worktree-{index}",
                     "branch": f"feat/source-{index}",
                     "base": "main", "status": "merged",
                     "intent": "x" * 1800} for index in range(150)],
    }
    raw = json.dumps(payload)
    assert len(raw) > 256 * 1024
    seen = {}

    def fake_runner(_command, **kwargs):
        seen.update(kwargs)
        limit = kwargs["capture_limit"]
        return subprocess.CompletedProcess(
            args=["fake"], returncode=0,
            stdout=raw[:limit], stderr="",
        )

    monkeypatch.setattr(MODULE, "run_streamed_command", fake_runner)
    rc, decoded = MODULE._delivery_json_tool(
        tmp_path / "fake.py", tmp_path, ["probe"], label="large-ledger",
        expected_schema="kg.worktree.registry.v1", required_keys=("records",),
    )

    assert seen["capture_limit"] > len(raw)
    assert rc == MODULE.EXIT_OK
    assert decoded == payload


def test_delivery_operation_target_uses_local_main_for_manifest_identity(tmp_path):
    """Manifest SHA is provenance; operational children run against local main."""
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "base": "deadbeef" * 8,
        "close_wave": {"anchor_base_sha": "deadbeef" * 8},
    }), encoding="utf-8")

    assert MODULE._delivery_operation_base(
        "deadbeef" * 8, manifest=MODULE._delivery_load_json(manifest)
    ) == "main"
    state = {
        "schema": MODULE.INTEGRATE_SCHEMA,
        "slug": "delivery-wave",
        "base": "main",
        "branches": ["feat/source"],
        "worktree": str(tmp_path / "removed-worktree"),
        "branch": "feat/integration",
        "status": "gated",
    }
    assert MODULE._delivery_integration_error(
        state,
        label="integration state",
        slug="delivery-wave",
        base=MODULE._delivery_operation_base("deadbeef" * 8,
                                             manifest=MODULE._delivery_load_json(manifest)),
        branches=["feat/source"],
        require_gated=True,
        require_live_worktree=False,
    ) is None


def test_close_wave_expected_ticket_set_includes_staged_queue(tmp_path):
    """Stacked source rows survive source teardown through the anchor queue."""
    queue = tmp_path / ".cache" / "backlog_anchor_queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text("\n".join(json.dumps(row) for row in [
        {"id": "IMP-20260811-5a3b26", "branch": "feat/team-a-de285f",
         "landed_sha": "abc123"},
        {"id": "IMP-20260811-de285f", "branch": "feat/team-a-de285f",
         "landed_sha": None},
        {"id": "IMP-foreign", "branch": "feat/other", "landed_sha": "def456"},
    ]) + "\n", encoding="utf-8")
    records = [{"status": "merged", "branch": "feat/team-a-de285f",
                "backlog": ["IMP-20260811-de285f"]}]

    staged = MODULE._delivery_staged_ticket_ids(tmp_path, ["feat/team-a-de285f"])
    assert staged == ["IMP-20260811-5a3b26", "IMP-20260811-de285f"]
    assert MODULE._delivery_expected_ticket_ids(
        records, ["feat/team-a-de285f"], staged_ids=staged
    ) == ["IMP-20260811-5a3b26", "IMP-20260811-de285f"]


def test_delivery_integration_rejects_foreign_git_checkout(tmp_path, monkeypatch):
    primary = tmp_path / "primary"
    foreign = tmp_path / "foreign"
    for repo in (primary, foreign):
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"],
                       cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base", "--allow-empty"],
                       cwd=repo, check=True)
    subprocess.run(["git", "switch", "-q", "-c", "feat/integration"],
                   cwd=foreign, check=True)
    monkeypatch.setattr(MODULE, "primary_root", lambda: primary)
    payload = {
        "schema": MODULE.INTEGRATE_SCHEMA,
        "slug": "delivery-wave",
        "base": "main",
        "branches": ["feat/source"],
        "worktree": str(foreign),
        "branch": "feat/integration",
        "status": "gated",
    }

    error = MODULE._delivery_integration_error(
        payload,
        label="integration manifest",
        slug="delivery-wave",
        base="main",
        branches=["feat/source"],
        require_gated=True,
        require_live_worktree=True,
    )

    assert error is not None
    assert "not a linked worktree of this repository" in error


def test_delivery_anchor_guard_checks_primary_branch_inside_advance_lock(
        tmp_path, monkeypatch):
    @contextmanager
    def fake_lock(_primary):
        yield

    monkeypatch.setattr(MODULE, "_main_advance_lock", fake_lock)
    monkeypatch.setattr(
        MODULE, "_primary_ff_ready",
        lambda *_args, **_kwargs: ("primary is on the wrong branch", {}),
    )
    monkeypatch.setattr(
        MODULE, "_delivery_primary_dirty",
        lambda _primary: pytest.fail("dirty check must not run after branch refusal"),
    )
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records",
        lambda _args, **_kwargs: pytest.fail(
            "registry must not run after branch refusal"
        ),
    )

    rc, steps = MODULE._delivery_anchor_and_commit(
        argparse.Namespace(base="main"), tmp_path, set(), "delivery-wave", None
    )

    assert rc == MODULE.EXIT_BLOCK
    assert steps[0]["name"] == "anchor-guard"
    assert "wrong branch" in steps[0]["error"]


def test_delivery_anchor_noop_marker_empty_queue_is_explicit_noop_and_replayable(
        tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=repo, check=True)
    backlog = repo / "docs" / "runbook" / "backlog"
    backlog.mkdir(parents=True)
    (backlog / "README").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)

    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "close_wave": {"expected_ticket_ids": []},
    }), encoding="utf-8")

    @contextmanager
    def fake_lock(_primary):
        yield

    calls = 0

    def fake_anchor(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return MODULE.EXIT_OK, {
            "schema": "kg.backlog.anchor.v1",
            "mode": "commit",
            "applied": [],
            "problems": [],
            "unstamped": [],
        }

    monkeypatch.setattr(MODULE, "_main_advance_lock", fake_lock)
    monkeypatch.setattr(MODULE, "_primary_ff_ready", lambda *_a, **_k: None)
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records", lambda *_a, **_k: (0, [])
    )
    monkeypatch.setattr(MODULE, "_delivery_json_tool", fake_anchor)
    args = argparse.Namespace(base="main", state=None)

    for _ in range(2):
        rc, steps = MODULE._delivery_anchor_and_commit(
            args, repo, set(), "delivery-wave", manifest
        )
        assert rc == MODULE.EXIT_OK
        anchor_commit = next(
            step["payload"] for step in steps if step.get("name") == "anchor-commit"
        )
        assert anchor_commit["committed"] is False
        assert anchor_commit["noop"] is True
        marker = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
        assert marker["anchor_noop"] is True
        assert marker["anchor_committed"] is False
        assert "anchor_commit_sha" not in marker
        assert marker["phases"]["anchor"]["status"] == "completed"
        assert marker["phases"]["anchor"]["queue_state"] == "consumed"

    assert calls == 2
    assert not subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout


def test_anchor_noop_recovery_after_metadata_commit(tmp_path, monkeypatch):
    """A durable noop may resume after a legal backlog metadata-only advance."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=repo, check=True)
    (repo / ".git" / "info" / "exclude").write_text(".cache/\n", encoding="utf-8")
    ticket_id = "IMP-20260812-noop-recovery"
    ticket = repo / "docs" / "runbook" / "backlog" / f"{ticket_id}.json"
    ticket.parent.mkdir(parents=True)
    ticket.write_text('{"status":"triaged"}\n', encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    queue = repo / MODULE.ANCHOR_QUEUE
    queue.parent.mkdir(parents=True)
    queue.write_text("", encoding="utf-8")
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "close_wave": {
            "expected_ticket_ids": [ticket_id],
            "anchor_base_sha": base_sha,
            "anchor_ids": [],
            "anchor_committed": False,
            "anchor_noop": True,
            "phases": {"anchor": {
                "status": "completed",
                "operation_base": base_sha,
                "landed_sha": base_sha,
                "expected_ticket_ids": [ticket_id],
                "applied_ticket_ids": [],
                "acceptance_receipt": {
                    "schema": "kg.backlog.anchor.v1",
                    "mode": "commit",
                    "applied": [],
                    "problems": [],
                },
                "queue_state": "consumed",
            }},
            "last_successful_phase": "anchor",
        },
    }), encoding="utf-8"),

    # This is the legal primary-side verify/groom advance that happened after
    # the noop marker was persisted: only the expected backlog document moves.
    ticket.write_text('{"status":"fixed","fixed_by":"metadata"}\n', encoding="utf-8")
    subprocess.run(["git", "add", str(ticket)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "ops: verify metadata"], cwd=repo,
                   check=True)
    current_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    assert current_sha != base_sha
    assert subprocess.run(
        ["git", "diff", "--name-only", base_sha, current_sha], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout.splitlines() == [f"docs/runbook/backlog/{ticket_id}.json"]

    @contextmanager
    def fake_lock(_primary):
        yield

    def fake_anchor(*_args, **_kwargs):
        return MODULE.EXIT_OK, {
            "schema": "kg.backlog.anchor.v1",
            "mode": "commit",
            "applied": [],
            "problems": [],
            "unstamped": [],
        }

    monkeypatch.setattr(MODULE, "_main_advance_lock", fake_lock)
    monkeypatch.setattr(MODULE, "_primary_ff_ready", lambda *_a, **_k: None)
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records", lambda *_a, **_k: (0, [])
    )
    monkeypatch.setattr(MODULE, "_delivery_json_tool", fake_anchor)

    rc, steps = MODULE._delivery_anchor_and_commit(
        argparse.Namespace(base="main", state=None), repo, set(),
        "delivery-wave", manifest,
    )
    assert rc == MODULE.EXIT_OK
    anchor_commit = next(
        step["payload"] for step in steps if step.get("name") == "anchor-commit"
    )
    assert anchor_commit["committed"] is False
    assert anchor_commit["noop"] is True
    marker = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
    assert marker["anchor_noop"] is True
    assert marker["anchor_committed"] is False
    assert "anchor_commit_sha" not in marker
    assert marker["anchor_base_sha"] == current_sha
    assert not subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo,
        check=True, capture_output=True, text=True,
    ).stdout


def _git_repo_with_anchor_ticket(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / ".git" / "info" / "exclude").write_text(".cache/\n", encoding="utf-8")
    ticket = repo / "docs" / "runbook" / "backlog" / "IMP-20260809-crash.json"
    ticket.parent.mkdir(parents=True)
    ticket.write_text("open\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                              check=True, capture_output=True, text=True).stdout.strip()
    ticket.write_text("closed\n", encoding="utf-8")
    return repo, base_sha


def test_delivery_anchor_recovers_commit_when_marker_write_crashes(tmp_path):
    repo, base_sha = _git_repo_with_anchor_ticket(tmp_path)
    ticket_id = "IMP-20260809-crash"

    rc, first = MODULE._delivery_anchor_commit(
        repo, applied_ids=[ticket_id], anchor_base_sha=base_sha
    )
    assert rc == MODULE.EXIT_OK
    assert first["committed"] is True

    rc, recovered = MODULE._delivery_anchor_commit(
        repo, applied_ids=[ticket_id], anchor_base_sha=base_sha
    )

    assert rc == MODULE.EXIT_OK
    assert recovered["already_committed"] is True
    assert recovered["recovered"] is True
    assert recovered["sha"] == first["sha"]


def test_delivery_anchor_replays_manifest_after_post_commit_marker_failure(
        tmp_path, monkeypatch):
    repo, _base_sha = _git_repo_with_anchor_ticket(tmp_path)
    (repo / "docs" / "runbook" / "backlog" / "IMP-20260809-crash.json").write_text(
        "open\n", encoding="utf-8"
    )
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({"schema": MODULE.INTEGRATE_SCHEMA,
                                    "close_wave": {}}), encoding="utf-8")
    ticket_id = "IMP-20260809-crash"
    calls = 0
    child_calls = 0

    @contextmanager
    def fake_lock(_primary):
        yield

    def fake_child(*_args, **_kwargs):
        nonlocal child_calls
        child_calls += 1
        if child_calls == 1:
            (repo / "docs" / "runbook" / "backlog" / f"{ticket_id}.json").write_text(
                "closed-by-anchor\n", encoding="utf-8"
            )
            return MODULE.EXIT_OK, {
                "schema": "kg.backlog.anchor.v1", "mode": "commit",
                "applied": [ticket_id], "problems": [], "unstamped": [],
            }
        return MODULE.EXIT_OK, {
            "schema": "kg.backlog.anchor.v1", "mode": "commit",
            "applied": [], "problems": [], "unstamped": [],
        }

    real_save = MODULE._integrate_save

    def crash_after_commit(path, payload):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated crash after anchor commit")
        return real_save(path, payload)

    monkeypatch.setattr(MODULE, "_main_advance_lock", fake_lock)
    monkeypatch.setattr(MODULE, "_primary_ff_ready", lambda *_a, **_k: None)
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records", lambda _args, **_kwargs: (0, [])
    )
    monkeypatch.setattr(MODULE, "_delivery_json_tool", fake_child)
    monkeypatch.setattr(MODULE, "_integrate_save", crash_after_commit)
    args = argparse.Namespace(base="main")

    first_rc, first_steps = MODULE._delivery_anchor_and_commit(
        args, repo, set(), "delivery-wave", manifest
    )
    assert first_rc == MODULE.EXIT_BLOCK
    assert any(step.get("name") == "anchor-commit" and step.get("rc") == 0
               for step in first_steps)
    marker_after_crash = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
    assert marker_after_crash["anchor_committed"] is False

    second_rc, second_steps = MODULE._delivery_anchor_and_commit(
        args, repo, set(), "delivery-wave", manifest
    )

    assert second_rc == MODULE.EXIT_OK
    assert any(step.get("payload", {}).get("recovered") is True
               for step in second_steps if step.get("name") == "anchor-commit")
    final_marker = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
    assert final_marker["anchor_committed"] is True
    assert final_marker["anchor_commit_sha"]


def test_close_wave_recovery_phase_ledger_is_durable_and_monotonic(tmp_path):
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "slug": "delivery-wave",
        "close_wave": {"expected_ticket_ids": ["IMP-0001"]},
    }), encoding="utf-8")

    started = MODULE._delivery_record_phase(
        manifest, "anchor", status="started", operation_base="base-sha",
        landed_sha="landed-sha", expected_ticket_ids=["IMP-0001"],
        applied_ticket_ids=[], acceptance_receipt={"rc": None},
    )
    assert started["phases"]["anchor"]["status"] == "started"
    assert started["last_successful_phase"] is None

    completed = MODULE._delivery_record_phase(
        manifest, "anchor", status="completed", operation_base="base-sha",
        landed_sha="landed-sha", expected_ticket_ids=["IMP-0001"],
        applied_ticket_ids=["IMP-0001"], acceptance_receipt={"rc": 0},
        anchor_commit="anchor-sha",
    )
    replay = MODULE._delivery_record_phase(
        manifest, "anchor", status="started", operation_base="other-base",
        landed_sha="other-sha", expected_ticket_ids=["IMP-0001"],
        applied_ticket_ids=[], acceptance_receipt={"rc": None},
    )

    assert completed["phases"]["anchor"]["status"] == "completed"
    assert completed["phases"]["anchor"]["anchor_commit"] == "anchor-sha"
    assert replay == completed
    assert json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]["last_successful_phase"] == "anchor"


def test_close_wave_phase_completion_never_regresses_or_reorders(tmp_path):
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({"close_wave": {}}), encoding="utf-8")

    MODULE._delivery_record_phase(
        manifest, "cutover", status="completed", operation_base="base",
        landed_sha="cutover-sha",
    )
    completed = MODULE._delivery_record_phase(
        manifest, "anchor", status="completed", operation_base="base",
        landed_sha="anchor-sha",
    )
    replay = MODULE._delivery_record_phase(
        manifest, "cutover", status="started", operation_base="other",
        landed_sha="other",
    )

    assert replay["phases"]["cutover"]["status"] == "completed"
    assert replay["phases"]["cutover"]["operation_base"] == "base"
    assert replay["last_successful_phase"] == "anchor"
    assert completed["last_successful_phase"] == "anchor"


def test_close_wave_anchor_recovery_allows_primary_advance_only_with_pending_queue(
        tmp_path):
    queue = tmp_path / ".cache" / "backlog_anchor_queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text(json.dumps({
        "id": "IMP-0001", "branch": "feat/source", "landed_sha": "landed",
    }) + "\n", encoding="utf-8")
    marker = {
        "expected_ticket_ids": ["IMP-0001"], "anchor_ids": [],
        "phases": {"anchor": {
            "status": "started", "expected_ticket_ids": ["IMP-0001"],
            "applied_ticket_ids": [],
        }},
    }
    assert MODULE._delivery_anchor_recovery_is_safe(tmp_path, marker)

    queue.write_text("", encoding="utf-8")
    assert not MODULE._delivery_anchor_recovery_is_safe(tmp_path, marker)


@pytest.mark.parametrize("malformed_field", ["expected", "phase"])
def test_close_wave_recovery_rejects_malformed_persisted_ticket_ids(
        tmp_path, monkeypatch, malformed_field):
    repo, base_sha = _git_repo_with_anchor_ticket(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "primary advance"], cwd=repo,
                   check=True)
    ticket_id = "IMP-20260809-crash"
    expected_ids = [123] if malformed_field == "expected" else [ticket_id]
    phase_ids = [123] if malformed_field == "phase" else []
    manifest = tmp_path / "completed.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA,
        "close_wave": {
            "anchor_base_sha": base_sha,
            "anchor_ids": [],
            "expected_ticket_ids": expected_ids,
            "phases": {"anchor": {
                "status": "started",
                "expected_ticket_ids": [ticket_id],
                "applied_ticket_ids": phase_ids,
            }},
        },
    }), encoding="utf-8")

    @contextmanager
    def fake_lock(_primary):
        yield

    monkeypatch.setattr(MODULE, "_main_advance_lock", fake_lock)
    monkeypatch.setattr(MODULE, "_primary_ff_ready", lambda *_a, **_k: None)
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records", lambda _args, **_kwargs: (0, [])
    )

    rc, steps = MODULE._delivery_anchor_and_commit(
        argparse.Namespace(base="main", state=None), repo, set(),
        "delivery-wave", manifest,
    )

    assert rc == MODULE.EXIT_BLOCK
    assert any(
        step.get("name") == "anchor-guard"
        and "malformed recovery ticket ids" in step.get("error", "")
        for step in steps
    )


@pytest.mark.parametrize(
    "failure_phase",
    ["cutover", "resolve-source", "anchor", "validate",
     "resolve-integration", "sync"],
)
def test_close_wave_recovery_resumes_each_phase_and_is_idempotent(
        tmp_path, monkeypatch, capsys, failure_phase):
    """One injected boundary failure must be recoverable without duplicate work."""
    repo = tmp_path / "primary"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    ops = repo / "ops"
    ops.mkdir()
    (ops / "worktree_orchestrate.py").write_text("# fixture\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".cache/\n", encoding="utf-8")
    store = repo / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True)
    ticket_id = "IMP-20260811-recovery"
    ticket_path = store / f"{ticket_id}.json"
    ticket_path.write_text(json.dumps({
        "id": ticket_id, "status": "staged", "verdict": "CONFIRMED-FIXED",
        "fixed_by": [],
    }) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
    ).strip()
    subprocess.run(["git", "checkout", "-qb", "feat/integration"], cwd=repo, check=True)
    (repo / "integration.txt").write_text("integration\n", encoding="utf-8")
    subprocess.run(["git", "add", "integration.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "integration"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "feat/source", base_sha], cwd=repo, check=True)

    source_path = tmp_path / "source"
    source_path.mkdir()
    integration_path = tmp_path / "integration"
    integration_path.mkdir()
    queue = repo / ".cache" / "backlog_anchor_queue.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text(json.dumps({
        "id": ticket_id, "branch": "feat/source", "landed_sha": base_sha,
        "status": "staged", "verdict": "CONFIRMED-FIXED", "by": "fixture",
        "evidence": "fixture", "kind": "closure",
    }) + "\n", encoding="utf-8")

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    manifest = manifest_dir / "delivery-wave.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA, "slug": "delivery-wave",
        "base": "main", "branches": ["feat/source"],
        "worktree": str(integration_path), "branch": "feat/integration",
        "status": "gated", "gate": {"verdict": "pass"},
        "close_wave": {"status": "gated", "expected_ticket_ids": [ticket_id]},
    }), encoding="utf-8")
    state = tmp_path / "state.json"
    records = [
        {"status": "active", "branch": "feat/source", "path": str(source_path),
         "base": "main", "backlog": [ticket_id]},
        {"status": "active", "branch": "feat/integration", "path": str(integration_path),
         "base": "main", "backlog": []},
    ]
    calls = {phase: 0 for phase in (
        "cutover", "resolve-source", "anchor", "validate",
        "resolve-integration", "sync",
    )}

    monkeypatch.setattr(MODULE, "primary_root", lambda: repo)
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *_args: None)
    monkeypatch.setattr(MODULE, "_delivery_state_paths", lambda _args: (state, [manifest]))
    monkeypatch.setattr(MODULE, "_delivery_integration_error", lambda *_a, **_k: None)
    monkeypatch.setattr(
        MODULE, "_delivery_registry_records",
        lambda _args, **_kwargs: (MODULE.EXIT_OK, records),
    )

    def fake_tool(_script, _cwd, argv, *, label, **_kwargs):
        phase = next((name for name in calls if label.startswith(f"{name}:")), None)
        if phase is not None:
            calls[phase] += 1
            if phase == failure_phase and calls[phase] == 1:
                if phase == "anchor":
                    ticket_path.write_text(json.dumps({
                        "id": ticket_id, "status": "fixed",
                        "verdict": "CONFIRMED-FIXED",
                        "fixed_by": ["partial-anchor"],
                    }) + "\n", encoding="utf-8")
                    queue.write_text("", encoding="utf-8")
                return MODULE.EXIT_BLOCK, {"error": f"injected {phase} failure"}
        if phase == "cutover":
            subprocess.run(["git", "branch", "-f", "feat/integration", "HEAD"],
                           cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
            ).strip()
            return MODULE.EXIT_OK, {
                "schema": MODULE.SCHEMA, "mode": "committed", "landed": True,
                "sha": head,
            }
        if phase == "resolve-source":
            records[0]["status"] = "merged"
            return MODULE.EXIT_OK, {
                "schema": MODULE.SCHEMA, "mode": "committed",
                "resolved": "merged", "failures": 0,
            }
        if phase == "anchor":
            ticket_path.write_text(json.dumps({
                "id": ticket_id, "status": "fixed", "verdict": "CONFIRMED-FIXED",
                "fixed_by": ["fixture-anchor"],
            }) + "\n", encoding="utf-8")
            queue.write_text("", encoding="utf-8")
            return MODULE.EXIT_OK, {
                "schema": "kg.backlog.anchor.v1", "mode": "commit",
                "applied": [ticket_id], "problems": [], "unstamped": [],
            }
        if phase == "validate":
            return MODULE.EXIT_OK, {
                "schema": "kg.backlog.validate.v1", "ok": True, "problems": [],
            }
        if phase == "resolve-integration":
            records[1]["status"] = "merged"
            return MODULE.EXIT_OK, {
                "schema": MODULE.SCHEMA, "mode": "committed",
                "resolved": "merged", "failures": 0,
            }
        if phase == "sync":
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
            ).strip()
            return MODULE.EXIT_OK, {
                "schema": MODULE.SCHEMA, "step": "sync", "verdict": "noop",
                "to": head,
            }
        pytest.fail(f"unexpected tool label={label!r} argv={argv!r}")

    monkeypatch.setattr(MODULE, "_delivery_json_tool", fake_tool)
    args = argparse.Namespace(
        state=str(state), json=True, base="main", slug="delivery-wave",
        branches=["feat/source"], commit=True, sync=True,
    )

    first_rc = MODULE.cmd_close_wave(args)
    first_payload = json.loads(capsys.readouterr().out)
    assert first_rc == MODULE.EXIT_BLOCK
    assert first_payload.get("steps"), first_payload
    assert calls[failure_phase] == 1

    second_rc = MODULE.cmd_close_wave(args)
    second_payload = json.loads(capsys.readouterr().out)
    assert second_rc == MODULE.EXIT_OK, second_payload
    assert calls[failure_phase] == 2
    final_marker = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
    assert final_marker["last_successful_phase"] == "sync"
    assert all(final_marker["phases"][phase]["status"] == "completed"
               for phase in calls)
    assert MODULE._read_anchor_queue(repo) == []
    assert records[1]["status"] == "merged"
    anchor_commits = subprocess.check_output(
        ["git", "log", "--format=%s", "--all"], cwd=repo, text=True,
    ).splitlines().count(MODULE._DELIVERY_ANCHOR_SUBJECT)
    assert anchor_commits == 1

    before_queue = queue.read_bytes() if queue.exists() else b""
    before_log = subprocess.check_output(
        ["git", "rev-list", "--all"], cwd=repo, text=True,
    )
    third_rc = MODULE.cmd_close_wave(args)
    third_payload = json.loads(capsys.readouterr().out)
    assert third_rc == MODULE.EXIT_OK, third_payload
    assert calls[failure_phase] == 2
    assert (queue.read_bytes() if queue.exists() else b"") == before_queue
    assert subprocess.check_output(
        ["git", "rev-list", "--all"], cwd=repo, text=True,
    ) == before_log


@pytest.mark.parametrize(
    "failure_phase",
    ["cutover", "resolve-source", "anchor", "validate",
     "resolve-integration", "sync"],
)
@gitmark
def test_close_wave_recovery_real_subprocess_wiring(
        tmp_path, monkeypatch, capsys, failure_phase):
    """Exercise close-wave against real git, registry, backlog and sync commands."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "fixture@example.test"], repo)
    _git(["config", "user.name", "recovery fixture"], repo)
    shutil.copytree(
        ROOT / "ops", repo / "ops",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (repo / ".gitignore").write_text(".cache/\n__pycache__/\n", encoding="utf-8")
    store = repo / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True)
    ticket_id = "IMP-20260811-real-recovery"
    (store / f"{ticket_id}.json").write_text(json.dumps({
        "schema": "kg.backlog.entry.v1", "id": ticket_id, "status": "open",
        "stream": "IMP", "severity": "med", "category": "tool",
        "date": "2026-08-11", "source": "fixture",
        "detail": "real close-wave recovery fixture",
        "brief": "recover a close-wave without duplicate side effects",
        "scope": "ops orchestration only", "plan": "exercise every phase",
        "acceptance": "the real fixture command exits zero",
        "fix_site": "ops/worktree_orchestrate.py",
        "acceptance_cmd": "true", "acceptance_expect_rc": 0,
        "resolution": "", "fixed_by": [],
        "groomed_at": "2026-08-11", "groomed_by": "fixture",
    }, indent=2) + "\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "fixture base"], repo)
    base_sha = _git(["rev-parse", "main"], repo)

    source = tmp_path / "source"
    _git(["worktree", "add", "-q", "-b", "feat/source", str(source), "main"], repo)
    (source / "source.txt").write_text("source\n", encoding="utf-8")
    _git(["add", "source.txt"], source)
    _git(["commit", "-qm", "fixture source"], source)
    source_tip = _git(["rev-parse", "HEAD"], source)
    integration = tmp_path / "integration"
    _git(["worktree", "add", "-q", "-b", "feat/integration", str(integration),
          "feat/source"], repo)
    (integration / "integration.txt").write_text("integration\n", encoding="utf-8")
    _git(["add", "integration.txt"], integration)
    _git(["commit", "-qm", "fixture integration"], integration)
    integration_tip = _git(["rev-parse", "HEAD"], integration)

    remote = tmp_path / "origin.git"
    _git(["init", "-q", "--bare", str(remote)], repo)
    _git(["remote", "add", "origin", str(remote)], repo)
    _git(["push", "-q", "origin", "main"], repo)

    state = repo / ".cache" / "worktree_registry.json"
    state.parent.mkdir(parents=True, exist_ok=True)

    def registry(*argv):
        proc = subprocess.run(
            [sys.executable, str(repo / "ops" / "worktree_registry.py"), *argv,
             "--state", str(state), "--json"],
            cwd=repo, capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return json.loads(proc.stdout)

    registry("register", "--path", str(source), "--branch", "feat/source",
             "--intent", "real recovery source", "--base", "main",
             "--backlog", ticket_id)
    registry("register", "--path", str(integration), "--branch", "feat/integration",
             "--intent", "real recovery integration", "--base", "main")
    ledger = json.loads(state.read_text(encoding="utf-8"))
    for record in ledger["records"]:
        record["base_sha"] = base_sha
        record["handed_back_sha"] = (
            source_tip if record["branch"] == "feat/source" else integration_tip
        )
        record["handed_back_at"] = "2026-08-11T00:00:00Z"
    state.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")

    queue = repo / ".cache" / "backlog_anchor_queue.jsonl"
    queue.write_text(json.dumps({
        "id": ticket_id, "branch": "feat/integration", "landed_sha": None,
        "status": "fixed", "verdict": "CONFIRMED-FIXED", "by": "fixture",
        "evidence": "real recovery fixture", "kind": "closure",
    }) + "\n", encoding="utf-8")

    slug = "real-recovery"
    manifest_dir = repo / ".cache" / "worktree_integrations" / "completed"
    manifest_dir.mkdir(parents=True)
    manifest = manifest_dir / f"{slug}-{integration_tip}.json"
    manifest.write_text(json.dumps({
        "schema": MODULE.INTEGRATE_SCHEMA, "slug": slug, "base": "main",
        "branches": ["feat/source"], "worktree": str(integration),
        "branch": "feat/integration", "status": "gated",
        "gate": {"verdict": "pass", "head_sha": integration_tip},
        "close_wave": {"status": "gated", "expected_ticket_ids": [ticket_id]},
    }, indent=2) + "\n", encoding="utf-8")
    gate_path = MODULE._gate_record_path(str(state), str(integration))
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(json.dumps({
        "schema": MODULE.GATE_SCHEMA, "step": "gate", "worktree": str(integration),
        "base": "main", "head_sha": integration_tip, "verdict": "pass",
        "gates": [], "orchestrator": MODULE._orchestrator_identity(str(integration)),
    }, indent=2) + "\n", encoding="utf-8")

    calls = {phase: 0 for phase in (
        "cutover", "resolve-source", "anchor", "validate",
        "resolve-integration", "sync",
    )}
    real_tool = MODULE._delivery_json_tool

    def injected_tool(script, cwd, argv, *, label, **kwargs):
        phase = next((name for name in calls if label.startswith(f"{name}:")), None)
        if phase is None:
            return real_tool(script, cwd, argv, label=label, **kwargs)
        calls[phase] += 1
        if phase == failure_phase and calls[phase] == 1 and phase != "anchor":
            return MODULE.EXIT_BLOCK, {"error": f"injected {phase} boundary failure"}
        rc, payload = real_tool(script, cwd, argv, label=label, **kwargs)
        if phase == failure_phase and calls[phase] == 1 and phase == "anchor":
            # The real anchor has already written every ticket and drained the queue;
            # returning BLOCK models a process death before the coordinator persisted
            # its receipt, which is the dangerous partial-anchor window.
            return MODULE.EXIT_BLOCK, {**payload, "error": "injected post-anchor crash"}
        return rc, payload

    monkeypatch.setattr(MODULE, "_delivery_json_tool", injected_tool)
    args = argparse.Namespace(
        state=str(state), json=True, base="main", slug=slug,
        branches=["feat/source"], commit=True, sync=True,
    )
    previous_cwd = Path.cwd()
    os.chdir(repo)
    try:
        first_rc = MODULE.cmd_close_wave(args)
        first_payload = json.loads(capsys.readouterr().out)
        assert first_rc == MODULE.EXIT_BLOCK, first_payload
        second_rc = MODULE.cmd_close_wave(args)
        second_payload = json.loads(capsys.readouterr().out)
        assert second_rc == MODULE.EXIT_OK, second_payload
        assert calls[failure_phase] == 2
        final_marker = json.loads(manifest.read_text(encoding="utf-8"))["close_wave"]
        assert final_marker["last_successful_phase"] == "sync"
        assert all(final_marker["phases"][phase]["status"] == "completed"
                   for phase in calls)
        assert MODULE._read_anchor_queue(repo) == []
        assert not source.exists() and not integration.exists()
        ledger_after = json.loads(state.read_text(encoding="utf-8"))
        assert all(r["status"] == "merged" for r in ledger_after["records"])
        anchor_commits = subprocess.check_output(
            ["git", "log", "--format=%s", "--all"], cwd=repo, text=True,
        ).splitlines().count(MODULE._DELIVERY_ANCHOR_SUBJECT)
        assert anchor_commits == 1
        before_refs = _git(["rev-list", "--all"], repo)
        before_queue = queue.read_bytes() if queue.exists() else b""
        third_rc = MODULE.cmd_close_wave(args)
        third_payload = json.loads(capsys.readouterr().out)
        assert third_rc == MODULE.EXIT_OK, third_payload
        assert calls[failure_phase] == 2
        assert _git(["rev-list", "--all"], repo) == before_refs
        assert (queue.read_bytes() if queue.exists() else b"") == before_queue
    finally:
        os.chdir(previous_cwd)


def test_delivery_anchor_commit_refuses_staged_or_unstaged_foreign_paths(
        tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo,
                   check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    backlog = repo / "docs" / "runbook" / "backlog"
    backlog.mkdir(parents=True)
    ticket = backlog / "IMP-20260809-anchor.json"
    ticket.write_text("closed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    ticket.write_text("closed-again\n", encoding="utf-8")
    (repo / "foreign.txt").write_text("must stay\n", encoding="utf-8")

    rc, payload = MODULE._delivery_anchor_commit(
        repo, applied_ids=["IMP-20260809-anchor"]
    )

    assert rc == MODULE.EXIT_BLOCK
    assert payload["outside_paths"] == ["foreign.txt"]
    assert payload["missing_paths"] == []
    assert subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=repo,
                          check=True, capture_output=True, text=True).stdout == ""


def test_close_wave_refuses_malformed_persisted_state_before_registry(
        tmp_path, monkeypatch, capsys):
    state = tmp_path / "registry.json"
    integration_state = state.parent / "worktree_integrations" / "delivery-wave.json"
    integration_state.parent.mkdir(parents=True, exist_ok=True)
    integration_state.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(MODULE, "_freeze_guard", lambda *args: None)
    monkeypatch.setattr(MODULE, "primary_root", lambda: tmp_path)
    monkeypatch.setattr(MODULE, "_delivery_primary_dirty", lambda _primary: [])
    args = argparse.Namespace(
        state=str(state), json=True, base="main", slug="delivery-wave",
        branches=["feat/source"], commit=True,
    )

    rc = MODULE.cmd_close_wave(args)

    assert rc == MODULE.EXIT_BLOCK
    payload = json.loads(capsys.readouterr().out)
    assert "unreadable or malformed" in payload["error"]


# --------------------------------------------------------------------------
# claim preconditions: a ticket has to be workable before it can be taken
#
# `--backlog` used to be a pure shape check (`worktree_registry._normalise_tickets`
# deliberately does not depend on backlog.py). That is right for the registry and
# wrong for the orchestrator, which knows where the store is: measured, `open
# --backlog IMP-typo` claimed a ticket that does not exist, and `open --backlog
# <ungroomed>` handed an agent a ticket with no plan, no acceptance and no fix site
# — which is the whole thing grooming exists to prevent. Both succeeded silently.
# --------------------------------------------------------------------------

def _ticket(tmp_path, entry_id, **fields):
    store = tmp_path / "docs" / "runbook" / "backlog"
    store.mkdir(parents=True, exist_ok=True)
    payload = {"schema": "kg.backlog.entry.v1", "id": entry_id, "status": "open",
               "stream": "IMP", "severity": "med", "category": "tool",
               "date": "2026-08-08", "source": "probe", "detail": "something"}
    payload.update(fields)
    (store / f"{entry_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    return store


GROOMED = {"plan": "do the thing", "acceptance": "red then green",
           "fix_site": "ops/x.py:1", "groomed_at": "2026-08-08",
           "groomed_by": "probe", "acceptance_cmd": "true",
           "acceptance_expect_rc": 0}


def test_a_groomed_open_ticket_is_claimable(tmp_path):
    store = _ticket(tmp_path, "IMP-20260808-aaaaaa", **GROOMED)
    assert MODULE._unclaimable(store, ["IMP-20260808-aaaaaa"]) == []


def test_claim_preflight_registry_probe_failure_is_fail_closed(tmp_path, monkeypatch):
    store = _ticket(tmp_path, "IMP-20260811-probe-fail", **GROOMED)

    def unreadable(_repo, **_kwargs):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(MODULE, "_active_worktree_files", unreadable)
    problems = MODULE._unclaimable(store, ["IMP-20260811-probe-fail"])
    assert [problem["kind"] for problem in problems] == ["preflight-read-failed"]


def test_pre_dispatch_refuses_missing_contract_evidence(tmp_path):
    """The claim boundary and backlog dispatch use the same contract guard."""
    store = _ticket(tmp_path, "IMP-20260810-contract", **{
        **GROOMED,
        "groomed_at": "2026-08-10",
    })
    problems = MODULE._unclaimable(store, ["IMP-20260810-contract"])
    assert [p["kind"] for p in problems] == ["contract-blocked"], problems
    assert any(p["kind"] == "contract-evidence-missing"
               for p in problems[0]["contract_problems"])


def test_an_explicit_claim_cannot_walk_around_dispatch_blocking_edges(tmp_path):
    blocker = "IMP-20260808-aaaaaa"
    blocked = "IMP-20260808-bbbbbb"
    store = _ticket(tmp_path, blocker, **GROOMED)
    _ticket(tmp_path, blocked, blocked_by=[blocker], **GROOMED)

    problems = MODULE._unclaimable(store, [blocked])

    assert [p["kind"] for p in problems] == ["blocked-by-unresolved"], problems
    assert problems[0]["blockers"] == [blocker]


def test_claiming_a_ticket_that_is_not_in_the_store_is_refused(tmp_path):
    """A typo used to claim a ticket that does not exist, and the ledger then held
    an id nobody could ever close."""
    store = _ticket(tmp_path, "IMP-20260808-aaaaaa", **GROOMED)
    problems = MODULE._unclaimable(store, ["IMP-20260808-typo0"])
    assert [p["kind"] for p in problems] == ["not-in-store"], problems
    assert problems[0]["id"] == "IMP-20260808-typo0"


def test_claiming_an_ungroomed_ticket_is_refused_and_names_the_repair(tmp_path):
    store = _ticket(tmp_path, "IMP-20260808-bbbbbb")     # no groom fields at all
    problems = MODULE._unclaimable(store, ["IMP-20260808-bbbbbb"])
    assert [p["kind"] for p in problems] == ["ungroomed"], problems
    assert "backlog.py update" in problems[0]["repair"], problems[0]
    assert "--allow-ungroomed" in problems[0]["repair"], (
        "the refusal has to name its own escape hatch, or the only way past it is "
        "to stop using the flag")
    # The flag list is the whole value of this hint, and it is hand-copied from
    # what `validate` demands — so it drifts silently. It already did: `--brief`
    # and `--scope` joined the groom requirement and this string kept teaching the
    # old command, which is worse than no hint at all because the agent believes
    # it followed the tool. Asserted per flag rather than as one blob so the
    # failure names which one went missing.
    # Asserted over the BACKTICKED COMMAND, not the whole repair string, and with
    # a word boundary. Both narrowings are load-bearing, and both were found by
    # mutation rather than reasoning:
    #   * the string also carries prose explaining --brief/--scope, so `"--brief"
    #     in repair` stayed green with the flags deleted from the command — the
    #     hint then taught a command `update` refuses with exit 64, which is the
    #     precise failure this assertion exists to catch.
    #   * `--acceptance` is a PREFIX of `--acceptance-cmd`, so a plain substring
    #     test is satisfied by a different flag that happens to start the same way.
    backticked = re.search(r"`([^`]+)`", problems[0]["repair"])
    # Named, not an IndexError from `.split("`")[1]`: the guard held either way,
    # but a failure that says "list index out of range" makes the reader debug
    # the test instead of reading the finding.
    assert backticked, (
        f"the repair hint no longer contains a backticked command:\n"
        f"  {problems[0]['repair']}")
    command = backticked.group(1)
    for flag in ("--plan", "--acceptance", "--fix-site", "--acceptance-cmd",
                 "--brief", "--scope", "--groomed-at", "--groomed-by"):
        assert re.search(rf"{re.escape(flag)}(?=[\s=]|$)", command), (
            f"the repair hint's command stopped naming {flag}; following it now "
            f"produces a command `backlog.py update` will refuse:\n  {command}")


def test_the_ungroomed_refusal_also_offers_a_ticket_that_needs_no_grooming(tmp_path):
    """Two different needs, so two exits — and the second one used to be missing.

    Everything else in this refusal answers "I need THIS ticket" by handing back a
    grooming chore. But the usual way to arrive here is picking an id off a list that
    does not distinguish claimable from not, and that caller wanted A ticket, not
    this one. Until the second exit was named, the only way to find it was to already
    know the command exists — which is the definition of a hint that is not one."""
    store = _ticket(tmp_path, "IMP-20260808-999999")     # no groom fields at all
    repair = MODULE._unclaimable(store, ["IMP-20260808-999999"])[0]["repair"]
    # The COMMAND, not the bare word: "dispatch" appears in ordinary prose about
    # handing out work, so a substring test on the word alone would be satisfied by
    # a sentence that names no way to run anything.
    assert "backlog.py dispatch" in repair, repair
    # …and it has to say what that command is FOR, or it reads as a third grooming
    # step rather than the way out of grooming.
    assert re.search(r"unclaimed|claimable|take right now", repair), repair
    # It must not have DISPLACED the grooming route: that is still the right answer
    # for the caller who really did need this particular ticket.
    assert "backlog.py update" in repair and "--allow-ungroomed" in repair, repair


def test_the_claim_gate_only_names_backlog_py_and_never_runs_it():
    """`_unclaimable` runs on the claim path, BEFORE any worktree exists, and the
    bootstrap case requires the orchestrator to work when the rest of the toolchain
    does not (its own docstring says so, and that is why it parses the store's JSON
    by hand rather than shelling out to `backlog.py list --json`).

    The repair hints name `backlog.py` subcommands, which makes "just call it" a
    standing temptation — and a subcommand named in a hint may not even exist on the
    branch being run, so calling one would turn a refusal into a crash. Naming is
    free; invoking is a dependency."""
    import inspect
    src = inspect.getsource(MODULE._unclaimable)
    for forbidden in ("subprocess", "run_streamed_command", "_tool_mutation",
                      "_git_mutation", "import backlog"):
        assert forbidden not in src, (
            f"_unclaimable now reaches for {forbidden!r} — it must only READ the "
            f"store's JSON; the hints name other tools, they do not run them")


def test_claiming_an_already_resolved_ticket_is_refused(tmp_path):
    """Work that is already done is the other way to waste an agent, and it reads
    exactly like a fresh ticket from the id alone."""
    store = _ticket(tmp_path, "IMP-20260808-cccccc", status="fixed",
                    fixed_by=["abc1234"], **GROOMED)
    problems = MODULE._unclaimable(store, ["IMP-20260808-cccccc"])
    assert [p["kind"] for p in problems] == ["already-resolved"], problems


def test_every_unclaimable_ticket_is_named_not_just_the_first(tmp_path):
    """A batch claim that reports one problem sends the caller round the loop N
    times. Same reason `anchor` reports the whole wave."""
    store = _ticket(tmp_path, "IMP-20260808-dddddd")
    _ticket(tmp_path, "IMP-20260808-eeeeee", status="wont-fix",
            resolution="decided against", **GROOMED)
    problems = MODULE._unclaimable(store, ["IMP-20260808-dddddd", "IMP-20260808-eeeeee",
                                        "IMP-20260808-ffffff"])
    assert sorted(p["kind"] for p in problems) == [
        "already-resolved", "not-in-store", "ungroomed"], problems


def test_an_unreadable_store_does_not_silently_permit_the_claim(tmp_path):
    """`could not check` must not become `fine`. The store directory not existing
    is the shape a fresh clone or a wrong --state has."""
    problems = MODULE._unclaimable(tmp_path / "no-such-store", ["IMP-20260808-aaaaaa"])
    assert [p["kind"] for p in problems] == ["not-in-store"], problems


# --------------------------------------------------------------------------
# --via-integration: the teardown audit, run by the tool instead of by a human
#
# Measured with ops/worktree_loadtest.py --mode batch -n 10 --conflict shared:
# integration itself is green (9/10 picks conflict, every conflict resolved, ZERO
# rows lost, one gate, one cutover, 27.9s) and then **10 of 10 source branches
# refuse teardown**. The refusal is correct — `resolve` is a force-discard, and
# after conflict resolution main holds a NEWER version than the branch, which is
# indistinguishable by tree-diff from "never landed". The documented remedy is a
# three-step manual audit per branch, and all three steps are mechanical.
#
# So: a SECOND evidence path, not a looser rule. `--force` still means "I looked";
# `--via-integration <ref>` means "prove it", and the tool says what it matched on.
# --------------------------------------------------------------------------

def _commit(repo, name, body, msg):
    (Path(repo) / name).write_text(body, encoding="utf-8")
    _git(["add", name], repo)
    _git(["commit", "-qm", msg], repo)
    return _git(["rev-parse", "HEAD"], repo).strip()


def test_a_cherry_picked_branch_is_vouched_for_by_patch_id(scratch):
    """The strong match: same change, different sha."""
    tmp_path, repo, remote = scratch
    _git(["checkout", "-q", "-b", "feat/lane"], repo)
    sha = _commit(repo, "lane.txt", "lane work\n", "ops: lane work")
    _git(["checkout", "-q", "main"], repo)
    # main MUST have moved first. With main still at the branch point, git
    # fast-forwards the cherry-pick and the branch becomes a literal ancestor —
    # a state the landed-floor already accepts, so the audit would never be
    # reached. Every real integration has main ahead (other lanes landed first).
    _commit(repo, "trunk.txt", "someone else landed\n", "ops: unrelated trunk work")
    _git(["cherry-pick", sha], repo)

    audit = MODULE._audit_integrated("feat/lane", "main")
    assert audit["ok"] is True, audit
    assert [c["match"] for c in audit["commits"]] == ["patch-id"], audit


def test_a_branch_whose_content_was_amended_during_integration_still_vouches(scratch):
    """The realistic case, and the one tree-diff cannot see.

    Integration resolves a conflict, so what landed is NOT byte-identical to what
    the branch held — patch-id differs. Subject plus the set of files touched is
    the next strongest thing that is still mechanical.
    """
    tmp_path, repo, remote = scratch
    _git(["checkout", "-q", "-b", "feat/lane2"], repo)
    _commit(repo, "shared.md", "| lane2 |\n", "ops: lane2 row")
    _git(["checkout", "-q", "main"], repo)
    # same subject, same file, DIFFERENT content (a merged version)
    _commit(repo, "shared.md", "| lane1 |\n| lane2 |\n", "ops: lane2 row")

    audit = MODULE._audit_integrated("feat/lane2", "main")
    assert audit["ok"] is True, audit
    assert [c["match"] for c in audit["commits"]] == ["subject+files"], audit


def test_a_commit_that_never_landed_is_named_and_refused(scratch):
    """The whole point of keeping the floor: this is the case the manual audit
    exists to catch, and it is the case an impatient `--force` walks straight past."""
    tmp_path, repo, remote = scratch
    _git(["checkout", "-q", "-b", "feat/lane3"], repo)
    kept = _commit(repo, "a.txt", "landed\n", "ops: landed part")
    lost = _commit(repo, "b.txt", "dropped\n", "ops: the part integration missed")
    _git(["checkout", "-q", "main"], repo)
    _commit(repo, "trunk.txt", "someone else landed\n", "ops: unrelated trunk work")
    _git(["cherry-pick", kept], repo)

    audit = MODULE._audit_integrated("feat/lane3", "main")
    assert audit["ok"] is False, audit
    unmatched = [c for c in audit["commits"] if c["match"] is None]
    assert [c["subject"] for c in unmatched] == ["ops: the part integration missed"]
    assert lost[:9] in [c["sha"] for c in unmatched][0], audit


def test_a_same_subject_commit_touching_other_files_does_not_vouch(scratch):
    """Subject alone is not evidence. Two commits can share a message and change
    unrelated things — the file set is what makes the weaker match usable."""
    tmp_path, repo, remote = scratch
    _git(["checkout", "-q", "-b", "feat/lane4"], repo)
    _commit(repo, "wanted.txt", "x\n", "ops: same subject")
    _git(["checkout", "-q", "main"], repo)
    _commit(repo, "unrelated.txt", "y\n", "ops: same subject")

    audit = MODULE._audit_integrated("feat/lane4", "main")
    assert audit["ok"] is False, audit
    assert audit["commits"][0]["match"] is None, audit


def test_the_audit_reports_what_each_commit_was_matched_on(scratch):
    """A verdict without its grounds is the 'reason field nobody reads'. The
    operator has to be able to see that a branch got through on the WEAK match."""
    tmp_path, repo, remote = scratch
    _git(["checkout", "-q", "-b", "feat/lane5"], repo)
    strong = _commit(repo, "s.txt", "strong\n", "ops: strong one")
    _commit(repo, "w.txt", "weak\n", "ops: weak one")
    _git(["checkout", "-q", "main"], repo)
    _commit(repo, "trunk.txt", "someone else landed\n", "ops: unrelated trunk work")
    _git(["cherry-pick", strong], repo)
    _commit(repo, "w.txt", "weak, but merged differently\n", "ops: weak one")

    audit = MODULE._audit_integrated("feat/lane5", "main")
    assert audit["ok"] is True, audit
    assert sorted(c["match"] for c in audit["commits"]) == ["patch-id", "subject+files"]
    assert all(c["matched_sha"] for c in audit["commits"]), audit


def test_resolve_refuses_without_the_flag_and_accepts_with_it(scratch):
    """End to end through the CLI: the floor still stands, and the flag is the
    second door — not a rename of --force."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "lane", "--slug", "picked",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "picked.txt").write_text("work\n", encoding="utf-8")
    _git(["add", "-A"], wt)
    _git(["commit", "-qm", "ops: picked work"], wt)
    sha = _git(["rev-parse", "HEAD"], wt).strip()
    _stage_row(repo, opened["branch"], "IMP-0001")
    # Integrate by hand, exactly as a batch integrator would: trunk moves first,
    # then the pick, then the conflict resolution EDITS the content — merging this
    # lane's line with another lane's. That last step is the whole point: without
    # it main holds a byte-identical copy, the tree-diff floor says "landed", and
    # the audit is never reached. With it, main holds a NEWER version and the floor
    # cannot tell that from "never landed".
    _commit(repo, "trunk.txt", "someone else landed\n", "ops: unrelated trunk work")
    _git(["cherry-pick", sha], repo)
    _commit(repo, "picked.txt", "work\nand another lane's line\n",
            "ops: picked work")

    rc, refused = _run_json(["resolve", "--worktree", wt, "--state", state,
                             "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, refused
    assert "--via-integration" in refused["reason"], (
        "the refusal must name the evidence path, or the only way past it is --force")

    rc, ok = _run_json(["resolve", "--worktree", wt, "--state", state,
                        "--via-integration", "main", "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, ok
    assert ok["audit"]["ok"] is True
    # Either rung is a pass here, and which one is not the CLI's contract: the
    # pick itself survives in main's history with its patch-id intact, so the
    # STRONGER rung vouches even though a later commit edited the same file. The
    # weaker rung is exercised where it actually applies — a conflict resolved
    # inside the pick, which produces one commit whose content differs. See
    # test_a_branch_whose_content_was_amended_during_integration_still_vouches.
    assert all(c["match"] for c in ok["audit"]["commits"]), ok["audit"]
    assert all(c["matched_sha"] for c in ok["audit"]["commits"]), ok["audit"]
    rows = {row["id"]: row for row in _queue_rows(repo)}
    assert rows["IMP-0001"]["landed_sha"] == _git(["rev-parse", "main"], repo).strip(), (
        "a vouched-for batch branch was torn down without stamping its closure")
    assert ok["pending_anchor"] == ["IMP-0001"], ok
    assert not Path(wt).exists(), "worktree survived a vouched-for resolve"


def test_resolve_refuses_an_integration_ref_that_has_not_landed_in_the_base(scratch):
    """A branch may vouch for the patch without vouching that it reached main."""
    tmp_path, repo, remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "lane", "--slug", "unlanded-source",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "source.txt").write_text("source work\n", encoding="utf-8")
    _git(["add", "source.txt"], wt)
    _git(["commit", "-qm", "ops: source work"], wt)
    source_sha = _git(["rev-parse", "HEAD"], wt).strip()

    # The integration branch contains the source patch, but main does not. Before
    # this guard, --via-integration accepted the patch-id and deleted the only source
    # worktree even though nothing had landed in the trunk.
    _git(["checkout", "-q", "-b", "feat/unlanded-integration", "main"], repo)
    _git(["cherry-pick", source_sha], repo)
    _git(["checkout", "-q", "main"], repo)

    rc, refused = _run_json([
        "resolve", "--worktree", wt, "--state", state,
        "--via-integration", "feat/unlanded-integration", "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, refused
    assert refused["reason_code"] == "integration-ref-not-landed", refused
    assert Path(wt).is_dir(), "an unlanded integration ref was allowed to delete source work"


@gitmark
def test_resolve_source_stamps_integration_rows_and_anchor_consumes_resolved_rows(scratch):
    """A resolved source must preserve the integration branch's queue identity.

    In the batch path the hunter stages its closure while checked out on the
    integration branch.  Resolving the source after that branch is already an
    ancestor of ``main`` used to tear the source down without a tree-diff audit,
    so the resolver stamped the source branch (which had no queue row) and left
    the integration row's ``landed_sha`` null.  This is the real supported path:
    stage through ``backlog.py``, resolve through the CLI, then consume through
    ``backlog.py anchor``; the test never edits the queue or marker files.
    """
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json([
        "open", "--intent", "source lane", "--slug", "source-lane",
        "--state", state, "--json",
    ])
    assert rc == MODULE.EXIT_OK, opened
    source_wt = opened["path"]
    source_sha = _commit(source_wt, "source.txt", "source work\n", "ops: source work")

    integration_branch = "feat/integration-lane"
    _git(["checkout", "-q", "-b", integration_branch, "main"], repo)
    _git(["cherry-pick", source_sha], repo)
    integration_sha = _git(["rev-parse", "HEAD"], repo)

    store = repo / "docs" / "runbook" / "backlog"
    queue = repo / ".cache" / "backlog_anchor_queue.jsonl"
    entry_path = store / "IMP-0001.json"
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    entry["resolution"] = "fixture closure"
    entry_path.write_text(json.dumps(entry), encoding="utf-8")
    backlog_spec = importlib.util.spec_from_file_location(
        "backlog_resolve_stamp_fixture", ROOT / "ops" / "backlog.py"
    )
    assert backlog_spec and backlog_spec.loader
    backlog = importlib.util.module_from_spec(backlog_spec)
    backlog_spec.loader.exec_module(backlog)
    backlog.GIT_REPO = repo

    def run_backlog(argv):
        output = io.StringIO()
        errors = io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            rc = backlog.main(argv)
        payload = json.loads(output.getvalue()) if output.getvalue().strip() else {}
        return rc, payload, errors.getvalue()

    rc, stage, stage_err = run_backlog([
        "stage", "IMP-0001", "--store", str(store), "--queue", str(queue),
        "--verdict", "CONFIRMED-FIXED", "--by", "fixture",
        "--evidence", "pytest resolve-via-integration fixture", "--json",
    ])
    assert rc == 0, stage_err or stage
    staged = {row["id"]: row for row in _queue_rows(repo)}
    assert staged["IMP-0001"]["branch"] == integration_branch
    assert staged["IMP-0001"]["landed_sha"] is None

    _git(["checkout", "-q", "main"], repo)
    _git(["merge", "--ff-only", integration_branch], repo)
    rc, resolved = _run_json([
        "resolve", "--worktree", source_wt, "--state", state,
        "--base", "main", "--via-integration", integration_branch,
        "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK, resolved
    assert not Path(source_wt).exists()
    rows = {row["id"]: row for row in _queue_rows(repo)}
    assert rows["IMP-0001"]["landed_sha"] == integration_sha, resolved

    rc, anchored, anchor_err = run_backlog([
        "anchor", "--store", str(store), "--queue", str(queue),
        "--branches", integration_branch, "--commit", "--json",
    ])
    assert rc == 0, anchor_err or anchored
    assert anchored["applied"] == ["IMP-0001"], anchored
    assert _queue_rows(repo) == [], "anchor left a null or duplicate row"
    entry = json.loads((store / "IMP-0001.json").read_text(encoding="utf-8"))
    assert entry["status"] == "fixed"
    assert entry["fixed_by"] == [integration_sha]


# ---------------------------------------------------------------------------
# integrate — N branches, ONE gate (IMP-20260807-267d60)
#
# The verb exists for one answer nothing else can produce: "do these N pieces of
# work still hold together". Measured 2026-08-06 on an eleven-branch batch — review
# of the integrated tree found FIVE blocking defects, and every one of them was
# green under its own branch's gate. So the property under test is not "integrate
# succeeded"; it is that the verdict is bound to the INTEGRATED head, that the
# stop-on-conflict names the file, and that nothing here invents a pass/fail of its
# own (the gate stays the only judge, and cutover stays the only lander).
# ---------------------------------------------------------------------------
def _make_branch(repo, branch, files, msg, base="main"):
    """A branch carrying exactly one commit, with the primary left back on `base`."""
    _git(["checkout", "-q", "-b", branch, base], repo)
    for rel, body in files.items():
        (Path(repo) / rel).write_text(body)
        _git(["add", rel], repo)
    _git(["commit", "-qm", msg], repo)
    _git(["checkout", "-q", base], repo)
    return _git(["rev-parse", branch], repo)


def _commit_on(repo, branch, files, msg, back_to="main"):
    _git(["checkout", "-q", branch], repo)
    for rel, body in files.items():
        (Path(repo) / rel).write_text(body)
        _git(["add", rel], repo)
    _git(["commit", "-qm", msg], repo)
    sha = _git(["rev-parse", "HEAD"], repo)
    _git(["checkout", "-q", back_to], repo)
    return sha


def _run_integrate_json(argv):
    """Legacy synthetic integration fixtures opt into the explicit bypass.

    These tests construct source branches directly and intentionally do not model a
    worker worktree hand-back. Production callers must omit this flag and use the
    registry hand-back stamp; keeping the exception visible at every fixture call
    prevents the test suite from quietly becoming the production contract.
    """
    assert argv and argv[0] == "integrate"
    return _run_json(["integrate", "--allow-unhanded", *argv[1:]])


def _seed_handoff(state, repo, branch, sha):
    path = Path(state)
    ledger = (json.loads(path.read_text()) if path.exists() else {
        "schema": "kg.worktree.registry.v1", "records": [],
    })
    record = {
        "path": str(repo), "branch": branch, "intent": "fixture",
        "base": "main", "created_at": "2999-01-01T00:00:00Z", "status": "active",
        "resolved_at": None, "backlog": [], "claimed_at": None,
        "base_sha": _git(["rev-parse", "main"], repo),
        "handed_back_at": "2999-01-01T00:00:00Z", "handed_back_sha": sha,
    }
    record["handback_seal"] = MODULE.wr._seal_with_digest(
        MODULE.wr._seal_body(
            record, base_sha=record["base_sha"], tip_sha=sha, outcomes=[],
            handed_back_at=record["handed_back_at"],
        )
    )
    ledger["records"].append(record)
    path.write_text(json.dumps(ledger))


def _conflicting_pair(repo):
    """Two branches that both create `shared.txt` — an add/add conflict on the SECOND
    cherry-pick — and `feat/b` carries a FURTHER commit after the conflicting one.

    That trailing commit is load-bearing for the tests, not decoration. With the
    conflict on the last commit of the last branch there is nothing left to pick once
    it is resolved, so "gate the moment the conflict is settled" and "gate when the
    queue is empty" become the same program and no assertion can tell them apart —
    which is precisely the mistake (a verdict bound to a tree that is not the final
    one) the whole ticket is about."""
    a = _make_branch(repo, "feat/a", {"shared.txt": "alpha\n"}, "work: a")
    b1 = _make_branch(repo, "feat/b", {"shared.txt": "beta\n"}, "work: b1")
    b2 = _commit_on(repo, "feat/b", {"b.txt": "b\n"}, "work: b2")
    return a, b1, b2


@gitmark
def test_integrate_dry_run_names_every_commit_and_creates_nothing(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    b = _make_branch(repo, "feat/b", {"b.txt": "b\n"}, "work: b")

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch",
                         "--branches", "feat/a", "feat/b",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK, pay
    assert pay["mode"] == "dry-run", pay
    picks = {p["branch"]: [c["sha"] for c in p["commits"]] for p in pay["plan"]}
    assert picks == {"feat/a": [a], "feat/b": [b]}, pay
    # dry-run means dry-run: no worktree, no branch, no resumable state on disk.
    assert not (Path(repo) / ".claude" / "worktrees" / "batch").exists()
    assert "feat/batch" not in _local_branches(repo)
    assert not MODULE._integrate_state_path(state, "batch").exists()


@gitmark
def test_integrate_stops_at_the_conflicting_branch_and_names_the_file(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a, b1, b2 = _conflicting_pair(repo)

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch",
                         "--branches", "feat/a", "feat/b",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    # NAMING the file is the whole point: "cherry-pick failed" leaves the reader
    # exactly where a bare non-zero exit would.
    assert pay["conflicts"] == ["shared.txt"], pay
    assert pay["stopped"]["branch"] == "feat/b", pay
    assert pay["stopped"]["sha"] == b1, pay
    # It stops, it does not roll back: the first branch is already applied, and the
    # commit it stopped on is still at the head of the queue with its successor.
    assert [p["branch"] for p in pay["picked"]] == ["feat/a"], pay
    assert [c["sha"] for c in pay["remaining"]] == [b1, b2], pay
    wt = pay["worktree"]
    assert MODULE._interrupted_operation(wt) == "cherry-pick"
    assert "<<<<<<<" in (Path(wt) / "shared.txt").read_text()
    assert MODULE._integrate_state_path(state, "batch").exists(), (
        "a stop with no resumable state on disk makes --continue impossible")


@gitmark
def test_integrate_continue_gates_the_integrated_head_not_a_source_branch(scratch):
    """The acceptance criterion of IMP-20260807-267d60, stated as an assertion.

    A verdict bound to any source branch's HEAD is precisely the verdict the batch
    already had before integrating, and the one that missed five defects.

    Which assertion carries which defect, measured rather than assumed (a reviewer
    caught me claiming the wrong one):
      * `head_sha == integrated` catches a payload that MISREPORTS the head, because
        `integrated` is read back off the worktree. It does NOT catch a gate that ran
        too early — the run stops early, so the HEAD read afterwards is the early one
        too and both sides move together. It is a tautology for exactly the defect
        this test is named after.
      * `changed_files` / `picked` / the commit COUNT are what catch that one: they
        are expectations written here from the fixture, not read back from the run.
    Keep all of them; just do not mistake the first for the proof."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a, b1, b2 = _conflicting_pair(repo)

    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, stopped
    wt = stopped["worktree"]

    (Path(wt) / "shared.txt").write_text("alpha\nbeta\n")
    _git(["add", "shared.txt"], wt)

    rc, done = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                          "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, done
    assert done["gate"]["verdict"] in ("pass", "warn"), done

    integrated = _git(["rev-parse", "HEAD"], wt)
    assert done["head_sha"] == integrated, done
    rec = json.loads(MODULE._gate_record_path(state, wt).read_text())
    assert rec["head_sha"] == integrated, rec["head_sha"]
    assert rec["head_sha"] not in (a, b1, b2), (
        "the verdict is bound to a SOURCE branch head — that is the pre-integration "
        "verdict wearing a new name")
    # Everything both branches contributed is inside the tree that was judged —
    # including feat/b's commit AFTER the conflicted one, which is what a gate fired
    # the moment the conflict settled would be missing.
    assert set(rec["changed_files"]) == {"shared.txt", "b.txt"}, rec["changed_files"]
    assert [c["sha"] for c in done["picked"]] == [a, b1, b2], done["picked"]
    assert len(_git(["rev-list", "main..HEAD"], wt).split()) == 3, (
        "the integrated tree does not hold one commit per authored commit — this "
        "expectation comes from the fixture, not from anything the run reported")
    assert (Path(wt) / "shared.txt").read_text() == "alpha\nbeta\n"


@gitmark
def test_integrate_continue_no_gate_stops_before_the_gate(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a, b1, b2 = _conflicting_pair(repo)

    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, stopped
    wt = stopped["worktree"]
    (Path(wt) / "shared.txt").write_text("alpha\nbeta\n")
    _git(["add", "shared.txt"], wt)

    rc, picked = _run_integrate_json(["integrate", "--slug", "batch",
                            "--state", state, "--continue", "--commit",
                            "--no-gate", "--json"])
    assert rc == MODULE.EXIT_OK, picked
    assert picked["mode"] == "picked", picked
    assert picked["gated"] is False, picked
    assert picked["verdict"] is None, picked
    assert [c["sha"] for c in picked["picked"]] == [a, b1, b2], picked
    assert MODULE.gate_history_rows(state) == []
    assert not MODULE._gate_record_path(state, wt).exists()
    saved = json.loads(MODULE._integrate_state_path(state, "batch").read_text())
    assert saved["queue"] == []
    assert saved["gate_pending"] is True


@gitmark
def test_integrate_continue_no_gate_then_gate_runs_alone_on_the_final_tree(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a, b1, b2 = _conflicting_pair(repo)

    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, stopped
    wt = stopped["worktree"]
    (Path(wt) / "shared.txt").write_text("alpha\nbeta\n")
    _git(["add", "shared.txt"], wt)

    rc, picked = _run_integrate_json(["integrate", "--slug", "batch",
                            "--state", state, "--continue", "--commit",
                            "--no-gate", "--json"])
    assert rc == MODULE.EXIT_OK, picked
    assert picked["mode"] == "picked", picked

    rc, done = _run_integrate_json(["integrate", "--slug", "batch",
                          "--state", state, "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, done
    assert done["gate"]["verdict"] in ("pass", "warn"), done
    integrated = _git(["rev-parse", "HEAD"], wt)
    rec = json.loads(MODULE._gate_record_path(state, wt).read_text())
    assert rec["head_sha"] == integrated, rec
    assert MODULE.gate_history_rows(state), "the delayed gate must write its journal"
    assert not MODULE._integrate_state_path(state, "batch").exists()


@gitmark
def test_integrate_append_fans_in_late_children_without_running_a_premature_gate(scratch):
    """A Delivery Team master may integrate children as they hand back.

    Append extends the same round state and worktree, preserves source ownership,
    and remains pick-only even when the caller forgets --no-gate. The master
    chooses when the expected child set is complete and then runs the one final
    Gate through --continue.
    """
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _seed_handoff(state, repo, "feat/a", a)

    rc, first = _run_json([
        "integrate", "--slug", "round", "--branches", "feat/a",
        "--state", state, "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_OK, first
    assert first["mode"] == "picked", first
    wt = first["worktree"]
    assert MODULE.gate_history_rows(state) == []

    b = _make_branch(repo, "feat/b", {"b.txt": "b\n"}, "work: b")
    _seed_handoff(state, repo, "feat/b", b)
    rc, appended = _run_json([
        "integrate", "--slug", "round", "--append", "--branches", "feat/b",
        "--state", state, "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK, appended
    assert appended["mode"] == "picked", appended
    assert appended["gated"] is False, appended
    assert appended["branches"] == ["feat/a", "feat/b"], appended
    assert [item["sha"] for item in appended["picked"]] == [a, b], appended
    assert (Path(wt) / "a.txt").read_text() == "a\n"
    assert (Path(wt) / "b.txt").read_text() == "b\n"
    saved = json.loads(MODULE._integrate_state_path(state, "round").read_text())
    assert saved["branches"] == ["feat/a", "feat/b"], saved
    assert saved["planned_total"] == 2, saved
    assert saved["queue"] == [], saved
    assert saved["gate_pending"] is True, saved
    assert MODULE.gate_history_rows(state) == []


@gitmark
def test_integrate_runs_the_gate_once_for_the_whole_batch(scratch):
    """Counted from the gate's OWN journal, not from a number integrate reports about
    itself. A per-branch implementation would report `gate_runs: 1` just as happily."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _make_branch(repo, "feat/b", {"b.txt": "b\n"}, "work: b")

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch",
                         "--branches", "feat/a", "feat/b",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    rows = MODULE.gate_history_rows(state)
    assert [r["gate"] for r in rows] == ["coverage"], rows
    wt_key = MODULE.hashlib.sha256(
        MODULE._norm(pay["worktree"]).encode()).hexdigest()[:16]
    assert rows[0]["wt"] == wt_key, rows


@gitmark
def test_integrate_copies_commits_rather_than_merging_the_sources(scratch):
    """cherry-pick, not merge. A merge would make the source commits ancestors of the
    integrated head, which drags along whatever else those branches happened to be
    carrying — measured on the 2026-08-06 batch, two branches each carried another
    session's discarded commit.

    The trunk is advanced AFTER the branches are cut, deliberately. Without that, the
    first cherry-pick lands on the very parent the commit already had and git
    reproduces the identical sha, so `a not in shas` would be measuring the clock
    (committer dates have one-second granularity) rather than the operation. Moving
    the trunk makes a rewrite unavoidable — and it is also the real shape: branches
    are cut, then main moves under them."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    b = _make_branch(repo, "feat/b", {"b.txt": "b\n"}, "work: b")
    _advance_local_main(repo, "trunkmove")

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch",
                         "--branches", "feat/a", "feat/b",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    wt = pay["worktree"]
    shas = _git(["rev-list", "main..HEAD"], wt).split()
    assert len(shas) == 2, shas
    assert a not in shas and b not in shas, (
        "the source commits are ancestors of the integrated head — that is a merge")
    assert _git(["rev-list", "--merges", "main..HEAD"], wt).split() == []
    assert (Path(wt) / "a.txt").exists() and (Path(wt) / "b.txt").exists()
    # every commit that arrived is one the tool NAMED, source sha and new sha both
    assert {(c["sha"], c["new_sha"]) for c in pay["picked"]} == {
        (a, shas[1]), (b, shas[0])}, pay["picked"]
    # the source branches are untouched by the integration
    assert _git(["rev-parse", "feat/a"], repo) == a
    assert _git(["rev-parse", "feat/b"], repo) == b


@gitmark
def test_integrate_does_not_advance_the_trunk(scratch):
    """`integrate` gates; `cutover` lands. Keeping the two apart is what leaves the
    existing "no block verdict may land" contract as the ONE place that rule lives."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    assert "a.txt" not in _local_main_files(repo)
    assert "cutover" in pay["next_step"], pay


@gitmark
def test_integrate_refuses_a_second_start_while_one_is_in_flight(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _conflicting_pair(repo)
    rc, _stopped = _run_integrate_json(["integrate", "--slug", "batch",
                              "--branches", "feat/a", "feat/b",
                              "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, _stopped
    rc, again = _run_integrate_json(["integrate", "--slug", "batch",
                           "--branches", "feat/a", "feat/b",
                           "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_USAGE, again
    assert "--continue" in again["error"] and "--abort" in again["error"], again
    # Not just "the message mentions its own flags" — it must be ABOUT the live
    # integration: name the worktree, and be reachable only while one is genuinely
    # in flight (see test_integrate_forgets_a_finished_integration).
    assert again["worktree"] == _stopped["worktree"], again
    assert Path(again["worktree"]).is_dir()


@gitmark
def test_integrate_continue_without_an_integration_says_which_one_is_missing(scratch):
    tmp_path, _repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, pay = _run_integrate_json(["integrate", "--slug", "ghost", "--state", state,
                         "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_USAGE, pay
    assert "ghost" in pay["error"], pay


@gitmark
def test_integrate_continue_refuses_while_paths_are_still_unmerged(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _conflicting_pair(repo)
    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                         "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    assert pay["conflicts"] == ["shared.txt"], pay
    # and nothing was gated over the conflicted tree
    assert not MODULE._gate_record_path(state, stopped["worktree"]).exists()


@gitmark
def test_integrate_abort_clears_the_in_flight_cherry_pick(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _conflicting_pair(repo)
    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    wt = stopped["worktree"]

    rc, dry = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                         "--abort", "--json"])
    assert rc == MODULE.EXIT_OK and dry["mode"] == "dry-run", dry
    assert MODULE._interrupted_operation(wt) == "cherry-pick", (
        "a dry-run abort aborted something")

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                         "--abort", "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    assert MODULE._interrupted_operation(wt) is None
    assert not MODULE._integrate_state_path(state, "batch").exists()
    # The worktree itself survives: teardown is `resolve`'s job, and it is the only
    # step that consults the landed-floor.
    assert Path(wt).is_dir()
    assert "resolve" in pay["next_step"], pay


@gitmark
def test_integrate_names_a_branch_that_does_not_resolve(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    rc, pay = _run_integrate_json(["integrate", "--slug", "batch",
                         "--branches", "feat/a", "feat/nope",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_USAGE, pay
    assert any("feat/nope" in p for p in pay["problems"]), pay
    assert not any("feat/a" in p for p in pay["problems"]), pay


@gitmark
def test_integrate_refuses_a_branch_carrying_a_merge_commit(scratch):
    """A merge commit has no single parent to diff against, so `rev-list --no-merges`
    would drop it silently — and silently dropping a commit is the failure mode the
    whole verb exists to prevent."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/side", {"side.txt": "s\n"}, "work: side")
    _git(["checkout", "-q", "-b", "feat/m", "main"], repo)
    (Path(repo) / "m.txt").write_text("m\n")
    _git(["add", "m.txt"], repo)
    _git(["commit", "-qm", "work: m"], repo)
    _git(["merge", "--no-ff", "-q", "-m", "merge side", "feat/side"], repo)
    merge_sha = _git(["rev-parse", "HEAD"], repo)
    _git(["checkout", "-q", "main"], repo)

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--branches", "feat/m",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_USAGE, pay
    assert any(merge_sha[:8] in p for p in pay["problems"]), pay


@gitmark
def test_integrate_is_refused_while_the_flow_is_frozen(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    rc, _ = _run_json(["freeze", "on", "--reason", "surgery", "--state", state,
                       "--json"])
    assert rc == MODULE.EXIT_OK
    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    assert pay["error"] == "frozen", pay


def test_integrate_is_wired_into_the_parser():
    p = MODULE.build_parser()
    ns = p.parse_args(["integrate", "--slug", "b", "--branches", "x", "y"])
    assert ns.func is MODULE.cmd_integrate
    assert ns.branches == ["x", "y"] and ns.commit is False
    assert ns.allow_unhanded is False and ns.append is False
    cw = p.parse_args([
        "close-wave", "--slug", "wave", "--branches", "x", "--sync",
    ])
    assert cw.func is MODULE.cmd_close_wave
    assert cw.sync is True and cw.commit is False


@gitmark
def test_integrate_refuses_a_source_branch_without_hand_back(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")

    rc, pay = _run_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    assert pay["error"] == "source branches were not handed back for integration"
    assert pay["handoff"]["problems"][0]["reason"] == "no active registry record"
    assert "hand-back" in pay["handoff"]["problems"][0]["remedy"]


@gitmark
def test_integrate_refuses_a_branch_that_advanced_after_hand_back(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    handed_back = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    current = _commit_on(repo, "feat/a", {"b.txt": "b\n"}, "work: a follow-up")
    _seed_handoff(state, repo, "feat/a", handed_back)

    rc, pay = _run_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    problem = pay["handoff"]["problems"][0]
    assert problem["reason"] == "branch advanced after hand-back"
    assert problem["handed_back_sha"] == handed_back
    assert problem["current_tip_sha"] == current

    # The explicit legacy bypass only covers a missing stamp; it must not turn a
    # stale stamp into permission to integrate code that was not handed back.
    rc, allowed = _run_json(["integrate", "--slug", "batch-allowed",
                             "--branches", "feat/a", "--state", state,
                             "--allow-unhanded", "--json"])
    assert rc == MODULE.EXIT_BLOCK, allowed
    assert allowed["handoff"]["problems"][0]["reason"] == "branch advanced after hand-back"


@gitmark
def test_integrate_accepts_a_branch_whose_tip_matches_hand_back(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    handed_back = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _seed_handoff(state, repo, "feat/a", handed_back)

    rc, pay = _run_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    assert pay["handoff"]["problems"] == []
    assert pay["handoff"]["warnings"] == []


@gitmark
def test_a_handed_back_branch_can_feed_only_one_live_integration(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    handed_back = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _seed_handoff(state, repo, "feat/a", handed_back)

    rc, first = _run_json([
        "integrate", "--slug", "round-four", "--branches", "feat/a",
        "--state", state, "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_OK, first
    assert first["mode"] == "picked", first

    rc, second = _run_json([
        "integrate", "--slug", "round-five", "--branches", "feat/a",
        "--state", state, "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, second
    assert second["error"] == "source branches already belong to another integration"
    conflict = second["source_claim"]["conflicts"][0]
    assert conflict["branch"] == "feat/a", conflict
    assert conflict["owner"]["branch"] == first["branch"], conflict
    assert not (Path(repo) / ".claude" / "worktrees" / "round-five").exists()


@gitmark
def test_integrate_continue_recovers_a_crash_between_state_and_source_claim(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    handed_back = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _seed_handoff(state, repo, "feat/a", handed_back)
    rc, picked = _run_json([
        "integrate", "--slug", "round-four", "--branches", "feat/a",
        "--state", state, "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_OK, picked

    assert MODULE.wr.release_integration_sources(
        Path(state), integration_branch=picked["branch"]) == ["feat/a"]
    spath = MODULE._integrate_state_path(state, "round-four")
    saved = json.loads(spath.read_text())
    saved.pop("source_claim", None)
    spath.write_text(json.dumps(saved))

    rc, resumed = _run_json([
        "integrate", "--slug", "round-four", "--state", state,
        "--continue", "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_OK, resumed
    records = json.loads(Path(state).read_text())["records"]
    source = next(r for r in records if r["branch"] == "feat/a")
    assert source["integration_owner"]["branch"] == picked["branch"], source


@gitmark
def test_an_integration_tree_survives_until_its_sources_are_resolved(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    handed_back = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _seed_handoff(state, repo, "feat/a", handed_back)

    rc, integrated = _run_json([
        "integrate", "--slug", "round-four", "--branches", "feat/a",
        "--state", state, "--commit", "--no-gate", "--json",
    ])
    assert rc == MODULE.EXIT_OK, integrated

    rc, refused = _run_json([
        "resolve", "--worktree", integrated["worktree"], "--state", state,
        "--force", "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, refused
    assert refused["reason_code"] == "integration-sources-active", refused
    assert refused["source_branches"] == ["feat/a"], refused
    assert Path(integrated["worktree"]).is_dir()


@gitmark
def test_two_round_integrations_converge_through_one_parent_gate_and_cutover(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    leaf_specs = {
        "feat/r4-a": {"r4-a.txt": "r4-a\n"},
        "feat/r4-b": {"r4-b.txt": "r4-b\n"},
        "feat/r5-a": {"r5-a.txt": "r5-a\n"},
        "feat/r5-b": {"r5-b.txt": "r5-b\n"},
    }
    for branch, files in leaf_specs.items():
        sha = _make_branch(repo, branch, files, f"work: {branch}")
        _seed_handoff(state, repo, branch, sha)

    rc, round4 = _run_json([
        "integrate", "--slug", "round-four", "--branches",
        "feat/r4-a", "feat/r4-b", "--state", state, "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK, round4
    rc, round5 = _run_json([
        "integrate", "--slug", "round-five", "--branches",
        "feat/r5-a", "feat/r5-b", "--state", state, "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK, round5

    for branch in (round4["branch"], round5["branch"]):
        rc, handoff = MODULE._registry([
            "hand-back", "--state", state, "--branch", branch, "--json",
        ])
        assert rc == MODULE.EXIT_OK, handoff

    rc, parent = _run_integrate_json([
        "integrate", "--slug", "rounds-four-five", "--branches",
        round4["branch"], round5["branch"], "--state", state,
        "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK, parent
    assert parent["verdict"] in ("pass", "warn"), parent
    for rel, body in {k: v for files in leaf_specs.values()
                      for k, v in files.items()}.items():
        assert (Path(parent["worktree"]) / rel).read_text() == body

    rc, landed = _run_json([
        "cutover", "--worktree", parent["worktree"], "--state", state,
        "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK and landed["landed"] is True, landed
    assert _git(["rev-parse", "main"], repo) == parent["head_sha"]
    assert len(MODULE.gate_history_rows(state)) == 3, (
        "the two round gates and the one parent gate are the three intended "
        "integrated-tree judgements; leaf gates belong to their workers")

    # The synthetic leaves share the fixture's primary path, so close their ledger
    # records directly; real workers use orchestrator resolve and remove their own
    # distinct worktrees. Once those ownership edges are terminal, the two round
    # trees and finally the parent can be torn down in dependency order.
    for branch in leaf_specs:
        rc, closed = MODULE._registry([
            "resolve", "--state", state, "--branch", branch,
            "--status", "merged", "--json",
        ])
        assert rc == MODULE.EXIT_OK, closed
    for round_result in (round4, round5):
        rc, closed = _run_json([
            "resolve", "--worktree", round_result["worktree"], "--state", state,
            "--via-integration", "main", "--commit", "--json",
        ])
        assert rc == MODULE.EXIT_OK, closed
    rc, closed = _run_json([
        "resolve", "--worktree", parent["worktree"], "--state", state,
        "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_OK, closed
    ledger = json.loads(Path(state).read_text())
    assert [r for r in ledger["records"] if r["status"] == "active"] == []


@gitmark
def test_integrate_allow_unhanded_is_explicit_and_names_the_warning(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")

    rc, pay = _run_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--allow-unhanded", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    assert pay["handoff"]["problems"] == []
    assert pay["handoff"]["warnings"] == [{
        "branch": "feat/a",
        "reason": "no active registry record",
        "remedy": "./ops/worktree_registry.py hand-back --branch feat/a --json",
    }]


# --- the false-green shapes: three ways `integrate` could hand cutover a verdict
#     it should never have produced (adversarial pass over a396e45ff) --------------
@gitmark
def test_integrate_refuses_to_gate_a_batch_its_own_books_do_not_add_up(scratch):
    """The failure this guard exists for is invisible without it: a batch that lost
    a branch's work gates GREEN, and green is exactly what `cutover` is waiting for.

    It judges nothing about the code — every commit leaves the queue into exactly one
    of `picked`/`skipped`, so the sum is an invariant of this tool's own bookkeeping.
    Same family as cutover's `gated_sha == rebased_sha`."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _conflicting_pair(repo)
    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    wt = stopped["worktree"]

    spath = MODULE._integrate_state_path(state, "batch")
    st = json.loads(spath.read_text())
    assert st["planned_total"] == 3, st
    st["queue"] = []                       # the queue empties without the work landing
    st.pop("stopped", None)
    spath.write_text(json.dumps(st))
    _git(["cherry-pick", "--abort"], wt)   # so nothing else refuses first

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                         "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    assert pay["planned_total"] == 3 and pay["accounted"] == 1, pay
    assert not MODULE._gate_record_path(state, wt).exists(), (
        "a verdict was recorded for a short batch — cutover would land it on green")


@gitmark
def test_integrate_surfaces_the_gates_own_refusal_rather_than_a_null_verdict(scratch):
    """`gate` has exits that REFUSE instead of judging (mid-operation tree, wrong
    orchestrator, base moved); those payloads carry `error` and no `verdict` at all.
    Reporting that as "verdict: None — fix the blocking gate(s)" hands the reader
    advice for a different problem while the real cause sits unread in gate's own
    payload — and points at a verdict record that was never written.

    Driven through the REAL refusal rather than a stubbed gate, and through the one
    that actually happens: the trunk moving while a human resolves a conflict. That
    is not an edge case — it is why `land` exists — and `integrate` does not run
    `catchup`, so it is on the normal path for a batch."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _conflicting_pair(repo)
    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    wt = stopped["worktree"]

    _advance_local_main(repo, "moved-while-you-resolved")
    (Path(wt) / "shared.txt").write_text("alpha\nbeta\n")
    _git(["add", "shared.txt"], wt)

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                         "--continue", "--commit", "--json"])
    assert rc != MODULE.EXIT_OK, pay
    assert pay["mode"] == "refused", pay
    # The CAUSE has to reach the operator, and so does the remedy gate itself names.
    assert "behind" in pay["error"], pay["error"]
    assert "catchup" in pay["error"], pay["error"]
    # …and it must not claim a verdict record that was never written.
    assert "verdict" not in pay or pay.get("verdict") is None, pay
    assert not MODULE._gate_record_path(state, wt).exists()


@gitmark
def test_integrate_continue_refuses_when_the_worktree_is_on_another_branch(scratch):
    """Everything after this point — the picks, the verdict, the sha cutover lands —
    is about whatever branch is actually checked out, not the one the state file
    names."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _conflicting_pair(repo)
    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/b",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK
    wt = stopped["worktree"]
    _git(["cherry-pick", "--abort"], wt)
    _git(["checkout", "-q", "-b", "sidetrack"], wt)

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                         "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, pay
    assert pay["actual_branch"] == "sidetrack", pay
    assert pay["expected_branch"] == stopped["branch"], pay
    assert not MODULE._gate_record_path(state, wt).exists()


@gitmark
def test_integrate_forgets_a_finished_integration(scratch):
    """A drained queue with a verdict on it is not something you can `--continue`.

    Keeping the state file made a FINISHED integration answer the next
    `integrate --slug <same>` with "already in flight … resume it with --continue
    after resolving" — false about the state, false about the remedy, and pointing
    at conflicts that do not exist. It was also residue `resolve` cannot strike,
    against a module docstring that promises none."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch", "--branches", "feat/a",
                         "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, pay
    assert pay["state_cleared"] is True, pay
    assert not MODULE._integrate_state_path(state, "batch").exists()
    manifest = Path(pay["manifest"])
    assert manifest.is_file(), pay
    completed = json.loads(manifest.read_text())
    assert completed["status"] == "gated", completed
    assert completed["head_sha"] == pay["head_sha"], completed
    assert completed["branches"] == ["feat/a"], completed

    # …and the follow-on question the residue used to answer wrongly.
    rc, again = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                           "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_USAGE, again
    # Asserted against the WRONG CLAIM, not against a phrase: the honest answer here
    # ("no integration named 'batch' is in flight") legitimately contains the words
    # "in flight", and a first draft of this test failed on exactly that. What must
    # not appear is the assertion that one is ALREADY in flight, and the instruction
    # to resume it after resolving conflicts that do not exist.
    assert "already in flight" not in again["error"], again["error"]
    assert "resolving" not in again["error"], again["error"]
    assert "start one with" in again["error"], again["error"]


@gitmark
def test_a_blocking_integrated_gate_keeps_state_for_retry_or_abort(scratch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    (Path(repo) / "ops").mkdir()
    handed_back = _make_branch(
        repo, "feat/bad-shell", {"ops/bad-round.sh": "if then\n"},
        "ops: add invalid shell fixture",
    )
    _seed_handoff(state, repo, "feat/bad-shell", handed_back)

    rc, blocked = _run_json([
        "integrate", "--slug", "blocked-round", "--branches", "feat/bad-shell",
        "--state", state, "--commit", "--json",
    ])
    assert rc == MODULE.EXIT_BLOCK, blocked
    assert blocked["verdict"] == "block", blocked
    assert blocked["state_cleared"] is False, blocked
    assert blocked["manifest"] is None, blocked
    saved = json.loads(
        MODULE._integrate_state_path(state, "blocked-round").read_text())
    assert saved["gate_pending"] is True, saved
    assert saved["source_claim"]["claimed"] == ["feat/bad-shell"], saved
    assert "--continue --commit" in blocked["next_step"], blocked


@gitmark
def test_integrate_refuses_stacked_branches_that_queue_a_commit_twice(scratch):
    """The mirror image of silently dropping a commit.

    `main..feat/b` contains feat/a's commits when b is stacked on a, so naming both
    queues the same commit twice; the second pick is an EMPTY cherry-pick, which
    stops the run with no unmerged paths and a message about conflict resolution —
    a diagnosis pointing away from the actual mistake."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a = _make_branch(repo, "feat/a", {"a.txt": "a\n"}, "work: a")
    _git(["checkout", "-q", "-b", "feat/b", "feat/a"], repo)
    (Path(repo) / "b.txt").write_text("b\n")
    _git(["add", "b.txt"], repo)
    _git(["commit", "-qm", "work: b"], repo)
    _git(["checkout", "-q", "main"], repo)

    rc, pay = _run_integrate_json(["integrate", "--slug", "batch",
                         "--branches", "feat/a", "feat/b",
                         "--state", state, "--json"])
    assert rc == MODULE.EXIT_USAGE, pay
    dup = [p for p in pay["problems"] if a[:8] in p]
    assert dup, pay["problems"]
    assert "feat/a" in dup[0] and "feat/b" in dup[0], dup
    # naming only the tip is the documented way through, and it must still work
    rc, ok = _run_integrate_json(["integrate", "--slug", "batch", "--branches", "feat/b",
                        "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK, ok
    assert [c["sha"] for c in ok["plan"][0]["commits"]][0] == a, ok


@gitmark
def test_integrate_names_a_commit_that_produced_nothing_instead_of_losing_it(scratch):
    """`skipped` is the ONLY channel through which "a commit you named is not in the
    integrated tree" reaches the operator, and it had no test at all.

    Reached the way it really happens: two branches carrying the same change, so the
    second pick is empty and `git cherry-pick --skip` is what git itself tells you to
    run (verified against git's own output, not assumed)."""
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    a = _make_branch(repo, "feat/a", {"dup.txt": "same\n"}, "work: a")
    c = _make_branch(repo, "feat/c", {"dup.txt": "same\n"}, "work: c (same change)")

    rc, stopped = _run_integrate_json(["integrate", "--slug", "batch",
                             "--branches", "feat/a", "feat/c",
                             "--state", state, "--commit", "--json"])
    assert rc == MODULE.EXIT_BLOCK, stopped
    # An empty pick has NO unmerged paths — the refusal must not invent conflicts.
    assert stopped["conflicts"] == [], stopped
    assert stopped["stopped"]["sha"] == c, stopped
    assert "--skip" in stopped["error"], stopped["error"]

    wt = stopped["worktree"]
    _git(["cherry-pick", "--skip"], wt)
    rc, done = _run_integrate_json(["integrate", "--slug", "batch", "--state", state,
                          "--continue", "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, done
    assert [x["sha"] for x in done["skipped"]] == [c], done
    assert [x["sha"] for x in done["picked"]] == [a], done
    # the books still balance, so the gate was allowed to run
    assert done["gate"]["verdict"] in ("pass", "warn"), done


@gitmark
def test_gate_reuse_records_and_reuses_out_of_scope_inputs(scratch, monkeypatch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    _seed_python_scan(repo)
    rc, opened = _run_json(["open", "--intent", "gate reuse", "--slug", "reuse",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "ops" / "lib").mkdir(parents=True)
    (Path(wt) / "ops" / "tests").mkdir(parents=True)
    (Path(wt) / "ops" / "lib" / "foo.py").write_text("value = 1\n")
    (Path(wt) / "ops" / "tests" / "test_foo.py").write_text("def test_foo(): pass\n")
    _git(["add", "ops/lib/foo.py", "ops/tests/test_foo.py"], wt)
    _git(["commit", "-qm", "ops: add gate input fixture"], wt)

    calls = []

    def fake_run(spec, worktree, *, record_path=None, state=None):
        calls.append(spec["name"])
        return {"name": spec["name"], "category": spec["category"],
                "level": spec["level"], "status": "pass", "rc": 0,
                "summary": "fixture gate ran"}

    monkeypatch.setattr(MODULE, "_run_gate", fake_run)
    rc, first = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    first_head = first["head_sha"]
    ops_first = next(g for g in first["gates"] if g["name"] == "ops-pytest")
    assert calls == ["ops-python-scan", "ops-pytest", "coverage"]
    assert {"ops/lib/foo.py", "ops/tests/test_foo.py"}.issubset(
        ops_first["input"]["files"]
    )
    assert "ops/python_scan.py" in ops_first["input"]["files"]
    assert ops_first["input"]["fingerprint"]
    assert ops_first["reuse"]["decision"] == "rerun"
    progress_path = MODULE._gate_progress_path(state, wt)
    first_progress = json.loads(progress_path.read_text(encoding="utf-8"))
    first_run_id = first_progress["run_id"]

    (Path(wt) / "notes.txt").write_text("unrelated backlog follow-up\n")
    _git(["add", "notes.txt"], wt)
    _git(["commit", "-qm", "docs: add unrelated follow-up note"], wt)
    calls.clear()
    rc, second = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    ops_second = next(g for g in second["gates"] if g["name"] == "ops-pytest")
    assert calls == ["coverage"], "the expensive ops gate must be reused"
    assert second["head_sha"] != first_head
    assert ops_second["reused"] is True
    assert ops_second["reused_from_head"] == first_head
    assert ops_second["reuse"] == {"decision": "reused", "source_head": first_head,
                                    "reason": "input_unchanged"}
    assert second["gate_reuse"]["reused"] == [
        {"name": "ops-python-scan", "source_head": first_head, "reason": "input_unchanged"},
        {"name": "ops-pytest", "source_head": first_head, "reason": "input_unchanged"},
    ]

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["head_sha"] == second["head_sha"]
    assert progress["run_id"] != first_run_id
    assert progress["done"] == progress["plan_total"] == len(second["gates"])
    assert progress["completed"] == [
        {"name": result["name"], "status": result["status"]}
        for result in second["gates"]
    ]

    # The progress sidecar is deliberately not a cutover input. Invalidating it must
    # not affect the verdict record produced above.
    progress_path.write_text("not-json\n", encoding="utf-8")
    rc, cut = _run_json(["cutover", "--worktree", wt, "--state", state,
                         "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, cut
    assert cut["gate_reuse"]["reused"][0]["source_head"] == first_head
    rc, resolved = _run_json(["resolve", "--worktree", wt, "--state", state,
                              "--commit", "--json"])
    assert rc == MODULE.EXIT_OK, resolved
    assert resolved["gate_progress_removed"] is True
    assert not progress_path.exists(), "resolve must leave no progress sidecar residue"


def test_gate_reuse_separates_ios_build_and_test_tool_inputs(tmp_path, monkeypatch):
    """A test-runner repair must not invalidate already-green build gates.

    This is the concrete retry shape: the first run compiled successfully but an iOS
    test gate failed; the repair changes only ios_test.sh.  Build and test both consume
    ios_ops.sh, but only the test gate consumes ios_test.sh.
    """
    monkeypatch.setattr(MODULE, "_git", lambda *args, **kwargs: (0, ""))
    tracked = [
        "ios/App.swift",
        "ops/ios_ops.sh",
        "ops/ios_build.sh",
        "ops/ios_test.sh",
        "ops/ios_diagnostics.py",
        "ops/ios_coverage.py",
        "ops/ui_world_manifest.py",
        "ops/uitest_review_page.py",
        "ops/fixtures/ui_worlds/marketing_demo.json",
        "ops/lib/ios_ops_core.sh",
        "ops/lib/ios_build_progress.sh",
        "ops/lib/ios_test_discovery.sh",
    ]
    for rel in tracked:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{rel}\n")

    specs = _by_name(MODULE.plan_gates(
        ["ios/BooksAndVocabUITests/LiveDemoAccessUITests.swift"],
        ops_test_exists=lambda rel: rel in tracked,
    ))
    build = specs["ios-build"]
    test = specs["ios-test-unit"]
    live_compile = specs["ios-live-demo-uitest-compile"]
    build_before = MODULE._gate_input_scope(build, str(tmp_path), tracked[:1], tracked)
    test_before = MODULE._gate_input_scope(test, str(tmp_path), tracked[:1], tracked)
    live_before = MODULE._gate_input_scope(
        live_compile, str(tmp_path), tracked[:1], tracked)

    assert "ops/ios_ops.sh" in build_before["files"]
    assert "ops/ios_ops.sh" in test_before["files"]
    assert "ops/ios_build.sh" in build_before["files"]
    assert "ops/ios_test.sh" not in build_before["files"]
    assert "ops/ios_test.sh" in test_before["files"]
    assert "ops/ios_build.sh" not in test_before["files"]
    assert "ops/ios_diagnostics.py" in build_before["files"]
    assert "ops/ios_coverage.py" in test_before["files"]
    assert "ops/uitest_review_page.py" in test_before["files"]
    assert "ops/fixtures/ui_worlds/marketing_demo.json" in test_before["files"]
    assert live_before["kind"] == "tracked-ios-test-surface"
    assert "ops/ios_test.sh" in live_before["files"]

    previous = {
        "schema": MODULE.GATE_SCHEMA,
        "base": "main",
        "head_sha": "a" * 40,
        "orchestrator": {"sha256": "same"},
        "gates": [
            {"name": "ios-build", "category": "ios", "level": "block",
             "status": "pass", "rc": 0, "summary": "green", "input": build_before},
            {"name": "ios-test-unit", "category": "ios", "level": "block",
             "status": "pass", "rc": 0, "summary": "green", "input": test_before},
        ],
    }
    (tmp_path / "ops/ios_test.sh").write_text("repaired test runner\n")
    build_after = MODULE._gate_input_scope(build, str(tmp_path), tracked[:1], tracked)
    test_after = MODULE._gate_input_scope(test, str(tmp_path), tracked[:1], tracked)

    reused, reason = MODULE._reuse_gate(
        build, build_after, previous, None, {"sha256": "same"})
    assert reused is not None and reason == "input_unchanged"
    rerun, reason = MODULE._reuse_gate(
        test, test_after, previous, None, {"sha256": "same"})
    assert rerun is None and reason == "input_content_changed"

    # A shared dispatcher edit still invalidates both commands; the optimization
    # may narrow proven dependencies, never wish them away.
    (tmp_path / "ops/ios_test.sh").write_text("ops/ios_test.sh\n")
    (tmp_path / "ops/ios_ops.sh").write_text("changed shared dispatcher\n")
    build_shared = MODULE._gate_input_scope(build, str(tmp_path), tracked[:1], tracked)
    test_shared = MODULE._gate_input_scope(test, str(tmp_path), tracked[:1], tracked)
    for spec, current in ((build, build_shared), (test, test_shared)):
        reused, reason = MODULE._reuse_gate(
            spec, current, previous, None, {"sha256": "same"})
        assert reused is None and reason == "input_content_changed"

    # Runtime helpers are verdict inputs too.  A diagnostics edit affects both
    # runners; UI-world data/validation affects test gates but not app builds.
    for rel in ("ops/ios_ops.sh", "ops/ios_test.sh"):
        (tmp_path / rel).write_text(f"{rel}\n")
    runtime_mutations = [
        ("ops/ios_diagnostics.py", True, True),
        ("ops/ui_world_manifest.py", False, True),
        ("ops/fixtures/ui_worlds/marketing_demo.json", False, True),
    ]
    for rel, invalidates_build, invalidates_test in runtime_mutations:
        path = tmp_path / rel
        original = path.read_text()
        path.write_text("mutated runtime input\n")
        for spec, before, should_invalidate in (
            (build, build_before, invalidates_build),
            (test, test_before, invalidates_test),
        ):
            current = MODULE._gate_input_scope(spec, str(tmp_path), tracked[:1], tracked)
            prior = {**previous, "gates": [
                {"name": spec["name"], "category": "ios", "level": "block",
                 "status": "pass", "rc": 0, "summary": "green", "input": before},
            ]}
            reused, reason = MODULE._reuse_gate(
                spec, current, prior, None, {"sha256": "same"})
            if should_invalidate:
                assert reused is None and reason == "input_content_changed", rel
            else:
                assert reused is not None and reason == "input_unchanged", rel
        path.write_text(original)

    unknown = MODULE._internal("future-ios-gate", "ios", "block")
    unknown_scope = MODULE._gate_input_scope(
        unknown, str(tmp_path), tracked[:1], tracked)
    assert unknown_scope["kind"] == "tracked-ios-surface"
    assert "ops/ios_build.sh" in unknown_scope["files"]
    assert "ops/ios_test.sh" in unknown_scope["files"]


def test_gate_progress_treats_invalid_utf8_as_unreadable(tmp_path):
    progress_path = tmp_path / "gate.progress.json"
    progress_path.write_bytes(b"\xff\xfe\n")

    assert MODULE._read_gate_progress(progress_path) is None


def test_ios_gate_input_map_covers_declared_shell_dependencies():
    """A new sourced helper must not silently sit outside the reuse fingerprint."""
    def declared_libs(rel):
        text = (ROOT / rel).read_text()
        return {f"ops/lib/{name}" for name in re.findall(
            r"(?:source|METRICS_LIB=)[^\n]*?/lib/([A-Za-z0-9_]+[.]sh)", text)}

    def declared_files(rel):
        text = (ROOT / rel).read_text()
        names = re.findall(
            r"[$](?:SCRIPT_DIR|PROJECT_ROOT)/(?:ops/)?([A-Za-z0-9_./-]+[.](?:py|sh))",
            text,
        )
        return {f"ops/{name}" for name in names}

    common = set(MODULE._IOS_OPS_COMMON_INPUTS)
    common.update(
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "ops/lib").glob("ios_ops_*.sh")
    )
    assert declared_libs("ops/ios_ops.sh") <= common
    assert declared_libs("ops/lib/ios_ops_catalog.sh") <= common
    assert declared_files("ops/ios_build.sh") <= (
        common | set(MODULE._IOS_BUILD_INPUTS))
    test_inputs = common | set(MODULE._IOS_TEST_INPUTS)
    test_inputs.update(
        p.relative_to(ROOT).as_posix()
        for pattern in ("ops/uitest_review_*.py", "ops/catalog_*.py")
        for p in ROOT.glob(pattern)
    )
    assert declared_files("ops/ios_test.sh") <= test_inputs


@gitmark
def test_gate_reuse_is_fail_safe_for_changed_unknown_legacy_and_bad_sources(
        scratch, monkeypatch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "gate reuse", "--slug", "reuse-fail-safe",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "ops" / "lib").mkdir(parents=True)
    (Path(wt) / "ops" / "tests").mkdir(parents=True)
    foo = Path(wt) / "ops" / "lib" / "foo.py"
    test = Path(wt) / "ops" / "tests" / "test_foo.py"
    foo.write_text("value = 1\n")
    test.write_text("def test_foo(): pass\n")
    _git(["add", "ops/lib/foo.py", "ops/tests/test_foo.py"], wt)
    _git(["commit", "-qm", "ops: add gate input fixture"], wt)

    def fake_run(spec, worktree, *, record_path=None, state=None):
        return {"name": spec["name"], "category": spec["category"],
                "level": spec["level"], "status": "pass", "rc": 0,
                "summary": "fixture gate ran"}

    monkeypatch.setattr(MODULE, "_run_gate", fake_run)
    rc, first = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    ops_spec = next(s for s in MODULE.plan_gates(
        first["changed_files"], ops_test_exists=lambda rel: (Path(wt) / rel).is_file(),
        base="main") if s["name"] == "ops-pytest")

    foo.write_text("value = 2\n")
    _git(["add", "ops/lib/foo.py"], wt)
    _git(["commit", "-qm", "ops: change gate input"], wt)
    rc, changed = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    ops_changed = next(g for g in changed["gates"] if g["name"] == "ops-pytest")
    assert ops_changed["reused"] is False
    assert ops_changed["reuse"]["reason"] == "input_content_changed"

    tracked = MODULE._tracked_paths(wt)
    unknown_spec = MODULE._internal("future-gate", "meta", "block")
    unknown = MODULE._gate_input_scope(unknown_spec, wt, changed["changed_files"], tracked)
    assert unknown["reusable"] is False
    previous, error = MODULE._read_gate_record(MODULE._gate_record_path(state, wt))
    assert error is None
    orch = MODULE._orchestrator_identity(wt)
    current_input = next(g for g in changed["gates"] if g["name"] == "ops-pytest")["input"]
    reused, reason = MODULE._reuse_gate(unknown_spec, unknown, previous, error, orch)
    assert reused is None and reason == "input_scope_not_reusable"

    legacy = json.loads(json.dumps(previous))
    legacy_ops = next(g for g in legacy["gates"] if g["name"] == "ops-pytest")
    legacy_ops.pop("input")
    reused, reason = MODULE._reuse_gate(ops_spec, current_input, legacy, None, orch)
    assert reused is None and reason == "source_record_has_no_input_fingerprint"

    blocked = json.loads(json.dumps(previous))
    next(g for g in blocked["gates"] if g["name"] == "ops-pytest")["status"] = "block"
    reused, reason = MODULE._reuse_gate(ops_spec, current_input, blocked, None, orch)
    assert reused is None and reason == "source_status_block"
    inconclusive = json.loads(json.dumps(previous))
    next(g for g in inconclusive["gates"] if g["name"] == "ops-pytest")["status"] = "inconclusive"
    reused, reason = MODULE._reuse_gate(ops_spec, current_input, inconclusive, None, orch)
    assert reused is None and reason == "source_status_inconclusive"

    wrong_current = json.loads(json.dumps(current_input))
    wrong_current["schema"] = "wrong.input.v0"
    reused, reason = MODULE._reuse_gate(ops_spec, wrong_current, previous, None, orch)
    assert reused is None and reason == "current_input_schema_unknown"
    wrong_source = json.loads(json.dumps(previous))
    wrong_source["schema"] = "wrong.gate.v0"
    reused, reason = MODULE._reuse_gate(ops_spec, current_input, wrong_source, None, orch)
    assert reused is None and reason == "source_record_schema_unknown"
    wrong_input = json.loads(json.dumps(previous))
    next(g for g in wrong_input["gates"] if g["name"] == "ops-pytest")["input"]["schema"] = "wrong.input.v0"
    reused, reason = MODULE._reuse_gate(ops_spec, current_input, wrong_input, None, orch)
    assert reused is None and reason == "source_input_schema_unknown"

    malformed_null_gates = json.loads(json.dumps(previous))
    malformed_null_gates["gates"] = None
    reused, reason = MODULE._reuse_gate(
        ops_spec, current_input, malformed_null_gates, None, orch)
    assert reused is None and reason == "source_record_gates_invalid"

    malformed_gate_item = json.loads(json.dumps(previous))
    malformed_gate_item["gates"] = ["not-a-gate"]
    reused, reason = MODULE._reuse_gate(
        ops_spec, current_input, malformed_gate_item, None, orch)
    assert reused is None and reason == "source_record_gates_invalid"


@gitmark
def test_gate_reuse_refuses_head_move_during_input_snapshot(scratch, monkeypatch):
    tmp_path, repo, _remote = scratch
    state = str(tmp_path / "reg.json")
    rc, opened = _run_json(["open", "--intent", "gate race", "--slug", "reuse-race",
                            "--state", state, "--json"])
    assert rc == MODULE.EXIT_OK
    wt = opened["path"]
    (Path(wt) / "ops" / "lib").mkdir(parents=True)
    (Path(wt) / "ops" / "tests").mkdir(parents=True)
    (Path(wt) / "ops" / "lib" / "foo.py").write_text("value = 1\n")
    (Path(wt) / "ops" / "tests" / "test_foo.py").write_text("def test_foo(): pass\n")
    _git(["add", "ops/lib/foo.py", "ops/tests/test_foo.py"], wt)
    _git(["commit", "-qm", "ops: add race fixture"], wt)
    initial = _git(["rev-parse", "HEAD"], wt)
    moved = _git(["rev-parse", "main"], repo)
    calls = []

    def fake_head(path):
        calls.append(path)
        return initial if len(calls) == 1 else moved

    def fake_run(*args, **kwargs):
        raise AssertionError("a moving HEAD must refuse before running a gate")

    monkeypatch.setattr(MODULE, "_head_sha", fake_head)
    monkeypatch.setattr(MODULE, "_run_gate", fake_run)
    rc, gate = _run_json(["gate", "--worktree", wt, "--state", state, "--json"])
    assert rc == MODULE.EXIT_BLOCK
    assert "HEAD moved while preparing gate inputs" in gate["error"]
    assert not MODULE._gate_record_path(state, wt).exists()
