from __future__ import annotations

import importlib.util
from pathlib import Path
import copy

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
    assert mod.canonical_role("cm") == "manager"
    assert mod.canonical_role("IM") == "manager"
    assert mod.canonical_role("im") == "manager"
    assert mod.canonical_role("Worker") == "contributor"
    assert mod.canonical_role("worker") == "contributor"
    assert mod.canonical_role("Issue Solver") == "contributor"
    assert mod.canonical_role("issue-solver") == "contributor"
    assert mod.canonical_role("CR") == "reviewer"
    assert mod.canonical_role("cr") == "reviewer"
    assert mod.canonical_role("DS") == "docs-steward"
    assert mod.canonical_role("ds") == "docs-steward"


def test_manifest_has_project_onboarding_and_canonical_identity_boundaries() -> None:
    manifest = mod.load_manifest(ROOT)
    assert manifest["schema"] == "kg.context_plane.v4"
    assert manifest["onboarding"] == {
        "source": "docs/reference/project_onboarding.md",
        "required": True,
    }
    assert set(manifest["identities"]) == {
        "cm", "im", "worker", "issue-solver", "cr", "ds", "release-operator"
    }
    assert manifest["roles"]["manager"]["identity_ids"] == ["cm", "im"]
    assert manifest["roles"]["contributor"]["identity_ids"] == ["worker", "issue-solver"]
    for identity in ("cm", "im", "worker", "issue-solver"):
        definition = manifest["identities"][identity]
        assert definition["allowed_surfaces"]
        assert definition["forbidden_surfaces"]
        assert not set(definition["allowed_surfaces"]) & set(definition["forbidden_surfaces"])
        assert definition["handoff_contract"]["input"]
        assert definition["handoff_contract"]["output"]


def test_worker_manifest_declares_both_dispatch_channels_and_hand_back_policies() -> None:
    worker = mod.load_manifest(ROOT)["identities"]["worker"]
    assert "dispatch_channel" in worker["assignment_requirements"]["direct-assignment"]
    assert worker["handoff_contract"]["dispatch_channels"] == {
        "im": {
            "discussion_with": "dispatching IM",
            "handback_policy": "same-dispatching-im",
        },
        "user": {
            "discussion_with": "User",
            "handback_policy": "specified-or-worker-selected-im",
        },
    }


def test_worker_dispatch_contract_fails_closed_when_a_channel_drifts() -> None:
    manifest = copy.deepcopy(mod.load_manifest(ROOT))
    del manifest["identities"]["worker"]["handoff_contract"]["dispatch_channels"]["user"]

    with pytest.raises(mod.ContextRouteError, match="dispatch_channels"):
        mod.validate_manifest(manifest, ROOT)


def test_route_is_github_native_and_does_not_grant_authority() -> None:
    payload = mod.resolve_route(mod.load_manifest(ROOT), "manager", intent="delivery", root=ROOT)
    assert payload["schema"] == "kg.context.route.v3"
    assert payload["status"] == "confirmed"
    assert payload["skill"] == "github-coordination"
    assert payload["skill_intent"] == "github-coordination"
    assert payload["sources"][0] == "docs/reference/project_onboarding.md"
    assert payload["onboarding"]["required"] is True
    assert payload["authority"]["granted"] is False
    assert "docs/runbook/system.md" in payload["sources"]
    assert [step["phase"] for step in payload["load_order"]] == ["project", "identity", "skill", "domain"]
    assert payload["skill_route"]["primary"] == "github-coordination"
    assert payload["route_selection"]["identity"] is None


def test_ambiguous_role_route_fails_closed_and_exact_identity_entry_resolves() -> None:
    manifest = mod.load_manifest(ROOT)
    with pytest.raises(mod.ContextRouteError, match="請提供 --identity 與 --entry"):
        mod.resolve_route(manifest, "manager", intent="release", root=ROOT)

    payload = mod.resolve_route(
        manifest,
        "manager",
        intent="release",
        identity="CM",
        entry="merge",
        root=ROOT,
    )
    assert payload["skill"] == "source-command-release"
    assert payload["route_selection"]["identity"] == "cm"
    assert payload["route_selection"]["entry"] == "merge"


