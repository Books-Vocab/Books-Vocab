"""
Tests for RateLimiter GC + size cap (memory leak prevention).

Goal: `_requests` dict must not grow unbounded. Expired keys are
periodically swept (lazy GC), and a hard size cap evicts the
least-recently-used keys.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from kg.rate_limit import RateLimiter


class TestRateLimiterGC:
    @pytest.mark.parametrize("max_keys", [0, -1])
    def test_non_positive_max_keys_is_rejected(self, max_keys):
        with pytest.raises(ValueError, match="max_keys must be positive"):
            RateLimiter(max_requests=1, window_seconds=60, max_keys=max_keys)

    def test_hammering_key_window_survives_full_cap(self):
        """At the cap a new key evicts the least-recently-seen key, never one
        that is still hitting: every lookup (admitted or rejected) refreshes
        recency, so flooding new keys cannot reset an abuser's window."""

        async def run():
            limiter = RateLimiter(
                max_requests=1,
                window_seconds=60,
                max_keys=2,
                gc_interval=10_000,
            )
            results = [await limiter.is_allowed(key) for key in ("abuser", "noise-a", "abuser", "noise-b", "abuser")]
            return results, list(limiter._requests)

        results, keys = asyncio.run(run())

        assert results == [True, True, False, True, False]
        # noise-a (least recently seen) was evicted; the rejected final lookup
        # still moved the abuser to the most-recent end.
        assert keys == ["noise-b", "abuser"]

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
            return "active" in limiter._requests, len(limiter._requests["active"])

        present, count = asyncio.run(run())
        assert present, "Active key must not be evicted by GC"
        assert count > 0, "Active key deque should still have entries"

    def test_size_cap_admits_new_key_when_no_expired(self):
        """When all slots are active, a new key is still admitted (#2056):
        rejecting it would let anyone who fills the table 429 every new
        client. The table stays bounded by evicting the LRU key."""

        async def run():
            limiter = RateLimiter(
                max_requests=5,
                window_seconds=60,
                max_keys=10,
                gc_interval=1,
            )
            results = [await limiter.is_allowed(f"k-{i}") for i in range(20)]
            return results, len(limiter._requests), set(limiter._requests.keys())

        results, size, keys = asyncio.run(run())
        assert size <= 10, f"Dict must respect max_keys, got {size}"
        assert results == [True] * 20
        assert keys == {f"k-{i}" for i in range(10, 20)}

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
        assert remaining == 1, f"GC must evict all 100 expired entries, only trigger should remain, got {remaining}"

    def test_rate_limiter_size_cap_evicts_least_recently_seen_windows(self):
        """With max_keys=10, later keys are admitted and the least recently
        seen windows are evicted, in recency order."""

        async def run():
            limiter = RateLimiter(
                max_requests=5,
                window_seconds=60,  # keep all keys "active" so only LRU cap fires
                max_keys=10,
                gc_interval=10_000,  # disable GC for clarity
            )
            results = [await limiter.is_allowed(f"user-{i}") for i in range(15)]
            return results, len(limiter._requests), list(limiter._requests.keys())

        results, size, keys = asyncio.run(run())
        assert size == 10, f"Dict must hold exactly max_keys=10, got {size}"
        assert results == [True] * 15
        assert keys == [f"user-{i}" for i in range(5, 15)]

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
            results = await asyncio.gather(*[limiter.is_allowed("hot-key") for _ in range(200)])
            return results, len(limiter._requests["hot-key"])

        results, deque_len = asyncio.run(run())
        admitted = sum(1 for r in results if r)
        rejected = sum(1 for r in results if not r)
        # Lock guarantees no lost updates: exactly max_requests admissions
        assert admitted == 50, f"Expected exactly 50 admitted, got {admitted}"
        assert rejected == 150, f"Expected exactly 150 rejected, got {rejected}"
        # Internal deque must match admitted count (no double-append, no drops)
        assert deque_len == 50, f"Internal deque must hold exactly admitted count, got {deque_len}"
