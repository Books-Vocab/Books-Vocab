from __future__ import annotations

import asyncio
import collections
import time

from dotenv import load_dotenv

from .settings import RateLimitSettingsSnapshot, load_rate_limit_settings


class RateLimiter:
    """In-memory per-key sliding window rate limiter.

    Memory hygiene and overflow policy (#2056):
    - `_requests` is kept ordered by each key's newest *admitted* timestamp
      (a key moves to the end only when it is admitted). Expired keys are
      therefore always a prefix, so reclaiming them is exact and amortized
      O(1): every pop permanently removes a dead key.
    - An active window is never evicted. Evicting one hands the key its full
      allowance back, so cycling `max_keys + 1` identities would bypass the
      limiter indefinitely.
    - A new key arriving at the cap first reclaims expired keys from the front.
      If the table is still full, the key is charged to a single shared
      overflow bucket with its own limit (`overflow_max_requests`, default
      `max_requests`) instead of being tracked. Unseen keys therefore fail
      closed under a key flood, while already-tracked keys are never denied
      because of other keys, and memory stays bounded (`max_keys` windows plus
      one overflow window of at most `overflow_max_requests` entries).
    - Trade-off: during such a flood, genuinely new clients share one budget
      and may get 429 until older windows expire. That is the price of not
      letting a flood buy fresh allowance; owning `max_keys` live keys already
      costs the attacker `max_keys * max_requests` admitted requests per
      window. Keys must still come from a source the client cannot mint for
      free (client IP or verified user id, see `app_middleware`).
    - Every `gc_interval` admissions a full sweep drops keys whose deques are
      empty or fully expired.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        max_keys: int = 10000,
        gc_interval: int = 100,
        overflow_max_requests: int | None = None,
    ):
        if max_keys < 1:
            raise ValueError("max_keys must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.gc_interval = max(1, gc_interval)
        self.overflow_max_requests = max_requests if overflow_max_requests is None else overflow_max_requests
        self._requests: collections.OrderedDict[str, collections.deque[float]] = collections.OrderedDict()
        self._overflow: collections.deque[float] = collections.deque()
        self._tick = 0
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            dq = self._requests.get(key)
            if dq is None:
                self._reclaim_expired_prefix(cutoff)
                if len(self._requests) >= self.max_keys:
                    allowed = self._charge_overflow(now, cutoff)
                else:
                    # Only track a key once it holds an admitted request, so
                    # the table stays ordered by newest admission.
                    allowed = self.max_requests > 0
                    if allowed:
                        self._requests[key] = collections.deque((now,))
            else:
                while dq and dq[0] < cutoff:
                    dq.popleft()
                allowed = len(dq) < self.max_requests
                if allowed:
                    dq.append(now)
                    self._requests.move_to_end(key)

            self._tick += 1
            if self._tick >= self.gc_interval:
                self._tick = 0
                self._gc(cutoff)

            return allowed

    def _reclaim_expired_prefix(self, cutoff: float) -> None:
        """Pop expired keys off the front (table is ordered by newest admission)."""
        requests = self._requests
        while requests:
            oldest = next(iter(requests.values()))
            if oldest and oldest[-1] >= cutoff:
                return
            requests.popitem(last=False)

    def _charge_overflow(self, now: float, cutoff: float) -> bool:
        """Charge an unseen key to the shared overflow window (fail closed when spent)."""
        overflow = self._overflow
        while overflow and overflow[0] < cutoff:
            overflow.popleft()
        if len(overflow) >= self.overflow_max_requests:
            return False
        overflow.append(now)
        return True

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
        self._overflow.clear()
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
