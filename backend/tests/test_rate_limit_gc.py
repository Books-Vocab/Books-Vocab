"""
Tests for RateLimiter GC + size cap (memory leak prevention).

Goal: `_requests` dict must not grow unbounded. Expired keys are
periodically swept (lazy GC); at the size cap only expired keys are
reclaimed and unseen keys share a bounded overflow bucket (live windows are
never evicted).
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
        """At the cap an unseen key is charged to the overflow bucket and no
        live window is evicted, so flooding new keys cannot reset an abuser's
        window."""

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
        # Neither live window was evicted; noise-b went to the overflow bucket.
        assert keys == ["abuser", "noise-a"]

    def test_key_rotation_cannot_reset_active_window(self):
        """#2056 review P2: cycling more than `max_keys` identities inside one
        window must not evict a live window and hand its allowance back."""

        async def run():
            limiter = RateLimiter(max_requests=1, window_seconds=60, max_keys=2, gc_interval=10_000)
            return [await limiter.is_allowed(key) for key in ("abuser", "noise-a", "noise-b", "abuser")]

        results = asyncio.run(run())
        assert results[0] is True
        assert results[3] is False, "abuser's 2nd request must stay 429 after key rotation"

    def test_rotation_flood_never_resets_any_tracked_window(self):
        async def run():
            limiter = RateLimiter(max_requests=1, window_seconds=60, max_keys=3, gc_interval=10_000)
            tracked = ["a", "b", "c"]
            first = [await limiter.is_allowed(k) for k in tracked]
            for i in range(200):
                await limiter.is_allowed(f"flood-{i}")
            second = [await limiter.is_allowed(k) for k in tracked]
            return first, second, list(limiter._requests)

        first, second, keys = asyncio.run(run())
        assert first == [True] * 3
        assert second == [False] * 3
        assert keys == ["a", "b", "c"]

    def test_tracked_key_never_denied_by_overflow_exhaustion(self):
        """Overflow exhaustion fails closed for *unseen* keys only; a tracked
        key keeps its own budget regardless of what other keys do."""

        async def run():
            limiter = RateLimiter(max_requests=3, window_seconds=60, max_keys=2, gc_interval=10_000)
            assert await limiter.is_allowed("tracked-a")
            assert await limiter.is_allowed("tracked-b")
            flood = [await limiter.is_allowed(f"unseen-{i}") for i in range(50)]
            # tracked keys still have 2 of 3 each, untouched by the flood.
            a = [await limiter.is_allowed("tracked-a") for _ in range(3)]
            b = [await limiter.is_allowed("tracked-b") for _ in range(3)]
            return flood, a, b

        flood, a, b = asyncio.run(run())
        assert not all(flood), "overflow must fail closed for unseen keys under flood"
        assert a == [True, True, False]
        assert b == [True, True, False]

    def test_overflow_bucket_is_bounded(self):
        async def run():
            limiter = RateLimiter(max_requests=5, window_seconds=60, max_keys=2, gc_interval=10_000)
            await limiter.is_allowed("a")
            await limiter.is_allowed("b")
            results = [await limiter.is_allowed(f"unseen-{i}") for i in range(10_000)]
            return results, len(limiter._requests), len(limiter._overflow)

        results, table_size, overflow_size = asyncio.run(run())
        assert table_size == 2
        assert overflow_size <= 5
        assert sum(results) == 5, "unseen keys share exactly one overflow budget"

    def test_overflow_bucket_recovers_after_window(self):
        async def run():
            limiter = RateLimiter(max_requests=1, window_seconds=60, max_keys=1, gc_interval=10_000)
            await limiter.is_allowed("a")
            assert await limiter.is_allowed("x") is True
            assert await limiter.is_allowed("y") is False
            aged = time.monotonic() - 120
            for dq in (*limiter._requests.values(), limiter._overflow):
                for j in range(len(dq)):
                    dq[j] = aged
            # Expired tracked key is reclaimed (not evicted while active) and
            # the new key is tracked normally again.
            return await limiter.is_allowed("y"), list(limiter._requests)

        allowed, keys = asyncio.run(run())
        assert allowed is True
        assert keys == ["y"]

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

    def test_size_cap_charges_overflow_when_no_expired(self):
        """When all slots are active, unseen keys share the overflow budget
        (#2056): the table stays bounded and no live window is evicted."""

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
        assert results == [True] * 15 + [False] * 5
        assert keys == {f"k-{i}" for i in range(10)}

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

    def test_rate_limiter_size_cap_reclaims_only_expired_keys(self):
        """At the cap only expired windows are reclaimed (from the front);
        live windows stay tracked and later keys go to the overflow bucket."""

        async def run():
            limiter = RateLimiter(
                max_requests=5,
                window_seconds=60,
                max_keys=10,
                gc_interval=10_000,  # disable the periodic sweep for clarity
            )
            for i in range(10):
                await limiter.is_allowed(f"user-{i}")
            # Age the first 4 keys past the window; the rest stay live.
            aged = time.monotonic() - 120
            for i in range(4):
                dq = limiter._requests[f"user-{i}"]
                for j in range(len(dq)):
                    dq[j] = aged
            results = [await limiter.is_allowed(f"new-{i}") for i in range(6)]
            return results, len(limiter._requests), list(limiter._requests.keys())

        results, size, keys = asyncio.run(run())
        assert results == [True] * 6  # 4 reclaimed slots + 2 overflow admissions
        assert size == 10
        assert keys == [f"user-{i}" for i in range(4, 10)] + [f"new-{i}" for i in range(4)]

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
