"""Behavior-group collector for worktree_orchestrate (planning)."""

from worktree_orchestrate_support import *  # noqa: F401,F403

def test_usage_errors_return_contract_code_for_root_and_subparser_typos():
    """Argparse's generic 2 must not collide with the workflow usage code 64."""
    for argv in (["--brnach"], ["open", "--brnach"]):
        assert MODULE.main(argv) == MODULE.EXIT_USAGE

def test_gate_omission_always_plans_official_deck_check():
    """The deck index check is fixed-set, not selected by a changed path."""
    gates = plan_gates(
        [],
        ops_test_exists=lambda rel: rel == "ops/official_decks/build_official.py",
        base="main",
    )
    deck = _by_name(gates)["official-decks-check"]
    assert deck["level"] == "block"
    assert deck["cwd"] == "backend"
    assert deck["cmd"] == [
        "uv", "run", "python", "../ops/official_decks/build_official.py",
        "check", "--json",
    ]

def test_gate_omission_routes_untracked_paths_into_the_gate_plan(monkeypatch):
    """A new untracked spec must be visible even when HEAD has no diff."""
    def fake_git(args, cwd=None):
        if args[:2] == ["diff", "--name-only"]:
            return 0, ""
        if args == ["status", "--porcelain", "--untracked-files=all"]:
            return 0, "?? ops/official_decks/untracked.json\n"
        raise AssertionError(f"unexpected git probe: {args!r}")

    monkeypatch.setattr(MODULE, "_git", fake_git)
    assert MODULE._changed_vs_base("/tmp/fixture", "main") == [
        "ops/official_decks/untracked.json"
    ]

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

def test_branch_for_explicit_type_overrides_intent_inference():
    assert branch_for(
        "review card front merges into one accessibility element",
        "review-card-a11y",
        branch_type="debug",
    ) == "debug/review-card-a11y"
    assert branch_for("fix the crash", "x", branch_type="research") == "research/x"

