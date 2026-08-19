"""Bounded per-user admission limiter for dictionary lookups."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from time import monotonic


class LexicalRateLimiter:
    def __init__(self, *, limit: int = 20, window_seconds: float = 60.0) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def admit(self, key: str) -> bool:
        now = monotonic()
        with self._lock:
            self._reap(now)
            events = self._events[key]
            while events and events[0] <= now - self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True

    @property
    def tracked_keys(self) -> int:
        with self._lock:
            self._reap(monotonic())
            return len(self._events)

    def _reap(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for key, events in list(self._events.items()):
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                self._events.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


dictionary_rate_limiter = LexicalRateLimiter()