def test_surface_aliases_are_bounded() -> None:
    payload = mod.resolve_route(mod.load_manifest(ROOT), "contributor", surface="backend", root=ROOT)
    assert payload["intent"] == "backend"
    assert "docs/reference/tech_index.md" in payload["sources"]


def test_every_context_intent_cross_validates_to_a_real_primary_skill() -> None:
    manifest = mod.load_manifest(ROOT)
    expected = {
        "delivery": "github-coordination",
        "review": "code-review",
        "docs": "kg-docs-control-plane",
        "release": "source-command-release",
        "backend": "worktree-flow",
        "ios": "ios-simulator-verification",
    }
    for intent, primary in expected.items():
        role = {
            "delivery": "manager",
            "review": "reviewer",
            "docs": "docs-steward",
            "release": "manager",
            "backend": "contributor",
            "ios": "contributor",
        }[intent]
        kwargs = {"identity": "CM", "entry": "merge"} if intent == "release" else {}
        payload = mod.resolve_route(manifest, role, intent=intent, root=ROOT, **kwargs)
        assert payload["schema"] == "kg.context.route.v3"
        assert payload["skill"] == primary
        assert payload["skill_intent"]
        assert payload["sources"][0] == "docs/reference/project_onboarding.md"
    ios_route = mod.resolve_route(manifest, "contributor", intent="ios", root=ROOT)
    assert ios_route["skill_route"]["selected"] == [
        "kg-router", "worktree-flow", "ios-simulator-verification"
    ]


def test_skill_override_and_work_mode_cannot_bypass_context_contract() -> None:
    manifest = mod.load_manifest(ROOT)
    with pytest.raises(mod.ContextRouteError, match="skill 與 intent route"):
        mod.resolve_route(manifest, "reviewer", intent="review", skill="devops", root=ROOT)
    with pytest.raises(mod.ContextRouteError, match="role 不允許 intent"):
        mod.resolve_route(manifest, "reviewer", intent="docs", root=ROOT)
    with pytest.raises(mod.ContextRouteError, match="work_mode"):
        mod.resolve_route(manifest, "reviewer", intent="review", work_mode="production-write", root=ROOT)


def test_all_canonical_identities_and_aliases_resolve() -> None:
    manifest = mod.load_manifest(ROOT)
    aliases = {
        "CM": "cm",
        "IM": "im",
        "Worker": "worker",
        "Issue Solver": "issue-solver",
        "CR": "cr",
        "DS": "ds",
        "Release operator": "release-operator",
    }
    for alias, expected in aliases.items():
        assert mod.canonical_agent_identity(manifest, alias) == expected


def test_identity_skill_route_cannot_drift_from_route_policy() -> None:
    manifest = copy.deepcopy(mod.load_manifest(ROOT))
    manifest["identities"]["cr"]["skill_routes"]["review"]["pr-review"] = "release-command"
    with pytest.raises(mod.ContextRouteError, match="route_policy"):
        mod.validate_manifest(manifest, ROOT)


def test_unknown_role_and_work_mode_fail_closed() -> None:
    with pytest.raises(mod.ContextRouteError):
        mod.canonical_role("unknown")
    with pytest.raises(mod.ContextRouteError):
        mod.normalize_role_identity("manager", "unexpected")


def test_cli_routes_are_maintainer_diagnostics_only(capsys) -> None:
    assert mod.main(["route", "--role", "manager", "--intent", "delivery"]) == 2
    assert "agent_onboard.py" in capsys.readouterr().err
    assert mod.main(["route", "--diagnostic", "--role", "manager", "--intent", "delivery", "--json"]) == 0
    assert '"skill": "github-coordination"' in capsys.readouterr().out
    assert mod.main(["identify", "--role", "manager"]) == 2
    assert "agent_onboard.py" in capsys.readouterr().err
