"""Compatibility composition root for lifecycle orchestration seams.

Landing/catchup, post-landing repair, and teardown/audit are separate children while
the historical lifecycle module remains the stable import and patching surface.
"""

from __future__ import annotations

from types import ModuleType

from . import worktree_orchestrator_landing as landing
from . import worktree_orchestrator_repair as repair
from . import worktree_orchestrator_resolve as resolve

_COMPONENTS: tuple[ModuleType, ...] = (landing, repair, resolve)


def _export(component: ModuleType, target: dict[str, object]) -> None:
    for name, value in vars(component).items():
        if not name.startswith("__") and name not in {"bind_runtime", "_COMPONENTS"}:
            target[name] = value


def bind_runtime(namespace: dict[str, object]) -> None:
    """Bind all lifecycle children to the shared runtime and re-export them."""
    for component in _COMPONENTS:
        _export(component, namespace)
    for component in _COMPONENTS:
        component.bind_runtime(namespace)
        _export(component, globals())
        _export(component, namespace)
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]

