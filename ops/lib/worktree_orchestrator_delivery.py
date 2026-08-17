"""Compatibility composition root for delivery orchestration seams.

The public command names and historical private patch points stay available from
this module, while each delivery responsibility owns a bounded implementation:
integration state, phase receipts, close-wave contracts, anchor/commit, and sync.
"""

from __future__ import annotations

from types import ModuleType

from . import worktree_orchestrator_close_wave as close_wave
from . import worktree_orchestrator_delivery_anchor as delivery_anchor
from . import worktree_orchestrator_delivery_contracts as delivery_contracts
from . import worktree_orchestrator_delivery_support as delivery_support
from . import worktree_orchestrator_integration as integration

_COMPONENTS: tuple[ModuleType, ...] = (
    integration,
    delivery_support,
    delivery_contracts,
    delivery_anchor,
    close_wave,
)


def _export(component: ModuleType, target: dict[str, object]) -> None:
    for name, value in vars(component).items():
        if not name.startswith("__") and name not in {"bind_runtime", "_COMPONENTS"}:
            target[name] = value


def bind_runtime(namespace: dict[str, object]) -> None:
    """Bind all delivery children to the shared runtime and re-export them."""
    # Seed every child name before binding any child.  Delivery support and the
    # close-wave command intentionally depend on helpers from neighbouring seams;
    # a one-pass bind made that dependency order observable as a NameError.
    for component in _COMPONENTS:
        _export(component, namespace)
    for component in _COMPONENTS:
        component.bind_runtime(namespace)
        _export(component, globals())
        _export(component, namespace)
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]
