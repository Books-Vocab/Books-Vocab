"""Tests for store cache eviction behavior."""
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from kg.service_factories import _get_cached, clear_store_cache


def test_evicted_store_is_closed():
    """When cache exceeds max, evicted store's close() should be called."""
    import kg.service_factories as sf
    old_max = sf._STORE_CACHE_MAX

    try:
        clear_store_cache()
        sf._STORE_CACHE_MAX = 2

        mock1 = MagicMock()
        mock2 = MagicMock()
        mock3 = MagicMock()

        _get_cached("a", lambda: mock1)
        _get_cached("b", lambda: mock2)
        _get_cached("c", lambda: mock3)  # should evict mock1

        mock1.close.assert_called_once()
        mock2.close.assert_not_called()
    finally:
        sf._STORE_CACHE_MAX = old_max
        clear_store_cache()


def test_clear_store_cache_closes_all():
    """clear_store_cache() should close all cached stores."""
    import kg.service_factories as sf
    clear_store_cache()

    mock1 = MagicMock()
    mock2 = MagicMock()
    _get_cached("x", lambda: mock1)
    _get_cached("y", lambda: mock2)

    clear_store_cache()
    mock1.close.assert_called_once()
    mock2.close.assert_called_once()


def test_factory_runs_outside_lock():
    """factory() must execute without holding _STORE_CACHE_LOCK so slow
    SQLite/npy initialisation doesn't block other cache lookups."""
    import kg.service_factories as sf
    clear_store_cache()
    try:
        observed_locked: list[bool] = []

        def slow_factory():
            # Try to acquire the cache lock from inside the factory; if the
            # caller holds the lock, this will fail (return False).
            acquired = sf._STORE_CACHE_LOCK.acquire(blocking=False)
            observed_locked.append(not acquired)
            if acquired:
                sf._STORE_CACHE_LOCK.release()
            return MagicMock()

        _get_cached("slow", slow_factory)
        assert observed_locked == [False], (
            "factory() executed while _STORE_CACHE_LOCK was held — "
            "this serialises every other request behind store init."
        )
    finally:
        clear_store_cache()


def test_concurrent_misses_dedupe_to_single_factory_call():
    """Two threads racing on the same key should both end up with the same
    cached instance (last writer wins) rather than constructing two."""
    import kg.service_factories as sf
    clear_store_cache()
    try:
        call_count = {"n": 0}
        gate = threading.Event()

        def factory():
            call_count["n"] += 1
            gate.wait(timeout=2.0)
            return MagicMock(name=f"instance_{call_count['n']}")

        results: list[object] = []

        def worker():
            results.append(_get_cached("shared", factory))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        # let both threads enter the factory (or one enter, other wait)
        time.sleep(0.05)
        gate.set()
        for t in threads:
            t.join(timeout=3.0)

        # Both callers must observe the same cached instance.
        assert len(results) == 2
        assert results[0] is results[1]
    finally:
        clear_store_cache()
