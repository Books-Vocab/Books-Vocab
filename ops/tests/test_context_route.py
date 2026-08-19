from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "context_route.py"
SPEC = importlib.util.spec_from_file_location("context_route", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_manifest_is_valid_and_has_bounded_roles() -> None:
    manifest = mod.load_manifest(ROOT)
    assert set(manifest["roles"]) == {
        "manager", "contributor", "reviewer", "docs-steward", "release-operator"
    }
    assert mod.canonical_role("Manager") == "manager"
    assert mod.canonical_role("CM") == "manager"
    assert mod.canonical_role("IM") == "manager"
    assert mod.canonical_role("Worker") == "contributor"
    assert mod.canonical_role("Issue Solver") == "contributor"
    assert mod.canonical_role("CR") == "reviewer"
    assert mod.canonical_role("DS") == "docs-steward"


def test_route_is_github_native_and_does_not_grant_authority() -> None:
    payload = mod.resolve_route(mod.load_manifest(ROOT), "manager", intent="delivery", root=ROOT)
    assert payload["schema"] == "kg.context.route.v2"
    assert payload["status"] == "confirmed"
    assert payload["skill"] == "worktree-flow"
    assert payload["authority"]["granted"] is False
    assert "docs/runbook/system.md" in payload["sources"]


def test_surface_aliases_are_bounded() -> None:
    payload = mod.resolve_route(mod.load_manifest(ROOT), "contributor", surface="backend", root=ROOT)
    assert payload["intent"] == "backend"
    assert "docs/reference/tech_index.md" in payload["sources"]


def test_unknown_role_and_work_mode_fail_closed() -> None:
    with pytest.raises(mod.ContextRouteError):
        mod.canonical_role("unknown")
    with pytest.raises(mod.ContextRouteError):
        mod.normalize_role_identity("manager", "unexpected")
