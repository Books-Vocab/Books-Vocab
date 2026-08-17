"""Compatibility composition root for core orchestrator seams.

Git/filesystem/registry primitives and gate input/execution mechanics are separate
children; this module preserves the original import path and private helper surface.
"""

from __future__ import annotations

from types import ModuleType

from . import worktree_orchestrator_core_gate_execution as core_gate_execution
from . import worktree_orchestrator_core_gate_inputs as core_gate_inputs
from . import worktree_orchestrator_core_primitives as core_primitives

_COMPONENTS: tuple[ModuleType, ...] = (
    core_primitives,
    core_gate_inputs,
    core_gate_execution,
)


def _export(component: ModuleType, target: dict[str, object]) -> None:
    for name, value in vars(component).items():
        if not name.startswith("__") and name not in {"bind_runtime", "_COMPONENTS"}:
            target[name] = value


def bind_runtime(namespace: dict[str, object]) -> None:
    """Bind all core children to the shared runtime and re-export them."""
    for component in _COMPONENTS:
        _export(component, namespace)
    for component in _COMPONENTS:
        component.bind_runtime(namespace)
        _export(component, globals())
        _export(component, namespace)
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]

