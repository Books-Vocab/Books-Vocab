"""Low-level file-store primitives for :mod:`backlog`.

This module deliberately knows nothing about backlog entry validation or CLI
semantics.  It owns only path calculation, readable JSON serialization,
atomic replacement, and the two locks needed by the file store.  Keeping this
seam dependency-free makes it safe to import from the sandboxed ops tests and
prevents storage concerns from spreading through command handlers.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterator

from lib.lock_wait import LockUnavailable, exclusive_lock


class EntryLockUnavailable(RuntimeError):
    """The per-entry lock could not be acquired."""

    def __init__(self, path: Path, cause: BaseException) -> None:
        self.path = path
        self.cause = cause
        super().__init__(f"entry lock unavailable for {path.name}: {cause}")


def entry_path(store: Path, entry_id: str) -> Path:
    """Return the one-file-per-entry path for ``entry_id``."""
    return Path(store) / f"{entry_id}.json"


def dumps(payload: dict) -> str:
    """Serialize an entry in the human-readable, git-friendly form."""
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@contextlib.contextmanager
def view_lock(root: Path) -> Iterator[bool]:
    """Serialize the shared generated-view refresh cycle.

    The lock is advisory and fail-open by design.  Mutations have already
    landed by the time a view refresh runs, so an unavailable refresh lock
    must not turn a successful mutation into a reported write failure.
    """
    lock_path = Path(root) / ".cache" / "backlog_view.lock"
    with exclusive_lock(lock_path, label="backlog-view", fail_closed=False) as acquired:
        yield acquired


def write_atomic(path: Path, text: str) -> None:
    """Replace ``path`` atomically without changing its existing mode."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        mode = path.stat().st_mode & 0o7777
    except OSError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


@contextlib.contextmanager
def entry_lock(root: Path, path: Path) -> Iterator[None]:
    """Serialize create-or-reuse for one entry path and fail closed."""
    path = Path(path)
    key = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()
    lock_path = Path(root) / ".cache" / "backlog_entry_locks" / f"{key}.lock"
    try:
        with exclusive_lock(lock_path, label=f"backlog-entry:{path.name}"):
            yield
    except LockUnavailable as exc:
        raise EntryLockUnavailable(path, exc) from exc
