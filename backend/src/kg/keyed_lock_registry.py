"""Bounded, reclaimable in-process locks keyed by a resource identity."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


class KeyedLockRegistryFull(RuntimeError):
    """Raised when every registry slot is held by another key."""


@dataclass
class _Entry:
    lock: threading.RLock
    users: int = 0


class KeyedLockRegistry:
    """Share locks by key without retaining an unbounded key-to-lock map.

    A registry slot is reserved for every active or waiting context.  The
    slot is removed as soon as the last context for that key exits, so the
    registry never keeps idle resource keys alive.  If all slots are active,
    a new key fails closed instead of growing beyond ``max_keys``.
    """

    def __init__(self, *, max_keys: int = 256) -> None:
        if max_keys < 1:
            raise ValueError("max_keys must be positive")
        self._max_keys = max_keys
        self._guard = threading.Lock()
        self._entries: dict[str, _Entry] = {}

    @property
    def max_keys(self) -> int:
        return self._max_keys

    @property
    def size(self) -> int:
        with self._guard:
            return len(self._entries)

    @contextmanager
    def lock(self, key: object) -> Iterator[None]:
        normalized_key = str(key)
        entry = self._retain(normalized_key)
        try:
            with entry.lock:
                yield
        finally:
            self._release(normalized_key, entry)

    def _retain(self, key: str) -> _Entry:
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                if len(self._entries) >= self._max_keys:
                    raise KeyedLockRegistryFull(
                        f"keyed lock registry capacity exhausted ({self._max_keys})"
                    )
                entry = _Entry(threading.RLock())
                self._entries[key] = entry
            entry.users += 1
            return entry

    def _release(self, key: str, entry: _Entry) -> None:
        with self._guard:
            entry.users -= 1
            if entry.users == 0 and self._entries.get(key) is entry:
                del self._entries[key]


DICTIONARY_LOCK_REGISTRY = KeyedLockRegistry(max_keys=256)


__all__ = [
    "DICTIONARY_LOCK_REGISTRY",
    "KeyedLockRegistry",
    "KeyedLockRegistryFull",
]
