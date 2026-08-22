"""Cross-process serialization for delivery-control mutations.

The delivery CLI can be invoked concurrently by a supervisor, an integrator,
or a cleanup retry.  Registry CAS protects the ledger, but Git operations such
as sync, worktree removal, and branch deletion still share the repository's
index and refs.  This lock serializes those command-level mutations while
leaving observation commands concurrent.  The kernel releases the lock when
the owning process exits, so a stale lock file is harmless.
"""

from __future__ import annotations

import errno
import fcntl
from pathlib import Path
from types import TracebackType
from typing import IO, Self

from ..domain.errors import DeliverySourceError


# The delivery CLI owns the process-wide lease while the registry adapter can
# invoke the registry CLI in-process during that same mutation.  Re-entering
# here must share the existing kernel handle; other processes still contend on
# the flock.
_HELD_LOCKS: dict[Path, tuple[IO[str], int]] = {}


class OperationLock:
    """Acquire one non-blocking mutation lease for a canonical repository."""

    def __init__(self, repo: Path, *, command: str) -> None:
        self.repo = repo.expanduser().resolve()
        self.command = command
        self.path = self.repo / ".cache" / "delivery-control.operation.lock"
        self._handle: IO[str] | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        held = _HELD_LOCKS.get(self.path)
        if held is not None:
            handle, depth = held
            _HELD_LOCKS[self.path] = (handle, depth + 1)
            self._handle = handle
            return self

        handle = self.path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                raise DeliverySourceError(
                    "delivery mutation already in progress; "
                    f"command={self.command}; retry after the active operation exits"
                ) from error
            raise
        _HELD_LOCKS[self.path] = (handle, 1)
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        handle = self._handle
        self._handle = None
        if handle is None:
            return False

        held = _HELD_LOCKS.get(self.path)
        if held is None or held[0] is not handle:
            raise RuntimeError("operation lock ownership state is corrupted")
        _, depth = held
        if depth > 1:
            _HELD_LOCKS[self.path] = (handle, depth - 1)
        else:
            del _HELD_LOCKS[self.path]
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        return False


__all__ = ["OperationLock"]
