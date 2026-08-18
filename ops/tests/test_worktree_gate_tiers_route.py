from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import worktree_test_routes as routes


def _route_ids(payload: dict[str, object]) -> set[str]:
    return {
        str(route["route_id"])
        for route in payload["routes"]  # type: ignore[index]
    }


def test_gate_tiers_source_uses_an_explicit_route_not_the_facade() -> None:
    payload = routes.resolve_routes(["ops/lib/worktree_gate_tiers.py"])

    assert payload["fallback"] is False
    assert _route_ids(payload) == {"orchestrator.gate-tiers"}
    route = payload["routes"][0]  # type: ignore[index]
    assert route["selectors"] == [
        "ops/tests/test_worktree_gate_tiers.py",
        "ops/tests/test_worktree_gate_tiers_route.py",
    ]
    assert route["fallback_test_file"] == "ops/tests/test_worktree_gate_tiers.py"


def test_unknown_and_legacy_route_ids_keep_the_complete_fallback() -> None:
    for route_id in ("orchestrator.unknown", "orchestrator.legacy"):
        selected = routes.routes_for_ids([route_id])

        assert [route["route_id"] for route in selected] == ["orchestrator.fallback"]


def test_legacy_collector_path_keeps_its_existing_behavior_routes() -> None:
    payload = routes.resolve_routes(["ops/tests/test_worktree_orchestrate.py"])

    assert payload["fallback"] is False
    assert _route_ids(payload) == {
        "orchestrator.claims",
        "orchestrator.delivery",
        "orchestrator.gate",
        "orchestrator.lifecycle",
        "orchestrator.planning",
        "orchestrator.recovery",
    }
