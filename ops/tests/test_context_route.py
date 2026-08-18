from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "context_route.py"
ROOT = SCRIPT.parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("context_route", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_manifest_validates_against_current_sources(capsys):
    mod = load_module()

    assert mod.main(["validate", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == "kg.context_plane.v1"
    assert payload["status"] == "ok"
    assert payload["units"] >= 20
    assert payload["routes"] >= 8


def test_delivery_child_backend_route_is_bounded_and_slice_based():
    mod = load_module()
    payload = mod.resolve_route(mod.load_manifest(), "Delivery Child", "backend")

    assert payload["role"] == "delivery-child"
    assert payload["summary"]["estimatedTokens"] <= payload["summary"]["maxTokens"]
    ids = [unit["id"] for unit in payload["units"]]
    assert "worktree.child-handoff" in ids
    assert "tech-index.backend-routers" not in ids
    assert all("content" in unit for unit in payload["units"])
    assert all(unit["contentType"] == "untrusted-document-data" for unit in payload["units"])
    tech = next(unit for unit in payload["units"] if unit["path"] == "docs/reference/tech_index.md")
    assert len(tech["content"]) < len((ROOT / tech["path"]).read_text(encoding="utf-8"))
    assert tech["registryId"] == "reference.tech_index"
    assert len(tech["sourceSha256"]) == 64


def test_duplicate_units_are_removed_across_matching_routes():
    mod = load_module()
    payload = mod.resolve_route(mod.load_manifest(), "delivery-child", task="handback")

    ids = [unit["id"] for unit in payload["units"]]
    assert len(ids) == len(set(ids))
    assert ids.count("worktree.child-stop") == 1
    assert "receipt.core" in ids


def test_unknown_role_fails_closed():
    mod = load_module()
    try:
        mod.resolve_route(mod.load_manifest(), "unknown-role")
    except mod.ContextPlaneError as exc:
        assert "找不到可用 role" in str(exc)
    else:
        raise AssertionError("unknown role must fail closed")


def test_documented_role_aliases_resolve_to_typed_routes():
    mod = load_module()

    assert mod.resolve_route(mod.load_manifest(), "docs-steward", surface="docs")["role"] == "docs-steward"
    assert mod.resolve_route(mod.load_manifest(), "Docs Steward", surface="docs")["role"] == "docs-steward"
    assert mod.resolve_route(mod.load_manifest(), "delivery-coordinator")["role"] == "delivery-integrator"
    assert mod.resolve_route(mod.load_manifest(), "platform-steward")["role"] == "ticket-factory"
    manager = mod.resolve_route(mod.load_manifest(), "Manager")
    assert manager["role"] == "delivery-manager"
    assert "worktree.manager" in [unit["id"] for unit in manager["units"]]


def test_docs_steward_does_not_preload_worktree_context():
    mod = load_module()
    base = mod.resolve_route(mod.load_manifest(), "docs-steward", surface="docs")
    handback = mod.resolve_route(mod.load_manifest(), "docs-steward", surface="docs", task="handback")

    base_ids = [unit["id"] for unit in base["units"]]
    handback_ids = [unit["id"] for unit in handback["units"]]
    assert not any(unit_id.startswith("worktree.") for unit_id in base_ids)
    assert "worktree.child-stop" in handback_ids
    assert "worktree.child-handoff" in handback_ids


def test_missing_anchor_fails_without_full_file_fallback():
    mod = load_module()
    manifest = mod.load_manifest()
    broken = copy.deepcopy(manifest)
    broken["units"][0]["start"] = "## missing-context-anchor"

    try:
        mod.validate_manifest(broken, ROOT)
    except mod.ContextPlaneError as exc:
        assert "anchor 次數=0" in str(exc)
    else:
        raise AssertionError("missing anchor must fail closed")


def test_unit_budget_cannot_exceed_manifest_default():
    mod = load_module()
    broken = copy.deepcopy(mod.load_manifest())
    broken["units"][0]["max_tokens"] = broken["defaults"]["max_unit_tokens"] + 1

    try:
        mod.validate_manifest(broken, ROOT)
    except mod.ContextPlaneError as exc:
        assert "超過全域上限" in str(exc)
    else:
        raise AssertionError("unit budget must be bounded by manifest default")


def test_registry_owner_mismatch_fails_closed():
    mod = load_module()
    manifest = mod.load_manifest()
    broken = copy.deepcopy(manifest)
    broken["units"][0]["registry_id"] = "sop.backend"

    try:
        mod.validate_manifest(broken, ROOT)
    except mod.ContextPlaneError as exc:
        assert "不在 registry sources" in str(exc)
    else:
        raise AssertionError("registry ownership mismatch must fail closed")


def test_registry_exclusion_overrides_broad_positive_source():
    mod = load_module()
    from types import SimpleNamespace

    document = SimpleNamespace(path="docs/reference/example.md", sources=["ops/", "!ops/tests/"])
    assert mod._registry_owns_path(document, "ops/context_route.py") is True
    assert mod._registry_owns_path(document, "ops/tests/test_context_route.py") is False


def test_route_provenance_is_explicit_and_does_not_grant_authority():
    mod = load_module()
    payload = mod.resolve_route(mod.load_manifest(), "delivery-child")

    assert payload["provenance"]["head"]
    assert payload["provenance"]["worktree"] == str(ROOT.resolve())
    assert payload["roleAttestation"]["status"] == "untrusted-input"
    assert payload["authorization"]["granted"] is False


def test_skill_context_route_adds_only_selected_skill_kernel():
    mod = load_module()
    payload = mod.resolve_route(mod.load_manifest(), "delivery-child", skill="app-debug")

    ids = [unit["id"] for unit in payload["units"]]
    assert "skill.app-debug.kernel" in ids
    assert "skill.devops.kernel" not in ids
    assert all("references/" not in unit["path"] for unit in payload["units"])


def test_feature_existence_route_is_explicit_opt_in():
    mod = load_module()
    base = mod.resolve_route(mod.load_manifest(), "delivery-child", "backend")
    feature = mod.resolve_route(mod.load_manifest(), "delivery-child", "backend", "feature-existence")

    assert "product-surface.backend" not in [unit["id"] for unit in base["units"]]
    assert "product-surface.backend" in [unit["id"] for unit in feature["units"]]


def test_tool_friction_reference_is_opt_in():
    mod = load_module()
    base = mod.resolve_route(mod.load_manifest(), "delivery-child")
    friction = mod.resolve_route(mod.load_manifest(), "delivery-child", task="tool-friction")

    assert "router.tool-friction" not in [unit["id"] for unit in base["units"]]
    assert "router.tool-friction" in [unit["id"] for unit in friction["units"]]


def test_bootstrap_route_contains_complete_router_and_agent_context_kernel():
    mod = load_module()
    payload = mod.resolve_route(mod.load_manifest(), "delivery-child")
    units = {unit["id"]: unit for unit in payload["units"]}

    assert "## Routing Table" in units["router.routing"]["content"]
    assert "## Output Contract" in units["router.output"]["content"]
    assert "## Loading discipline" in units["agent-context.loading"]["content"]


def test_registry_gate_reference_is_opt_in():
    mod = load_module()
    base = mod.resolve_route(mod.load_manifest(), "delivery-child")
    registry = mod.resolve_route(mod.load_manifest(), "delivery-child", task="docs-registry")

    assert "docs-control.registry-gate" not in [unit["id"] for unit in base["units"]]
    assert "docs-control.registry-gate" in [unit["id"] for unit in registry["units"]]


def test_registry_gate_documented_cli_route_is_executable(capsys):
    mod = load_module()

    assert mod.main(["render", "--role", "docs-steward", "--task", "docs-registry", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["role"] == "docs-steward"
    assert "docs-control.registry-gate" in [unit["id"] for unit in payload["units"]]


def test_route_text_output_is_an_index_without_source_content(capsys):
    mod = load_module()
    assert mod.main(["route", "--role", "delivery-child", "--surface", "backend"]) == 0
    output = capsys.readouterr().out
    assert "[context][unit]" in output
    assert "## Backend API Routers" not in output
