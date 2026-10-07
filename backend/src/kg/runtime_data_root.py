"""The data root this process's runtime SQLite stores resolve against.

The app lifespan takes the single-worker lock on ``settings.data_dir``, sweeps
that directory's orphaned rows, then binds it here until it releases the lock.
A store that builds its path from :func:`current` therefore reads and writes
exactly the directory the lock guards and the next startup's sweep recovers,
even when ``KG_DATA_DIR`` names another root.  With nothing bound (CLI and ops
tools, module-level tests with no app running) :func:`current` falls back to
:func:`kg.ops_shared.data_dir`, i.e. ``KG_DATA_DIR`` or the default.

One process-wide binding rather than a per-module override: the worker lock is
per process, so every store must agree on a single root, and a store that has
not opted in stays visible as a direct ``data_dir()`` call instead of drifting
silently.  A store opts in by resolving its path through :func:`current`.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from .ops_shared import data_dir

_lock = Lock()
_bound: Path | None = None


def bind(root: Path) -> None:
    """Point runtime stores at ``root`` (the lifespan's locked ``settings.data_dir``)."""
    global _bound
    with _lock:
        _bound = Path(root)


def release(root: Path) -> None:
    """Drop the binding made for ``root``; a binding to a different root is kept."""
    global _bound
    with _lock:
        if _bound == Path(root):
            _bound = None


def bound() -> Path | None:
    """The bound root, or ``None`` when no app lifespan holds one."""
    return _bound


def current() -> Path:
    """Root for runtime store paths: the bound root, else ``KG_DATA_DIR``/default."""
    root = _bound
    return root if root is not None else data_dir()
