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

    def test_rate_limiter_gc_evicts_expired_entries(self):
        """Loading 100 distinct user entries and advancing time past the
        window must cause the sweeper to drop every expired entry on the
        next GC tick. Targets PR #388 / #391 lazy-GC behavior."""
        async def run():
            limiter = RateLimiter(
                max_requests=5,
                window_seconds=1,
                max_keys=10_000,  # well above 100, so no LRU eviction
                gc_interval=100,  # next admission after batch triggers GC
            )
            # Populate 100 distinct user entries
            for i in range(100):
                await limiter.is_allowed(f"user-{i}")
            assert len(limiter._requests) == 100, "All 100 entries should be present pre-GC"

            # Advance time past the window by mutating timestamps in-place
            aged = time.monotonic() - 2 * limiter.window_seconds
            for dq in limiter._requests.values():
                for j in range(len(dq)):
                    dq[j] = aged

            # Reset tick so the very next admission triggers GC
            limiter._tick = limiter.gc_interval - 1
            await limiter.is_allowed("trigger-gc")
            return len(limiter._requests), "trigger-gc" in limiter._requests

        remaining, trigger_present = asyncio.run(run())
        # All 100 expired keys should be swept; only the trigger remains
        assert trigger_present, "Trigger key must remain after GC"
        assert remaining == 1, (
            f"GC must evict all 100 expired entries, only trigger should remain, got {remaining}"
        )

    def test_rate_limiter_size_cap_evicts_oldest(self):
        """With max_keys=10, admitting 15 distinct active keys must evict
        the 5 oldest (LRU) while preserving the 10 most recent."""
        async def run():
            limiter = RateLimiter(
                max_requests=5,
                window_seconds=60,  # keep all keys "active" so only LRU cap fires
                max_keys=10,
                gc_interval=10_000,  # disable GC for clarity
            )
            for i in range(15):
                await limiter.is_allowed(f"user-{i}")
            return len(limiter._requests), list(limiter._requests.keys())

        size, keys = asyncio.run(run())
        assert size == 10, f"Dict must hold exactly max_keys=10, got {size}"
        # The 5 oldest (user-0..user-4) must have been evicted
        for i in range(5):
            assert f"user-{i}" not in keys, f"Oldest key user-{i} should be evicted"
        # The 10 newest (user-5..user-14) must remain
        for i in range(5, 15):
            assert f"user-{i}" in keys, f"Recent key user-{i} must survive"

    def test_rate_limiter_concurrent_increment_no_lost_count(self):
        """Concurrent coroutines incrementing the same key must not lose
        counts: `is_allowed` is protected by `asyncio.Lock`, so the total
        admitted count must equal `max_requests` exactly (rest rejected)."""
        async def run():
            limiter = RateLimiter(
                max_requests=50,
                window_seconds=60,
                max_keys=100,
                gc_interval=10_000,
            )
            # Fire 200 concurrent admissions for the same key
            results = await asyncio.gather(
                *[limiter.is_allowed("hot-key") for _ in range(200)]
            )
            return results, len(limiter._requests["hot-key"])

        results, deque_len = asyncio.run(run())
        admitted = sum(1 for r in results if r)
        rejected = sum(1 for r in results if not r)
        # Lock guarantees no lost updates: exactly max_requests admissions
        assert admitted == 50, f"Expected exactly 50 admitted, got {admitted}"
        assert rejected == 150, f"Expected exactly 150 rejected, got {rejected}"
        # Internal deque must match admitted count (no double-append, no drops)
        assert deque_len == 50, (
            f"Internal deque must hold exactly admitted count, got {deque_len}"
        )
