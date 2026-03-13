from __future__ import annotations

from pathlib import Path

import pytest

import kg.service_factories as sf


def setup_function():
    sf.clear_store_cache()


def teardown_function():
    sf.clear_store_cache()


def test_same_card_store_instance(tmp_path):
    d = tmp_path / "user1"
    d.mkdir()
    s1 = sf.create_card_store(d)
    s2 = sf.create_card_store(d)
    assert s1 is s2


def test_different_user_dirs_different_card_store(tmp_path):
    d1 = tmp_path / "user1"
    d2 = tmp_path / "user2"
    d1.mkdir()
    d2.mkdir()
    s1 = sf.create_card_store(d1)
    s2 = sf.create_card_store(d2)
    assert s1 is not s2


def test_same_daily_stats_store_instance(tmp_path):
    d = tmp_path / "user1"
    d.mkdir()
    s1 = sf.create_daily_stats_store(d)
    s2 = sf.create_daily_stats_store(d)
    assert s1 is s2


def test_same_graph_store_instance(tmp_path):
    d = tmp_path / "user1"
    d.mkdir()
    s1 = sf.create_graph_store(d)
    s2 = sf.create_graph_store(d)
    assert s1 is s2


def test_evict_oldest_when_exceeding_max(tmp_path):
    max_size = sf._STORE_CACHE_MAX
    dirs = []
    for i in range(max_size):
        d = tmp_path / f"user{i}"
        d.mkdir()
        dirs.append(d)
        sf.create_card_store(d)

    # cache is now full; first entry key should still be present
    first_key = f"card:{dirs[0]}"
    assert first_key in sf._STORE_CACHE

    # add one more to trigger eviction
    extra = tmp_path / "extra"
    extra.mkdir()
    sf.create_card_store(extra)

    assert len(sf._STORE_CACHE) == max_size
    assert first_key not in sf._STORE_CACHE


def test_clear_store_cache_returns_new_instance(tmp_path):
    d = tmp_path / "user1"
    d.mkdir()
    s1 = sf.create_card_store(d)
    sf.clear_store_cache()
    s2 = sf.create_card_store(d)
    assert s1 is not s2


def test_clear_store_cache_empties_cache(tmp_path):
    d = tmp_path / "user1"
    d.mkdir()
    sf.create_card_store(d)
    assert len(sf._STORE_CACHE) > 0
    sf.clear_store_cache()
    assert len(sf._STORE_CACHE) == 0
