"""Tests for translate cache hit counter — precise hit-rate observability.

`translate_log.record()` only fires on cache MISS (LLM call). True cache hits
short-circuit before record(), so hits were previously invisible. This counter
records every cache hit explicitly via `record_cache_hit()`.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import kg.translate_log as tl
    tl._reset()
    yield
    tl._reset()


def test_record_cache_hit_persists_row():
    from kg.translate_log import record_cache_hit, count_cache_hits_since

    record_cache_hit(
        user_id="u1", operation="translate_quick",
        word="evoke", context_hash="abc123",
        source_lang="en", target_lang="zh-Hant",
    )
    cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert count_cache_hits_since(cutoff) == 1


def test_record_cache_hit_allows_blank_user_id():
    """Anonymous / unauth cache hits should still be counted."""
    from kg.translate_log import record_cache_hit, count_cache_hits_since

    record_cache_hit(
        user_id=None, operation="translate_quick",
        word="evoke", context_hash="abc",
        source_lang="en", target_lang="zh-Hant",
    )
    cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert count_cache_hits_since(cutoff) == 1


def test_count_cache_hits_since_filters_old_rows():
    from kg.translate_log import (
        _get_conn,
        _lock,
        count_cache_hits_since,
        record_cache_hit,
    )

    # Insert one fresh hit
    record_cache_hit(
        user_id="u1", operation="translate_quick",
        word="fresh", context_hash="h1",
        source_lang="en", target_lang="zh-Hant",
    )
    # Insert one old hit (backdate)
    record_cache_hit(
        user_id="u1", operation="translate_quick",
        word="stale", context_hash="h2",
        source_lang="en", target_lang="zh-Hant",
    )
    old_ts = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "UPDATE translate_cache_hits SET created_at=? WHERE word='stale'",
            (old_ts,),
        )
        conn.commit()

    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    assert count_cache_hits_since(cutoff) == 1  # only the fresh one


def test_record_cache_hit_multiple_increments():
    from kg.translate_log import count_cache_hits_since, record_cache_hit

    for _ in range(5):
        record_cache_hit(
            user_id="u1", operation="translate_quick",
            word="evoke", context_hash="abc",
            source_lang="en", target_lang="zh-Hant",
        )
    cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert count_cache_hits_since(cutoff) == 5
