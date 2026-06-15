"""Tests for store cache eviction behavior."""
from __future__ import annotations

import threading
import time
from queue import Queue
from unittest.mock import MagicMock

from kg.service_factories import _get_cached, clear_store_cache, create_library_store


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
    clear_store_cache()

    mock1 = MagicMock()
    mock2 = MagicMock()
    _get_cached("x", lambda: mock1)
    _get_cached("y", lambda: mock2)

    clear_store_cache()
    mock1.close.assert_called_once()
    mock2.close.assert_called_once()


def test_clear_store_cache_prevents_inflight_factory_reinsert():
    """A clear that returns while a factory is still running must remain a
    linearization point: the late result is returned to its caller, but not
    inserted back into the global cache after clear."""
    import kg.service_factories as sf

    clear_store_cache()
    started = threading.Event()
    release = threading.Event()
    result: Queue[object] = Queue()
    errors: Queue[BaseException] = Queue()
    late_store = MagicMock(name="late_store")

    def factory():
        started.set()
        release.wait(timeout=5)
        return late_store

    def worker():
        try:
            result.put(_get_cached("late", factory))
        except BaseException as exc:
            errors.put(exc)

    thread = threading.Thread(target=worker)
    try:
        thread.start()
        assert started.wait(timeout=5)

        clear_store_cache()
        with sf._STORE_CACHE_LOCK:
            assert "late" not in sf._STORE_CACHE

        release.set()
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert errors.empty(), list(errors.queue)
        assert result.get_nowait() is late_store
        with sf._STORE_CACHE_LOCK:
            assert "late" not in sf._STORE_CACHE
        late_store.close.assert_not_called()
    finally:
        release.set()
        thread.join(timeout=5)
        clear_store_cache()


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


def test_create_library_store_is_cached(tmp_path):
    """Same user_dir returns the *same* LibraryStore instance (shared engine,
    not a fresh per-request engine which leaked connections + lost WAL cache)."""
    clear_store_cache()
    try:
        s1 = create_library_store(tmp_path)
        s2 = create_library_store(tmp_path)
        assert s1 is s2
    finally:
        clear_store_cache()


def test_library_store_has_close(tmp_path):
    """LibraryStore must expose close() so the LRU can dispose its engine on
    eviction (without it, evicted stores leak SQLite connections)."""
    clear_store_cache()
    try:
        store = create_library_store(tmp_path)
        assert hasattr(store, "close")
        store.close()
        # After close the engine is released; a fresh build still works.
        assert store.engine is None
    finally:
        clear_store_cache()


def test_concurrent_misses_dedupe_to_single_factory_call():
    """Two threads racing on the same key should both end up with the same
    cached instance, and the underlying factory must only run once."""
    clear_store_cache()
    calls = 0
    calls_lock = threading.Lock()
    start = threading.Barrier(2)
    results: Queue[object] = Queue()
    errors: Queue[BaseException] = Queue()

    def factory():
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return MagicMock(name=f"instance_{calls}")

    def worker():
        try:
            start.wait(timeout=5)
            results.put(_get_cached("shared", factory))
        except BaseException as exc:
            errors.put(exc)

    try:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        assert all(not thread.is_alive() for thread in threads)
        assert errors.empty(), list(errors.queue)
        built = list(results.queue)
        assert len(built) == 2
        assert built[0] is built[1]
        assert calls == 1
    finally:
        clear_store_cache()
