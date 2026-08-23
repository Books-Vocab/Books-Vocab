"""Cross-process locks for test groups that share mutable test fixtures."""

from __future__ import annotations

import fcntl
import re
from pathlib import Path
from typing import IO, Self

_LOCK_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


class TestExecutionLock:
    """Block competing test groups without changing production lock semantics."""

    __test__ = False

    def __init__(self, repo: Path, lock_name: str) -> None:
        if not isinstance(lock_name, str) or _LOCK_NAME.fullmatch(lock_name) is None:
            raise ValueError(f"invalid test lock name: {lock_name!r}")
        self.path = (
            repo.expanduser().resolve()
            / ".cache"
            / (f"test-execution.{lock_name}.lock")
        )
        self._handle: IO[str] | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except BaseException:
            handle.close()
            raise
        self._handle = handle
        return self

    def __exit__(self, *_: object) -> bool:
        handle = self._handle
        self._handle = None
        if handle is None:
            return False
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
        return False


__all__ = ["TestExecutionLock"]
