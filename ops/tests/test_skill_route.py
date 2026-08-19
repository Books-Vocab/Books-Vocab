from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skill_route.py"
ROOT = SCRIPT.parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("skill_route", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_catalog_inventory_and_fixtures_are_green(capsys):
    mod = load_module()
    assert mod.main(["validate", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"schema": "kg.skill_catalog.v1", "status": "ok", "skills": 15, "fixtures": 12}


def test_human_intent_aliases_resolve_to_canonical_primary_intents():
    mod = load_module()
    delivery = mod.resolve_route(mod.load_catalog(), "delivery")
    assert delivery["requested_intent"] == "delivery"
    assert delivery["intent"] == "delivery-worktree"
    assert delivery["primary"] == "worktree-flow"

    review = mod.resolve_route(mod.load_catalog(), "review")
    assert review["intent"] == "code-review"
    assert review["primary"] == "code-review"


def test_visual_report_has_one_primary_and_required_simulator_dependency():
    mod = load_module()
    route = mod.resolve_route(mod.load_catalog(), "visual-report-rebuild")
    assert route["primary"] == "ios-visual-report-workflow"
    assert route["skills"] == ["kg-router", "ios-simulator-verification", "ios-visual-report-workflow"]
    assert route["authorization"]["granted"] is False


def test_optional_and_closure_are_explicit():
    mod = load_module()
    route = mod.resolve_route(mod.load_catalog(), "podcast-pipeline", include_optional=True, include_closure=True)
    assert route["skills"] == ["kg-router", "podcast", "kg-receipt"]


def test_delivery_intent_has_one_primary_and_typed_context_dependency():
    mod = load_module()
    route = mod.resolve_route(mod.load_catalog(), "delivery-worktree")
    assert route["primary"] == "worktree-flow"
    assert route["skills"] == ["kg-router", "kg-agent-context", "worktree-flow"]
    assert route["dependencies"] == {"required": ["kg-agent-context"], "optional": [], "closure": []}


def test_code_review_route_requires_context_and_does_not_load_delivery():
    mod = load_module()
    route = mod.resolve_route(mod.load_catalog(), "review")
    assert route["skills"] == ["kg-router", "kg-agent-context", "code-review"]
    assert "worktree-flow" not in route["skills"]


def test_missing_skill_is_not_silently_ignored():
    mod = load_module()
    broken = copy.deepcopy(mod.load_catalog())
    broken["skills"] = broken["skills"][:-1]
    try:
        mod.validate_catalog(broken, ROOT)
    except mod.SkillCatalogError as exc:
        assert "skill parity" in str(exc)
    else:
        raise AssertionError("catalog parity must fail closed")


def test_primary_overlap_is_rejected():
    mod = load_module()
    broken = copy.deepcopy(mod.load_catalog())
    broken["skills"][1]["intents"].append("bug")
    try:
        mod.validate_catalog(broken, ROOT)
    except mod.SkillCatalogError as exc:
        assert "primary intent overlap" in str(exc)
    else:
        raise AssertionError("primary overlap must fail closed")


def test_bootstrap_and_required_fixture_dependencies_fail_closed():
    mod = load_module()
    broken_bootstrap = copy.deepcopy(mod.load_catalog())
    broken_bootstrap["bootstrap"] = ["missing-bootstrap"]
    try:
        mod.validate_catalog(broken_bootstrap, ROOT)
    except mod.SkillCatalogError as exc:
        assert "bootstrap" in str(exc)
    else:
        raise AssertionError("unknown bootstrap must fail closed")

    broken_fixture = copy.deepcopy(mod.load_catalog())
    broken_fixture["fixtures"][-1]["required_secondary"] = []
    try:
        mod.validate_catalog(broken_fixture, ROOT)
    except mod.SkillCatalogError as exc:
        assert "required_secondary" in str(exc)
    else:
        raise AssertionError("omitted required dependency must fail closed")


def test_intent_alias_target_must_be_a_real_primary_intent():
    mod = load_module()
    broken = copy.deepcopy(mod.load_catalog())
    broken["intent_aliases"]["phantom"] = "not-a-primary-intent"
    try:
        mod.validate_catalog(broken, ROOT)
    except mod.SkillCatalogError as exc:
        assert "alias target" in str(exc)
    else:
        raise AssertionError("phantom alias target must fail closed")


def test_cold_start_contract_validates_before_route_and_names_docs_steward():
    startup = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    validate = "./ops/skill_route.py validate --json"
    route = "./ops/skill_route.py route --intent "
    assert validate in startup
    assert route in startup
    route_start = startup.index(route)
    route_line = startup[route_start:startup.find("\n", route_start)]
    assert "--json" in route_line
    assert startup.index(validate) < route_start
    assert "docs_lint.sh" in startup
