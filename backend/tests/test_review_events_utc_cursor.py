from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from sqlalchemy import event as sa_event

from kg.api_models import ReviewEventEntry
from kg.exceptions import BadRequestError
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

        # Init-time migration canonicalizes legacy rows; reopen to run it.
        store.close()
        store = ReviewEventStore(tmp_path / "review_events.db")

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

        store.close()
        store = ReviewEventStore(tmp_path / "review_events.db")

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


_LEGACY_INSERT = """
    INSERT INTO reviewevent
        (event_id, word_snapshot, feedback, reviewed_at,
         created_at, ingested_at, notebook_id, is_synthetic)
    VALUES (?, ?, 1, ?, ?, ?, 'default', 0)
"""


def _seed_raw(path, rows):
    with sqlite3.connect(path) as conn:
        for event_id, ingested in rows:
            conn.execute(_LEGACY_INSERT, (event_id, event_id, ingested, ingested, ingested))
        conn.commit()


def _raw_ingested(path):
    with sqlite3.connect(path) as conn:
        return dict(conn.execute("SELECT event_id, ingested_at FROM reviewevent").fetchall())


def test_init_rewrites_legacy_offset_ingested_at_to_canonical_naive_utc(tmp_path):
    path = tmp_path / "review_events.db"
    ReviewEventStore(path).close()
    _seed_raw(
        path,
        [
            ("plus", "2026-05-14 12:00:00+01:00"),
            ("minus", "2026-05-14 12:00:00-05:00"),
            ("t-form", "2026-05-14T12:00:00+00:00"),
            ("z-form", "2026-05-14T12:00:00Z"),
            ("naive", "2026-05-14 12:00:00"),
            ("canonical", "2026-05-14 12:00:00.123456"),
        ],
    )

    ReviewEventStore(path).close()

    assert _raw_ingested(path) == {
        "plus": "2026-05-14 11:00:00.000000",
        "minus": "2026-05-14 17:00:00.000000",
        "t-form": "2026-05-14 12:00:00.000000",
        "z-form": "2026-05-14 12:00:00.000000",
        "naive": "2026-05-14 12:00:00.000000",
        "canonical": "2026-05-14 12:00:00.123456",
    }
    # Idempotent: a second init changes nothing.
    ReviewEventStore(path).close()
    assert _raw_ingested(path)["plus"] == "2026-05-14 11:00:00.000000"


def test_get_since_statement_uses_ingested_at_index(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    try:
        stmt = store._since_statement(datetime(2026, 5, 14, 11, 15, tzinfo=UTC))
        compiled = stmt.compile(dialect=store.engine.dialect, compile_kwargs={"literal_binds": True})
        with store.engine.connect() as conn:
            plan = conn.exec_driver_sql(f"EXPLAIN QUERY PLAN {compiled}").fetchall()
        detail = " ".join(str(row[-1]) for row in plan)
        assert "ix_reviewevent_ingested_at" in detail
    finally:
        store.close()


def _statements(store, action):
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    sa_event.listen(store.engine, "before_cursor_execute", record)
    try:
        action()
    finally:
        sa_event.remove(store.engine, "before_cursor_execute", record)
    return seen


def test_get_since_filters_in_sql_and_insert_many_uses_single_max(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    try:
        entry = ReviewEventEntry(
            event_id="e1",
            word_snapshot="w",
            notebook_id="default",
            feedback=1,
            reviewed_at="2026-05-14T10:00:00+00:00",
            created_at="2026-05-14T10:00:01+00:00",
        )
        insert_sql = _statements(store, lambda: store.insert_many([entry]))
        max_queries = [s for s in insert_sql if "max(" in s.lower()]
        assert len(max_queries) == 1
        assert not any("FROM reviewevent" in s and "ingested_at FROM" in s for s in insert_sql)

        since_sql = _statements(store, lambda: store.get_since(datetime(2026, 1, 1, tzinfo=UTC)))
        selects = [s for s in since_sql if "FROM reviewevent" in s]
        assert len(selects) == 1
        assert "WHERE" in selects[0]
    finally:
        store.close()


def test_same_ingested_at_ties_order_by_event_id(tmp_path):
    path = tmp_path / "review_events.db"
    ReviewEventStore(path).close()
    _seed_raw(
        path,
        [
            ("b", "2026-05-14 12:00:00.000000"),
            ("c", "2026-05-14 12:00:00.000000"),
            ("a", "2026-05-14 12:00:00.000000"),
        ],
    )
    store = ReviewEventStore(path)
    try:
        assert [e.event_id for e in store.all()] == ["a", "b", "c"]
        since = datetime(2026, 5, 14, 11, 0, tzinfo=UTC)
        assert [e.event_id for e in store.get_since(since)] == ["a", "b", "c"]
    finally:
        store.close()


def test_out_of_range_timestamps_are_bad_request_not_overflow():
    import pytest

    from kg.review_events import _parse_iso8601_timestamp, _parse_required_timestamp

    with pytest.raises(BadRequestError):
        _parse_required_timestamp("9999-12-31T23:59:59-05:00", "reviewed_at")
    with pytest.raises(BadRequestError):
        _parse_iso8601_timestamp("0001-01-01T00:00:00+02:00")


def _drain(store, *, page_size):
    """Pull page by page the way the client does; returns (event_id pages)."""
    pages: list[list[str]] = []
    since = None
    for _ in range(20):
        entries, cursor = pull_review_events(since=since, event_store=store, page_size=page_size)
        if not entries:
            break
        pages.append([e.event_id for e in entries])
        since = cursor
    return pages


def test_pull_pages_bounded_for_since_none_and_cursor(tmp_path):
    path = tmp_path / "review_events.db"
    ReviewEventStore(path).close()
    _seed_raw(path, [(f"e{i}", f"2026-05-14 12:00:0{i}.000000") for i in range(5)])
    store = ReviewEventStore(path)
    try:
        entries, cursor = pull_review_events(since=None, event_store=store, page_size=2)
        assert [e.event_id for e in entries] == ["e0", "e1"]
        entries, _ = pull_review_events(since=cursor, event_store=store, page_size=2)
        assert [e.event_id for e in entries] == ["e2", "e3"]
        assert _drain(store, page_size=2) == [["e0", "e1"], ["e2", "e3"], ["e4"]]
    finally:
        store.close()


def test_pull_page_never_splits_same_ingested_at_tie(tmp_path):
    path = tmp_path / "review_events.db"
    ReviewEventStore(path).close()
    tie = "2026-05-14 12:00:01.000000"
    _seed_raw(
        path,
        [("a", "2026-05-14 12:00:00.000000"), ("b", tie), ("c", tie), ("d", tie), ("e", "2026-05-14 12:00:02.000000")],
    )
    store = ReviewEventStore(path)
    try:
        pages = _drain(store, page_size=2)
        assert pages == [["a", "b", "c", "d"], ["e"]]
    finally:
        store.close()
