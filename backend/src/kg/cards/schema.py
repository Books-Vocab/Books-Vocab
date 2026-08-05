"""Schema setup, index creation and migrations for the card table."""

from __future__ import annotations

import logging

from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from ..text_utils import normalize_nfc_lower
from .dictionary_models import (
    DictionaryArchiveLinkCause,
    DictionaryEntry,
    DictionaryLifecycleState,
    DictionaryPromotionJob,
    LexicalOperation,
)
from .model import Card

logger = logging.getLogger(__name__)


def init_schema(engine: Engine) -> None:
    """Create the card table, run migrations and ensure all indexes exist."""
    Card.metadata.create_all(
        engine,
        tables=[
            Card.__table__,
            DictionaryArchiveLinkCause.__table__,
            DictionaryEntry.__table__,
            DictionaryLifecycleState.__table__,
            LexicalOperation.__table__,
            DictionaryPromotionJob.__table__,
        ],
        checkfirst=True,
    )
    _migrate_review_columns(engine)
    _migrate_dictionary_promotion_jobs(engine)
    _migrate_content_nfc_lower(engine)
    _create_indexes(engine)


def _create_indexes(engine: Engine) -> None:
    """Ensure all secondary indexes on the card table exist."""
    with engine.connect() as conn:
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_card_updated_at ON card (updated_at)"
        )
        # Composite index backing cursor pagination — row-value comparison and
        # ORDER BY both use (updated_at, id). Kept alongside the single-column
        # index above (still used by get_modified_since's `updated_at >` scan).
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_card_updated_at_id ON card (updated_at, id)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_card_content ON card (content)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_card_content_nocase ON card (content COLLATE NOCASE)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_card_content_nfc_lower "
            "ON card (content_nfc_lower)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_card_notebook_id ON card (notebook_id)"
        )
        # Unique constraint to prevent duplicate active cards.
        # Uses partial index (is_deleted=0) so soft-deleted duplicates
        # don't block re-creation.
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_card_content_notebook "
            "ON card (content COLLATE NOCASE, notebook_id) WHERE is_deleted = 0"
        )
        conn.commit()


def _migrate_review_columns(engine: Engine) -> None:
    """Add review state columns to existing card tables (SQLModel create_all won't ALTER)."""
    review_columns = {
        "notebook_id": "TEXT DEFAULT 'default'",
        "is_archived": "INTEGER DEFAULT 0",
        "source": "TEXT",
        "review_interval_hours": "REAL DEFAULT 12.0",
        "next_review_at": "TIMESTAMP",
        "last_reviewed_at": "TIMESTAMP",
        "review_count": "INTEGER DEFAULT 0",
        "lapse_count": "INTEGER DEFAULT 0",
        "review_streak": "INTEGER DEFAULT 0",
        "last_review_feedback": "INTEGER DEFAULT -1",
        "source_shared_card_guid": "TEXT",
        "card_role": "TEXT NOT NULL DEFAULT 'learning'",
        "review_eligible": "INTEGER NOT NULL DEFAULT 1",
        "reader_hidden": "INTEGER NOT NULL DEFAULT 0",
        "promotion_state": "TEXT NOT NULL DEFAULT 'idle'",
        "promoted_at": "TIMESTAMP",
    }
    with engine.connect() as conn:
        result = conn.exec_driver_sql("PRAGMA table_info(card)")
        existing = {row[1] for row in result}
        for col_name, col_type in review_columns.items():
            if col_name not in existing:
                try:
                    conn.exec_driver_sql(f"ALTER TABLE card ADD COLUMN {col_name} {col_type}")
                except OperationalError as exc:
                    if "duplicate column" in str(exc).lower():
                        pass  # column already added by concurrent process
                    else:
                        logger.error("Migration failed for column %s: %s", col_name, exc, exc_info=True)
                        raise
        conn.commit()


def _migrate_dictionary_promotion_jobs(engine: Engine) -> None:
    """Keep pre-release promotion job tables forward-compatible."""
    with engine.connect() as conn:
        columns = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(dictionary_promotion_jobs)"
            )
        }
        if columns and "worker_id" not in columns:
            try:
                conn.exec_driver_sql(
                    "ALTER TABLE dictionary_promotion_jobs ADD COLUMN worker_id TEXT"
                )
            except OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
        conn.commit()


def _migrate_content_nfc_lower(engine: Engine) -> None:
    """Add and backfill `content_nfc_lower` for legacy DBs."""
    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(card)")}
        if "content_nfc_lower" not in cols:
            try:
                conn.exec_driver_sql(
                    "ALTER TABLE card ADD COLUMN content_nfc_lower TEXT DEFAULT ''"
                )
            except OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    logger.error("Migration failed for content_nfc_lower: %s", exc, exc_info=True)
                    raise
        # Backfill any rows where the column is empty/null but content isn't.
        rows = conn.exec_driver_sql(
            "SELECT id, content FROM card "
            "WHERE content_nfc_lower IS NULL OR content_nfc_lower = ''"
        ).fetchall()
        for card_id, content in rows:
            if content:
                conn.exec_driver_sql(
                    "UPDATE card SET content_nfc_lower = ? WHERE id = ?",
                    (normalize_nfc_lower(content), card_id),
                )
        conn.commit()
