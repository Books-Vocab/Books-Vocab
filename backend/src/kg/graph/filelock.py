"""Process-level advisory file locking for the graph store.

``threading.Lock`` only serialises writers *within one GraphStore instance*.
Two instances of ``GraphStore`` pointing at the same files (pipeline run +
API request after an LRU eviction, or two uvicorn workers) each hold their
own lock and their own in-memory snapshot -- a whole-file flush from one
silently overwrites the other's changes.

``fcntl.flock`` is an OS-level advisory lock keyed by the underlying file
description, so it serialises writers *across instances and across
processes* on the same machine. Stdlib only -- no new dependency.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

try:  # POSIX
    import fcntl

    _HAVE_FCNTL = True
except ImportError as exc:  # pragma: no cover -- Windows fallback
    logging.getLogger(__name__).warning("fcntl unavailable; file locks disabled (Windows fallback)", exc_info=True)
    fcntl = None  # type: ignore[assignment]
    _HAVE_FCNTL = False


@contextmanager
def path_write_lock(target: Path) -> Iterator[None]:
    """Exclusive advisory lock scoped to ``target``'s sibling ``.lock`` file.

    The lock file is separate from the data file so the lock survives the
    ``tmp -> replace`` rename dance (which swaps the data file's inode).

    On platforms without ``fcntl`` the context manager is a no-op -- the
    in-process ``threading.Lock`` still applies, matching prior behaviour.
    """
    if not _HAVE_FCNTL:  # pragma: no cover -- Windows
        yield
        return

    lock_path = target.with_name(target.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Append mode: we only need a live fd for flock and never write to the
    # lock file, so opening with O_TRUNC ("w") would needlessly truncate a
    # file other holders may have open. "a" creates-if-absent without truncating.
    fd = open(lock_path, "a")  # noqa: SIM115 -- closed in finally
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        finally:
            fd.close()
