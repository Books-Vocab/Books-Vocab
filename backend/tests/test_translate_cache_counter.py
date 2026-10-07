"""Tests for translate cache hit counter — precise hit-rate observability.

`translate_log.record()` only fires on cache MISS (LLM call). True cache hits
short-circuit before record(), so hits were previously invisible. This counter
records every cache hit explicitly via `record_cache_hit()`; admin
observability reads the `translate_cache_hits` rows it persists.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("translate_data_dir")


def _hit_rows() -> list[tuple]:
    from kg.translate_log import _get_conn, _lock

    with _lock:
        conn = _get_conn()
        return conn.execute(
            "SELECT user_id, operation, word, context_hash, source_lang, target_lang, model "
            "FROM translate_cache_hits ORDER BY id"
        ).fetchall()


def test_record_cache_hit_persists_row():
    from kg.translate_log import record_cache_hit

    record_cache_hit(
        user_id="u1",
        operation="translate_quick",
        word="evoke",
        context_hash="abc123",
        source_lang="en",
        target_lang="zh-Hant",
    )
    assert _hit_rows() == [("u1", "translate_quick", "evoke", "abc123", "en", "zh-Hant", "")]


def test_record_cache_hit_allows_blank_user_id():
    """Anonymous / unauth cache hits should still be counted."""
    from kg.translate_log import record_cache_hit

    record_cache_hit(
        user_id=None,
        operation="translate_quick",
        word="evoke",
        context_hash="abc",
        source_lang="en",
        target_lang="zh-Hant",
    )
    assert [row[0] for row in _hit_rows()] == [None]


def test_record_cache_hit_multiple_increments():
    from kg.translate_log import record_cache_hit

    for _ in range(5):
        record_cache_hit(
            user_id="u1",
            operation="translate_quick",
            word="evoke",
            context_hash="abc",
            source_lang="en",
            target_lang="zh-Hant",
        )
    assert len(_hit_rows()) == 5
