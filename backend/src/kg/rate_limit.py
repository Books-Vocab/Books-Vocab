from __future__ import annotations

import asyncio
import collections
import os
import time


class RateLimiter:
    """In-memory per-key sliding window rate limiter.

    Memory hygiene:
    - Every `gc_interval` admissions, sweep `_requests` and drop keys whose
      deques are empty or fully expired.
    - Hard cap at `max_keys`: if the dict exceeds the cap after GC, evict
      least-recently-used keys (OrderedDict insertion-order, with
      move_to_end on each touch).
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        max_keys: int = 10000,
        gc_interval: int = 100,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.gc_interval = max(1, gc_interval)
        self._requests: collections.OrderedDict[
            str, collections.deque[float]
        ] = collections.OrderedDict()
        self._tick = 0
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            dq = self._requests.get(key)
            if dq is None:
                dq = collections.deque()
                self._requests[key] = dq
            else:
                self._requests.move_to_end(key)
            while dq and dq[0] < cutoff:
                dq.popleft()
            allowed = len(dq) < self.max_requests
            if allowed:
                dq.append(now)

            self._tick += 1
            if self._tick >= self.gc_interval:
                self._tick = 0
                self._gc(cutoff)
            if len(self._requests) > self.max_keys:
                self._enforce_cap()

            return allowed

    def _gc(self, cutoff: float) -> None:
        """Sweep keys whose deques are empty or fully expired."""
        # A deque is dead if empty or its newest entry is older than cutoff.
        dead = [k for k, dq in self._requests.items() if not dq or dq[-1] < cutoff]
        for k in dead:
            self._requests.pop(k, None)

    def _enforce_cap(self) -> None:
        """Evict least-recently-used keys until under cap."""
        while len(self._requests) > self.max_keys:
            self._requests.popitem(last=False)

    def reset(self) -> None:
        """Drop all tracked windows and reset the GC tick counter.

        Intended as a test-isolation seam: the module-level limiter singletons
        are shared process-wide, so a long-running test session accumulates
        admissions across unrelated tests and can trip the window. Production
        code never needs this — restarting the process is the only other reset.
        Synchronous + lock-free on purpose: callers invoke it between tests
        when no request is in flight, so taking the asyncio lock is unnecessary
        (and would require an event loop).
        """
        self._requests.clear()
        self._tick = 0


# 全域 limiter 實例（可透過環境變數覆蓋）
api_limiter = RateLimiter(
    max_requests=int(os.getenv("API_RATE_LIMIT", "60")),
    window_seconds=60,
)
translate_limiter = RateLimiter(
    max_requests=int(os.getenv("TRANSLATE_RATE_LIMIT", "20")),
    window_seconds=60,
)
# Dedicated low-threshold limiter for POST /admin/login. The admin password is a
# single shared online-guessable secret, so the generic api_limiter (60/min) is
# far too loose to slow credential stuffing. Default 5/min/IP, env-overridable.
login_limiter = RateLimiter(
    max_requests=int(os.getenv("ADMIN_LOGIN_RATE_LIMIT", "5")),
    window_seconds=60,
)
