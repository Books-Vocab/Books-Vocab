from __future__ import annotations

import asyncio
import collections
import os
import time


class RateLimiter:
    """In-memory per-key sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, collections.deque[float]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            if key not in self._requests:
                self._requests[key] = collections.deque()
            dq = self._requests[key]
            cutoff = now - self.window_seconds
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self.max_requests:
                return False
            dq.append(now)
            return True


# 全域 limiter 實例（可透過環境變數覆蓋）
api_limiter = RateLimiter(
    max_requests=int(os.getenv("API_RATE_LIMIT", "60")),
    window_seconds=60,
)
translate_limiter = RateLimiter(
    max_requests=int(os.getenv("TRANSLATE_RATE_LIMIT", "20")),
    window_seconds=60,
)
