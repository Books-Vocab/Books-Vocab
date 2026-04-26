"""
Tests for RateLimiter GC + size cap (memory leak prevention).

Goal: `_requests` dict must not grow unbounded. Expired keys are
periodically swept (lazy GC), and a hard size cap evicts the
least-recently-used keys.
"""

from __future__ import annotations

import asyncio
import time

from kg.rate_limit import RateLimiter


class TestRateLimiterGC:

    def test_expired_keys_are_swept_under_size_cap(self):
        """Adding many unique expired keys should not blow the dict past
        the configured size cap."""
        async def run():
            limiter = RateLimiter(
                max_requests=5,
                window_seconds=1,
                max_keys=500,
                gc_interval=100,
            )
            # Drive 10k unique keys through the limiter, all aged out
            # before the next admission.
            for i in range(10000):
                await limiter.is_allowed(f"key-{i}")
                # Age the just-added entry past the window so it qualifies
                # as expired on the next sweep.
                dq = limiter._requests.get(f"key-{i}")
                if dq:
                    aged = time.monotonic() - 2 * limiter.window_seconds
                    for j in range(len(dq)):
                        dq[j] = aged
            return len(limiter._requests)

        size = asyncio.run(run())
        assert size <= 500, f"Dict should be <= 500 keys after GC, got {size}"

    def test_active_key_not_evicted_by_gc(self):
        """A key that keeps making requests within the window must not
        be evicted by lazy GC."""
        async def run():
            limiter = RateLimiter(
                max_requests=100,
                window_seconds=60,
                max_keys=500,
                gc_interval=50,
            )
            # Active key keeps hitting throughout
            for i in range(200):
                await limiter.is_allowed("active")
                # Add a noisy expired key to drive GC ticks
                await limiter.is_allowed(f"noise-{i}")
                dq = limiter._requests.get(f"noise-{i}")
                if dq:
                    aged = time.monotonic() - 2 * limiter.window_seconds
                    for j in range(len(dq)):
                        dq[j] = aged
            return "active" in limiter._requests, len(
                limiter._requests["active"]
            )

        present, count = asyncio.run(run())
        assert present, "Active key must not be evicted by GC"
        assert count > 0, "Active key deque should still have entries"

    def test_size_cap_evicts_lru_when_no_expired(self):
        """When the dict reaches the hard size cap and no entries are
        expired, the least-recently-used key is evicted."""
        async def run():
            limiter = RateLimiter(
                max_requests=5,
                window_seconds=60,
                max_keys=10,
                gc_interval=1,
            )
            for i in range(20):
                await limiter.is_allowed(f"k-{i}")
            return len(limiter._requests), set(limiter._requests.keys())

        size, keys = asyncio.run(run())
        assert size <= 10, f"Dict must respect max_keys, got {size}"
        # The most recent keys must still be present
        assert "k-19" in keys
        assert "k-18" in keys
        # The oldest keys must have been evicted
        assert "k-0" not in keys
