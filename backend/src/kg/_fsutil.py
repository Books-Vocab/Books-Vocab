"""Low-level filesystem durability helpers shared across persistence modules.

Centralises the directory-fsync used after an ``os.replace`` so a rename
survives a crash. A bare rename only updates an in-memory directory entry;
without a directory fsync a power loss can lose the rename itself even though
the tmp payload was already durably on disk.
"""

from __future__ import annotations

import os
from pathlib import Path


def fsync_dir(directory: Path) -> None:
    """Best-effort fsync of a directory so a rename within it is durable.

    Some filesystems disallow directory fsync (notably Windows raises) — that
    is tolerated: the tmp-file fsync already covers data durability, this only
    hardens the rename's directory entry where the platform supports it.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        # Windows / some filesystems reject fsync on a directory fd.
        pass
    finally:
        os.close(fd)