def test_open_parser_exposes_explicit_branch_type_choices():
    parser = MODULE.build_parser()
    subparsers = next(
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    open_parser = subparsers.choices["open"]
    type_action = next(action for action in open_parser._actions if "--type" in action.option_strings)
    assert set(type_action.choices) == {"debug", "feat", "research"}

def test_open_and_adopt_parser_expose_direct_scope_and_codex_thread_owner():
    parser = MODULE.build_parser()
    subparsers = next(
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    for name in ("open", "adopt"):
        option_strings = {
            option
            for action in subparsers.choices[name]._actions
            for option in action.option_strings
        }
        assert "--scope" in option_strings
        assert "--scope-file" in option_strings
        assert "--codex-thread-id" in option_strings

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

def test_agent_constitution_is_routed_to_its_contract_gate():
    """The root constitution must not remain an anonymous coverage warning."""
    gates = plan_gates(["CLAUDE.md"], ops_test_exists=lambda rel: True, base="main")
    coverage = next(g for g in gates if g["name"] == "coverage")
    constitution = next(g for g in gates if g["name"] == "agent-constitution")
    assert coverage["uncovered"] == []
    assert "CLAUDE.md" in coverage["covered"]
    assert constitution["level"] == "block"
    assert constitution["cmd"] == ["ops/tests/test_docs_lint.sh"]

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

def test_gate_plan_does_not_require_commit_review_metadata():
    """Review metadata must not be a machine gate or cutover prerequisite."""
    gates = plan_gates(["README.md"], ops_test_exists=lambda rel: True, base="main")
    assert not any("review" in str(gate.get("name", "")).lower() for gate in gates)
    assert all(not gate.get("preflight") for gate in gates)

def test_integrate_gate_does_not_request_commit_review_metadata(
        tmp_path, monkeypatch, capsys
):
    """Integration uses normal machine gates without an alternate metadata mode."""
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
    assert "machine_gate" not in call

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
    ui = _by_name(gates)["ios-test-ui:ReaderFlowTests"]
    assert ui["cmd"] == [
        "ops/ios_ops.sh", "test", "--ui", "--json", "--lease",
        "--dataset", "marketing_demo", "--file", "ReaderFlowTests",
    ]
    # helper/page-object files are not test classes
    gates = plan_gates(["ios/BooksAndVocabUITests/Pages/AppPage.swift"])
    assert not any(n.startswith("ios-test-ui") for n in _names(gates))

def test_gate_plan_deleted_uitest_is_named_but_never_executed():
    deleted = "ios/BooksAndVocabUITests/DictionaryLookupFlowUITests.swift"
    changed = [deleted, "ios/BooksAndVocabUITests/FixtureDatasetUITests.swift"]
    gates = plan_gates(changed, ops_test_exists=lambda rel: rel != deleted)
    names = _names(gates)

    assert "ios-test-ui:DictionaryLookupFlowUITests" not in names
    removed = _by_name(gates)["ios-ui-tests-removed"]
    assert removed["level"] == "warn"
    assert removed["files"] == [deleted]

    fixture = _by_name(gates)["ios-test-ui:FixtureDatasetUITests"]
    assert "--visual" in fixture["cmd"]

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

def test_gate_plan_deleted_backend_test_is_not_passed_to_pytest():
    deleted = "backend/tests/test_dictionary_lifecycle.py"
    live = "backend/tests/test_dictionary_lookup_surface.py"
    gates = plan_gates([deleted, live], ops_test_exists=lambda rel: rel != deleted)
    spec = _by_name(gates)["backend-pytest"]

    assert "tests/test_dictionary_lifecycle.py" not in spec["cmd"]
    assert "tests/test_dictionary_lookup_surface.py" in spec["cmd"]
    removed = _by_name(gates)["backend-tests-removed"]
    assert removed["level"] == "warn"
    assert removed["files"] == [deleted]

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
    assert spec["cmd"][7:11] == ["--with", "pyjwt", "--with", "cryptography"]
    assert spec["cmd"][11:13] == ["pytest", "-q"]
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
    exists = {
        "ops/tests/test_worktree_orchestrate_planning.py",
        "ops/tests/test_worktree_orchestrate_gate.py",
        "ops/tests/test_worktree_orchestrate_lifecycle.py",
        "ops/tests/test_worktree_orchestrate_claims.py",
        "ops/tests/test_worktree_orchestrate_delivery.py",
        "ops/tests/test_worktree_orchestrate_recovery.py",
        "ops/tests/test_orchestrator_seams.py",
        "ops/tests/test_worktree_gate_tiers.py",
    }.__contains__
    gates = plan_gates(["ops/worktree_orchestrate.py"], ops_test_exists=exists)
    focused = _by_name(gates)["ops-pytest-orchestrator-focused"]
    group = _by_name(gates)["ops-pytest-orchestrator-group"]
    assert focused["cmd"][:3] == ["ops/test_route.py", "run", "--mode"]
    assert "--route-id" in focused["cmd"]
    assert group["tier"] == "S2"
    assert group["supersedes"] == ["ops-pytest-orchestrator-focused"]
    assert "ops/tests/test_worktree_orchestrate.py" not in group["cmd"]


def test_gate_plan_core_gate_inputs_keeps_the_focused_gate_route():
    exists = {"ops/tests/test_worktree_orchestrate_gate.py"}.__contains__
    gates = _by_name(plan_gates(
        ["ops/lib/worktree_orchestrator_core_gate_inputs.py"],
        ops_test_exists=exists,
    ))
    focused = gates["ops-pytest-orchestrator-focused"]
    group = gates["ops-pytest-orchestrator-group"]
    assert "orchestrator.gate" in focused["cmd"]
    assert "orchestrator.fallback" not in focused["cmd"]
    assert "orchestrator.gate" in group["cmd"]
    assert "orchestrator.fallback" not in group["cmd"]


def test_gate_plan_routes_control_plane_and_kg_board_sources_without_ops_suite_fallback():
    changed = [
        "ops/lib/worktree_gate_tiers.py",
        "ops/lib/worktree_test_routes.py",
        "ops/lib/worktree_orchestrator_commands.py",
        "ops/tests/test_orchestrator_seams.py",
        "ops/kg_board/__init__.py",
        "ops/kg_board/git_tree.py",
        "ops/kg_board/model.py",
        "ops/kg_board/scope.py",
        "ops/kg_board/server.py",
    ]
    exists = {
        "ops/tests/test_orchestrator_seams.py",
        "ops/tests/test_worktree_gate_tiers.py",
        "ops/tests/test_worktree_orchestrate_planning.py",
        "ops/tests/test_worktree_orchestrate_gate.py",
        "ops/tests/test_worktree_orchestrate_lifecycle.py",
        "ops/tests/test_worktree_orchestrate_claims.py",
        "ops/tests/test_worktree_orchestrate_delivery.py",
        "ops/tests/test_worktree_orchestrate_recovery.py",
        "ops/tests/test_kg_board_git_tree.py",
        "ops/tests/test_kg_board_model.py",
        "ops/tests/test_kg_board_web.py",
        "ops/tests/test_worktree_gate_tiers_route.py",
    }.__contains__

    gates = _by_name(plan_gates(changed, ops_test_exists=exists))

    assert "ops-pytest-orchestrator-focused" in gates
    assert "ops-pytest-orchestrator-group" in gates
    assert "ops-pytest" not in gates
    for name in ("ops-pytest-orchestrator-focused", "ops-pytest-orchestrator-group"):
        assert "orchestrator.fallback" not in gates[name]["cmd"]
    assert "orchestrator.kg-board" in gates["ops-pytest-orchestrator-focused"]["cmd"]


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
    # change must use the explicit parent-group fallback, never an empty command.
    gates = plan_gates(["ops/worktree_orchestrate.py"])
    group = _by_name(gates)["ops-pytest-orchestrator-group"]
    assert "orchestrator.fallback" in group["cmd"]
    assert "ops-pytest-orchestrator-focused" not in _names(gates)

def test_gate_plan_ops_src_and_its_test_dedupes_target():
    # the self-referential dogfood shape: tool + its test changed together
    exists = {
        "ops/tests/test_worktree_orchestrate_planning.py",
        "ops/tests/test_worktree_orchestrate_gate.py",
        "ops/tests/test_worktree_orchestrate_lifecycle.py",
        "ops/tests/test_worktree_orchestrate_claims.py",
        "ops/tests/test_worktree_orchestrate_delivery.py",
        "ops/tests/test_worktree_orchestrate_recovery.py",
        "ops/tests/test_orchestrator_seams.py",
        "ops/tests/test_worktree_gate_tiers.py",
    }.__contains__
    gates = plan_gates(["ops/worktree_orchestrate.py",
                        "ops/tests/test_worktree_orchestrate.py"],
                       ops_test_exists=exists)
    focused = _by_name(gates)["ops-pytest-orchestrator-focused"]
    route_ids = focused["cmd"][focused["cmd"].index("--route-id") + 1:]
    assert len(route_ids) == len(set(route_ids))
    assert "ops-pytest-orchestrator-group" in _names(gates)

def test_gate_plan_ops_shell_selects_no_ops_pytest():
    """Shell scripts have no pytest counterpart; docs/backend must not leak into the
    ops route either."""
    assert "ops-pytest" not in _names(plan_gates(["ops/devops_kg_safe.sh"]))
    assert not any(n == "ops-pytest"
                   for n in _names(plan_gates(["docs/reference/tech_index.md"])))
    assert not any(n == "ops-pytest"
                   for n in _names(plan_gates(["backend/tests/test_app.py"])))

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


def test_expensive_ops_control_plane_proofs_are_not_classified_as_smoke():
    gates = _by_name(plan_gates([
        "ops/tests/test_ops_ci_coverage.sh",
        "ops/tests/test_gate_can_fail.sh",
    ], ops_test_exists=lambda rel: True))
    assert gates["ops-shell:test_ops_ci_coverage.sh"]["tier"] == "S2"
    assert gates["ops-shell:test_gate_can_fail.sh"]["tier"] == "S2"


def test_deleted_shell_paths_do_not_create_untested_warning():
    deleted = {"ops/removed_shell_fixture.sh", "ops/tests/test_removed_shell_fixture.sh"}
    exists = lambda rel: rel not in deleted

    gates = plan_gates(sorted(deleted), ops_test_exists=lambda rel: False,
                       path_exists=exists)
    names = _names(gates)

    assert "ops-shell-syntax" not in names
    assert "ops-shell-scan" not in names
    assert "ops-shell-untested" not in names
    assert deleted.isdisjoint(_by_name(gates)["coverage"]["uncovered"])

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
    """`promotion/` already has a neutral rule. Routing yml must not
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
    but exactly the set where the basename CONVENTION applies. The guard therefore
    also pins the two halves
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
    routed = out.stdout.split()
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
    routed_outside_ops = [p for p in out.stdout.split()
                          if not p.startswith("ops/")]
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
