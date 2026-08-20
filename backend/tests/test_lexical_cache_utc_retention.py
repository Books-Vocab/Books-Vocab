"""Regression tests for UTC-instant lexical lookup-event retention."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone


def test_record_lookup_prunes_fixed_offset_rows_by_utc_instant(tmp_path, monkeypatch) -> None:
    import kg.lexical_cache as lexical_cache

    frozen_now = datetime(2026, 5, 15, tzinfo=UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_now.astimezone(tz) if tz is not None else frozen_now.replace(tzinfo=None)

    monkeypatch.setattr(lexical_cache, "datetime", FrozenDateTime)

    cache_path = tmp_path / "lexical_cache.db"
    cache = lexical_cache.LexicalCache(cache_path)
    cutoff = frozen_now - timedelta(days=lexical_cache.LOOKUP_EVENT_RETENTION_DAYS)
    older_plus_one = cutoff - timedelta(minutes=30)
    newer_minus_one = cutoff + timedelta(minutes=30)

    assert older_plus_one < cutoff < newer_minus_one
    seeded_events = [
        (
            "provider",
            "older_plus_one",
            "seed",
            1,
            older_plus_one.astimezone(timezone(timedelta(hours=1))).isoformat(),
        ),
        (
            "provider",
            "newer_minus_one",
            "seed",
            2,
            newer_minus_one.astimezone(timezone(-timedelta(hours=1))).isoformat(),
        ),
        ("provider", "exact_boundary", "seed", 3, cutoff.isoformat()),
    ]
    with closing(sqlite3.connect(cache_path)) as conn, conn:
        conn.executemany(
            "INSERT INTO lexical_lookup_event"
            "(provider, operation, outcome, duration_ms, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            seeded_events,
        )

    cache.record_lookup("provider", "current", "fresh", 4)

    with closing(sqlite3.connect(cache_path)) as conn:
        events = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT operation, created_at FROM lexical_lookup_event ORDER BY id"
            )
        }

    assert set(events) == {"newer_minus_one", "exact_boundary", "current"}
    assert events["exact_boundary"] == cutoff.isoformat()
    assert events["current"] == frozen_now.isoformat()
