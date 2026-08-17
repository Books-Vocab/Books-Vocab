#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Stable executable façade for the worktree orchestrator.

The implementation lives under ``ops/lib`` so the historical CLI path remains a
small, auditable compatibility boundary.  Symbols are re-exported deliberately:
existing tests and callers patch private seams on this module, and the façade
propagates those patches to the implementation module before execution.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

_OPS_DIR = Path(__file__).resolve().parent
for _path in (str(_OPS_DIR), str(_OPS_DIR / "lib")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from lib import worktree_orchestrator_runtime as _runtime  # noqa: E402

# Runtime provenance is intentionally the façade path.  The executable contract is
# the stable ops/worktree_orchestrate.py surface, including its content fingerprint.
_runtime.__file__ = __file__
_runtime.orchestrator_core.__file__ = __file__
_COMPONENTS: list[types.ModuleType] = [_runtime]


def _copy_exports(component: types.ModuleType) -> None:
    for _name, _value in vars(component).items():
        if not _name.startswith("__"):
            globals()[_name] = _value


def _register_component(component: types.ModuleType) -> None:
    if component not in _COMPONENTS:
        _COMPONENTS.append(component)
    _copy_exports(component)


_copy_exports(_runtime)
_register_component(_runtime.planning)
_register_component(_runtime.orchestrator_core)


class _FacadeModule(types.ModuleType):
    """Keep legacy monkeypatch seams coherent across extracted components."""

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name.startswith("__"):
            return
        for _component in _COMPONENTS:
            if name in vars(_component):
                setattr(_component, name, value)

    def __getattr__(self, name: str) -> object:
        for _component in _COMPONENTS:
            if name in vars(_component):
                return vars(_component)[name]
        raise AttributeError(name)

    def __dir__(self) -> list[str]:
        names = set(super().__dir__())
        for _component in _COMPONENTS:
            names.update(vars(_component))
        return sorted(names)


_MODULE = sys.modules.get(__name__)
if _MODULE is not None:
    _MODULE.__class__ = _FacadeModule


if __name__ == "__main__":
    raise SystemExit(main())
