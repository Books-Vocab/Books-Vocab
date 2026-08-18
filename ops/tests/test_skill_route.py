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
    assert payload == {"schema": "kg.skill_catalog.v1", "status": "ok", "skills": 13, "fixtures": 10}


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
    assert "Docs Steward" in startup
