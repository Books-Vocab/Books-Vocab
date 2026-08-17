"""Structural contracts for the decomposed orchestrator runtime."""

from __future__ import annotations

import importlib.util
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
