from __future__ import annotations

from datetime import UTC, datetime

from kg.review_events import ReviewEventStore


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
