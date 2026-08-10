"""Concurrent legacy-schema opening contracts.

Each migration is exercised through two independent connections against the same
legacy SQLite file.  A process-local lock is not enough here: separate workers
must serialize the schema read/ALTER boundary themselves.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

from kg.cards import CardStore
from kg.notebook import NotebookStore
from kg.review_events import ReviewEventStore
from kg.sqlite_utils import ensure_columns, init_sqlite_pragmas


def _run_two_writers(factory: Callable[[], Any]) -> list[Any]:
    barrier = Barrier(2)

    def open_store():
        barrier.wait(timeout=30)
        return factory()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(open_store) for _ in range(2)]
        return [future.result(timeout=60) for future in futures]


def _columns(path: Path, table: str) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _schema_snapshot(path: Path) -> tuple[tuple[str, str, str | None], ...]:
    with sqlite3.connect(path) as conn:
        return tuple(
            conn.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE type IN ('table', 'index') ORDER BY type, name"
            ).fetchall()
        )


def _assert_second_round_is_stable(path: Path, factory: Callable[[], Any]) -> None:
    before = _schema_snapshot(path)
    first = factory()
    first.close()
    second = factory()
    second.close()
    assert _schema_snapshot(path) == before


def _create_legacy_card_db(path: Path) -> None:
    # Bootstrap auxiliary SQLModel tables once.  The contract below targets
    # migrations, not SQLAlchemy's concurrent create_all catalogue walk.
    store = CardStore(path)
    store.close()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX IF EXISTS ix_card_content_nfc_lower")
        for column in (
            "source_shared_card_guid",
            "card_role",
            "review_eligible",
            "reader_hidden",
            "promotion_state",
            "promoted_at",
            "content_nfc_lower",
        ):
            conn.execute(f"ALTER TABLE card DROP COLUMN {column}")


def _create_legacy_notebook_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE notebook ("
            "id TEXT PRIMARY KEY, name TEXT, color TEXT, sort_order INTEGER, "
            "is_default INTEGER, created_at TIMESTAMP, updated_at TIMESTAMP, is_deleted INTEGER"
            ")"
        )


def _create_legacy_review_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE reviewevent ("
            "event_id TEXT PRIMARY KEY, card_id TEXT, word_snapshot TEXT NOT NULL, "
            "notebook_id TEXT, feedback INTEGER, reviewed_at TIMESTAMP, created_at TIMESTAMP"
            ")"
        )


def test_card_legacy_migration_is_safe_with_two_independent_stores(tmp_path: Path):
    path = tmp_path / "cards.db"
    _create_legacy_card_db(path)

    stores = _run_two_writers(lambda: CardStore(path))
    try:
        assert {
            "review_interval_hours",
            "next_review_at",
            "last_reviewed_at",
            "review_count",
            "lapse_count",
            "review_streak",
            "last_review_feedback",
            "source_shared_card_guid",
            "card_role",
            "review_eligible",
            "reader_hidden",
            "promotion_state",
            "promoted_at",
            "content_nfc_lower",
        } <= _columns(path, "card")
    finally:
        for store in stores:
            store.close()
    _assert_second_round_is_stable(path, lambda: CardStore(path))


def test_notebook_legacy_migration_is_safe_with_two_independent_stores(tmp_path: Path):
    path = tmp_path / "notebooks.db"
    _create_legacy_notebook_db(path)

    stores = _run_two_writers(lambda: NotebookStore(path))
    try:
        assert {"cover_pattern", "source_shared_deck_id", "source_version", "is_staged"} <= _columns(path, "notebook")
    finally:
        for store in stores:
            store.close()
    _assert_second_round_is_stable(path, lambda: NotebookStore(path))


def test_review_legacy_migration_is_safe_with_two_independent_stores(tmp_path: Path):
    path = tmp_path / "review_events.db"
    _create_legacy_review_db(path)

    stores = _run_two_writers(lambda: ReviewEventStore(path))
    try:
        assert {
            "ingested_at",
            "interval_before",
            "interval_after",
            "next_review_before",
            "next_review_after",
            "review_count_after",
            "streak_after",
            "lapse_after",
            "is_synthetic",
        } <= _columns(path, "reviewevent")
    finally:
        for store in stores:
            store.close()
    _assert_second_round_is_stable(path, lambda: ReviewEventStore(path))


def test_shared_sqlite_column_helper_is_safe_with_two_independent_connections(tmp_path: Path):
    path = tmp_path / "shared_log.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE legacy_log (id INTEGER PRIMARY KEY, payload TEXT)")

    barrier = Barrier(2)

    def migrate(*, synchronize: bool = True) -> None:
        conn = sqlite3.connect(path, timeout=30)
        try:
            init_sqlite_pragmas(conn)
            if synchronize:
                barrier.wait(timeout=30)
            ensure_columns(conn, "legacy_log", {"created_at": "TEXT", "model": "TEXT"})
            conn.commit()
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(migrate) for _ in range(2)]
        for future in futures:
            future.result(timeout=60)

    assert {"created_at", "model"} <= _columns(path, "legacy_log")
    before = _schema_snapshot(path)
    migrate(synchronize=False)
    migrate(synchronize=False)
    assert _schema_snapshot(path) == before
