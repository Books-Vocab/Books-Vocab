"""Shared, observable flock acquisition for concurrent KG tools.

The registry and backlog are deliberately local-file coordination planes.  A
contended lock is therefore normal work, not a command error.  This module
waits without a busy retry loop, backs off exponentially, and reports only a
small stderr heartbeat so machine-readable stdout remains untouched.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import sys
import time
from pathlib import Path
from typing import Iterator


class LockUnavailable(OSError):
    """The lock could not be created or acquired for a non-contention reason."""


def _is_busy(error: OSError) -> bool:
    return isinstance(error, BlockingIOError) or error.errno in (errno.EACCES, errno.EAGAIN)


@contextlib.contextmanager
def exclusive_lock(
    path: Path,
    *,
    label: str,
    fail_closed: bool = True,
    initial_delay: float = 0.25,
    max_delay: float = 30.0,
    heartbeat_interval: float = 20.0,
) -> Iterator[bool]:
    """Hold an exclusive advisory lock, waiting with exponential backoff.

    The yielded value is ``True`` when the lock is held.  With
    ``fail_closed=False`` only a non-contention acquisition error yields
    ``False``; contention still waits, because silently proceeding while a
    read-modify-write lock is held would lose data.  ``LockUnavailable`` is
    raised for the fail-closed variant.
    """
    lock_path = Path(path)
    fd: int | None = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as error:
        if fail_closed:
            raise LockUnavailable(f"{label}: cannot open lock {lock_path}: {error}") from error
        print(
            f"[lock] label={label} phase=unavailable path={lock_path} error={error}",
            file=sys.stderr,
            flush=True,
        )
        yield False
        return

    started = time.monotonic()
    delay = max(0.01, initial_delay)
    waited = False
    last_heartbeat = started - heartbeat_interval
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                if waited:
                    elapsed = time.monotonic() - started
                    print(
                        f"[lock] label={label} phase=acquired elapsed={elapsed:.1f}s "
                        f"pid={os.getpid()}",
                        file=sys.stderr,
                        flush=True,
                    )
                break
            except OSError as error:
                if not _is_busy(error):
                    if fail_closed:
                        raise LockUnavailable(
                            f"{label}: cannot acquire lock {lock_path}: {error}"
                        ) from error
                    print(
                        f"[lock] label={label} phase=unavailable path={lock_path} error={error}",
                        file=sys.stderr,
                        flush=True,
                    )
                    yield False
                    return

            waited = True
            now = time.monotonic()
            if now >= last_heartbeat + heartbeat_interval:
                elapsed = now - started
                print(
                    f"[lock] label={label} phase=waiting elapsed={elapsed:.1f}s "
                    f"pid={os.getpid()} next={delay:.2f}s",
                    file=sys.stderr,
                    flush=True,
                )
                last_heartbeat = now
            time.sleep(delay)
            delay = min(max_delay, delay * 2)

        yield acquired
    finally:
        if fd is not None:
            if acquired:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
