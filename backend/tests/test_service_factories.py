"""Tests for store cache eviction behavior."""
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
