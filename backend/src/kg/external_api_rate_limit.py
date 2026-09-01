"""Per-API-key sliding-window limits for the versioned external API."""

from __future__ import annotations

import asyncio
import collections
import math
import os
import time
from dataclasses import dataclass


def _positive_env(name: str, default: int, *, maximum: int = 10_000) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        value = default
    return max(1, min(value, maximum))


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "Retry-After": str(self.retry_after),
        }


class ExternalRateLimiter:
    """Small process-local limiter with bounded key memory.

    The existing deployment is single-worker. This limiter follows the same
    process-local boundary as the backend API limiter; a later multi-worker
    deployment must move this state to a shared store before claiming a global
    limit.
    """

    def __init__(self, *, limit: int, window_seconds: int, max_keys: int = 20_000) -> None:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive")
        if max_keys <= 0:
            raise ValueError("max_keys must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._events: collections.OrderedDict[str, collections.deque[float]] = collections.OrderedDict()
        self._lock = asyncio.Lock()

    async def admit(self, key: str) -> RateLimitDecision:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            events = self._events.get(key)
            if events is None:
                if len(self._events) >= self.max_keys:
                    self._gc(cutoff)
                if len(self._events) >= self.max_keys:
                    return RateLimitDecision(False, self.limit, 0, 1)
                events = collections.deque()
                self._events[key] = events
            else:
                self._events.move_to_end(key)
            while events and events[0] <= cutoff:
                events.popleft()

            if len(events) >= self.limit:
                retry_after = max(1, math.ceil(events[0] + self.window_seconds - now))
                decision = RateLimitDecision(False, self.limit, 0, retry_after)
            else:
                events.append(now)
                decision = RateLimitDecision(
                    True,
                    self.limit,
                    max(0, self.limit - len(events)),
                    0,
                )

            self._gc(cutoff)
            while len(self._events) > self.max_keys:
                self._events.popitem(last=False)
            return decision

    def _gc(self, cutoff: float) -> None:
        for key, events in list(self._events.items()):
            if not events or events[-1] <= cutoff:
                self._events.pop(key, None)

    def reset(self) -> None:
        self._events.clear()


read_limiter = ExternalRateLimiter(
    limit=_positive_env("KG_EXTERNAL_API_READ_RATE_LIMIT", 120),
    window_seconds=_positive_env("KG_EXTERNAL_API_READ_WINDOW_SECONDS", 60, maximum=86_400),
)
write_limiter = ExternalRateLimiter(
    limit=_positive_env("KG_EXTERNAL_API_WRITE_RATE_LIMIT", 30),
    window_seconds=_positive_env("KG_EXTERNAL_API_WRITE_WINDOW_SECONDS", 60, maximum=86_400),
)
enrich_limiter = ExternalRateLimiter(
    limit=_positive_env("KG_EXTERNAL_API_ENRICH_RATE_LIMIT", 5),
    window_seconds=_positive_env("KG_EXTERNAL_API_ENRICH_WINDOW_SECONDS", 300, maximum=86_400),
)


__all__ = [
    "ExternalRateLimiter",
    "RateLimitDecision",
    "enrich_limiter",
    "read_limiter",
    "write_limiter",
]
