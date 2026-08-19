from __future__ import annotations

import asyncio
import collections
import time

from dotenv import load_dotenv

from .settings import RateLimitSettingsSnapshot, load_rate_limit_settings


class RateLimiter:
    """In-memory per-key sliding window rate limiter.

    Memory hygiene:
    - Every `gc_interval` admissions, sweep `_requests` and drop keys whose
      deques are empty or fully expired.
    - Hard cap at `max_keys`: reclaim expired keys before admitting a new key;
      if all slots are active, reject the new key rather than evicting an
      active window.
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
                if len(self._requests) >= self.max_keys:
                    # A full table may contain entries that have expired since
                    # the last scheduled sweep. Reclaim them before deciding
                    # whether this new key can be tracked.
                    self._gc(cutoff)
                if len(self._requests) >= self.max_keys:
                    # Never reset an active key's window just to admit a new
                    # key. Failing closed preserves the bounded-table
                    # invariant and the existing keys' rate-limit history.
                    return False
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

            return allowed

    def _gc(self, cutoff: float) -> None:
        """Sweep keys whose deques are empty or fully expired."""
        # A deque is dead if empty or its newest entry is older than cutoff.
        dead = [k for k, dq in self._requests.items() if not dq or dq[-1] < cutoff]
        for k in dead:
            self._requests.pop(k, None)

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


# 全域 limiter 實例；環境值已在 typed rate-limit settings snapshot 中解析。
# kg.api imports this module before its own load_dotenv() call, so local `.env`
# values must be available before the settings snapshot is created.
load_dotenv()
_settings_snapshot: RateLimitSettingsSnapshot = load_rate_limit_settings()
api_limiter = RateLimiter(
    max_requests=_settings_snapshot.api_rate_limit,
    window_seconds=60,
)
translate_limiter = RateLimiter(
    max_requests=_settings_snapshot.translate_rate_limit,
    window_seconds=60,
)
# Dedicated low-threshold limiter for POST /admin/login. The admin password is a
# single shared online-guessable secret, so the generic api_limiter (60/min) is
# far too loose to slow credential stuffing. Default 5/min/IP, env-overridable.
login_limiter = RateLimiter(
    max_requests=_settings_snapshot.admin_login_rate_limit,
    window_seconds=60,
)
