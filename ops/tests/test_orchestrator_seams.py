"""Structural contracts for the decomposed orchestrator runtime."""

from __future__ import annotations

import importlib.util
from collections import Counter
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "worktree_orchestrate_seams", ROOT / "ops" / "worktree_orchestrate.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

from lib import worktree_test_routes as ROUTES  # noqa: E402


@pytest.mark.parametrize(
    ("component", "children"),
    [
        (
            MODULE._runtime.orchestrator_delivery,
            {
                "integration",
                "delivery_support",
                "delivery_contracts",
                "delivery_anchor",
                "close_wave",
            },
        ),
        (
            MODULE._runtime.orchestrator_core,
            {"core_primitives", "core_gate_inputs", "core_gate_execution"},
        ),
        (
            MODULE._runtime.orchestrator_lifecycle,
            {"landing", "repair", "resolve"},
        ),
    ],
)
def test_large_runtime_seams_are_composed_of_named_children(component, children):
    assert children <= {
        name.rsplit(".", 1)[-1]
        for name, value in vars(component).items()
        if getattr(value, "__package__", None) == "lib"
    }


@pytest.mark.parametrize(
    ("relative_path", "max_lines"),
    [
        ("ops/lib/worktree_orchestrator_delivery.py", 180),
        ("ops/lib/worktree_orchestrator_integration.py", 1500),
        ("ops/lib/worktree_orchestrator_delivery_support.py", 180),
        ("ops/lib/worktree_orchestrator_delivery_contracts.py", 1000),
        ("ops/lib/worktree_orchestrator_delivery_anchor.py", 600),
        ("ops/lib/worktree_orchestrator_close_wave.py", 1350),
        ("ops/lib/worktree_orchestrator_core.py", 180),
        ("ops/lib/worktree_orchestrator_core_primitives.py", 700),
        ("ops/lib/worktree_orchestrator_core_gate_inputs.py", 450),
        ("ops/lib/worktree_orchestrator_core_gate_execution.py", 1000),
        ("ops/lib/worktree_orchestrator_lifecycle.py", 180),
        ("ops/lib/worktree_orchestrator_landing.py", 550),
        ("ops/lib/worktree_orchestrator_repair.py", 450),
        ("ops/lib/worktree_orchestrator_resolve.py", 800),
    ],
)
def test_runtime_seam_has_a_bounded_responsibility_size(relative_path, max_lines):
    path = ROOT / relative_path
    assert path.is_file(), f"missing seam module: {relative_path}"
    assert len(path.read_text(encoding="utf-8").splitlines()) <= max_lines


def test_legacy_commands_remain_reexported_from_the_facade():
    for name in (
        "cmd_integrate",
        "cmd_close_wave",
        "cmd_land",
        "cmd_catchup",
        "cmd_resolve",
        "_git",
        "_run_gate",
    ):
        assert callable(getattr(MODULE, name))


def test_legacy_collector_matches_split_behavior_collection():
    """Historical -k commands must see exactly the split test population."""
    split_files = [
        "ops/tests/test_worktree_orchestrate_planning.py",
        "ops/tests/test_worktree_orchestrate_gate.py",
        "ops/tests/test_worktree_orchestrate_lifecycle.py",
        "ops/tests/test_worktree_orchestrate_claims.py",
        "ops/tests/test_worktree_orchestrate_delivery.py",
        "ops/tests/test_worktree_orchestrate_recovery.py",
    ]

    def collected(path):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--collect-only",
                path,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        return Counter(
            line.strip().split("::", 1)[1]
            for line in result.stdout.splitlines()
            if line.strip().startswith("ops/tests/") and "::" in line
        )

    legacy = collected("ops/tests/test_worktree_orchestrate.py")
    split = Counter()
    for path in split_files:
        split.update(collected(path))
    assert legacy == split


def test_route_manifest_has_explicit_selectors_and_negative_control():
    manifest = ROUTES.route_manifest()
    assert manifest["schema"] == "kg.test.route.v1"
    assert len(manifest["routes"]) == 7
    for route in manifest["routes"]:
        assert route["route_id"]
        assert route["source_patterns"]
        assert route["pytest_nodeids"]
        assert route["selectors"]
        assert route["fallback_test_file"]
        assert route["failure_policy"] == "block"
    unknown = ROUTES.resolve_routes(["ops/lib/not-an-orchestrator.py"])
    assert unknown["fallback"] is True
    assert unknown["routes"][0]["route_id"] == "orchestrator.fallback"
    assert unknown["routes"][0]["selectors"]


def test_facade_change_unions_behavior_routes_and_missing_selector_falls_back():
    facade = ROUTES.resolve_routes(["ops/worktree_orchestrate.py"])
    assert facade["fallback"] is False
    assert {route["route_id"] for route in facade["routes"]} == {
        "orchestrator.planning",
        "orchestrator.gate",
        "orchestrator.lifecycle",
        "orchestrator.claims",
        "orchestrator.delivery",
        "orchestrator.recovery",
        "orchestrator.facade",
    }
    missing = ROUTES.resolve_routes(
        ["ops/lib/worktree_orchestrator_gate.py"], exists=lambda _path: False
    )
    assert missing["fallback"] is True


def test_route_commands_have_collection_preflight_and_stable_semantic_inputs():
    payload = ROUTES.resolve_routes(["ops/lib/worktree_orchestrator_gate.py"])
    route = payload["routes"]
    focused = ROUTES.pytest_command(route, focused=True)
    collect = ROUTES.pytest_command(route, focused=True, collect_only=True)
    assert "--collect-only" not in focused
    assert "--collect-only" in collect
    assert focused[-2:] == [
        "ops/tests/test_worktree_orchestrate_gate.py::"
        "test_shell_and_internal_gate_results_carry_duration",
    ] or focused[-1].startswith("ops/tests/")
    assert "HEAD" not in " ".join(ROUTES.runner_route_args(payload, focused=True))
