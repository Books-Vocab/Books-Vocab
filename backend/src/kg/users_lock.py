"""Bounded acquisition of the shared ``users.json`` FileLock (#2060).

Logins, config writes, billing ingest and account deletion all serialise on
this one inter-process lock. An unbounded wait turns a single slow holder into
a stalled worker pool, so callers give up after a bounded wait and surface a
retryable 503 instead.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException
from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)

# Critical sections are a users.json load + save (milliseconds); 10s only
# trips when a holder is genuinely stuck.
USERS_LOCK_TIMEOUT_SECONDS = 10.0


def bounded_users_filelock(lock_file: str | Path) -> FileLock:
    """The users lock with a bounded wait; ``acquire`` raises ``filelock.Timeout``.

    For callers outside a request (startup migration, the ops CLI) that have no
    HTTP response to turn the timeout into: a stuck holder must fail them loudly
    rather than hang them forever. Request paths use ``users_file_lock``.
    """
    return FileLock(str(lock_file), timeout=USERS_LOCK_TIMEOUT_SECONDS)


@contextmanager
def users_file_lock(lock_file: str | Path) -> Iterator[None]:
    """Hold the users lock, or raise HTTP 503 after ``USERS_LOCK_TIMEOUT_SECONDS``."""
    lock = bounded_users_filelock(lock_file)
    try:
        lock.acquire()
    except Timeout as exc:
        logger.warning("users lock %s not acquired within %.1fs", lock_file, USERS_LOCK_TIMEOUT_SECONDS)
        raise HTTPException(
            status_code=503,
            detail="Account service busy, please retry",
            headers={"Retry-After": "1"},
        ) from exc
    try:
        yield
    finally:
        lock.release()
