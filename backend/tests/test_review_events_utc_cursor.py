from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from kg.api_models import ReviewEventEntry
from kg.review_events import ReviewEventStore, pull_review_events, push_review_events


def test_get_since_compares_mixed_offset_ingestion_timestamps_as_instants(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    try:
        # Keep the historical offset spellings in SQLite so the query exercises
        # the mixed-offset rows that older writers could leave behind.
        with store.engine.begin() as conn:
            for event_id, timestamp in (
                ("old", "2026-05-14 12:00:00+01:00"),
                ("new", "2026-05-14 11:30:00+00:00"),
            ):
                conn.exec_driver_sql(
                    """
                    INSERT INTO reviewevent
                        (event_id, word_snapshot, feedback, reviewed_at,
                         created_at, ingested_at, notebook_id, is_synthetic)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        event_id,
                        1,
                        timestamp,
                        timestamp,
                        timestamp,
                        "default",
                        0,
                    ),
                )

        events = store.get_since(datetime(2026, 5, 14, 11, 15, tzinfo=UTC))

        assert [event.event_id for event in events] == ["new"]
    finally:
        store.close()


def test_empty_pull_normalizes_url_decoded_legacy_utc_cursor(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    try:
        # An unescaped '+' in a legacy query cursor reaches the handler as a space.
        legacy_since = "2026-05-14T16:30:00 00:00"

        entries, cursor = pull_review_events(
            since=legacy_since,
            event_store=store,
        )

        assert entries == []
        assert cursor == "2026-05-14T16:30:00Z"
    finally:
        store.close()


def test_insert_after_legacy_offset_rows_stays_after_utc_cursor(tmp_path, monkeypatch):
    store = ReviewEventStore(tmp_path / "review_events.db")
    try:
        with sqlite3.connect(store.path) as conn:
            for event_id, timestamp in (
                # Lexically greatest, but 11:00Z is not the latest instant.
                ("lexical-max", "2026-05-14 12:00:00+01:00"),
                ("utc-max", "2026-05-14 11:30:00-05:00"),
            ):
                conn.execute(
                    """
                    INSERT INTO reviewevent
                        (event_id, word_snapshot, feedback, reviewed_at,
                         created_at, ingested_at, notebook_id, is_synthetic)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        event_id,
                        1,
                        timestamp,
                        timestamp,
                        timestamp,
                        "default",
                        0,
                    ),
                )
            conn.commit()

        _events, cursor = pull_review_events(since=None, event_store=store)
        assert cursor == "2026-05-14T16:30:00Z"

        # A backward wall clock must still allocate after the UTC-latest legacy row.
        monkeypatch.setattr(
            "kg.review_events._now",
            lambda: datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
        )
        push_review_events(
            [
                ReviewEventEntry(
                    event_id="after-legacy",
                    word_snapshot="after",
                    notebook_id="default",
                    feedback=1,
                    reviewed_at="2026-05-14T10:00:00+00:00",
                    created_at="2026-05-14T10:00:01+00:00",
                )
            ],
            event_store=store,
        )

        pulled, _next_cursor = pull_review_events(since=cursor, event_store=store)
        assert [event.event_id for event in pulled] == ["after-legacy"]
    finally:
        store.close()
