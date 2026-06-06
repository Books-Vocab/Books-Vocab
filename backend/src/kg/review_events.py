"""Review event storage and sync operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select

from .api_models import ReviewEventEntry
from .exceptions import BadRequestError


class ReviewEvent(SQLModel, table=True):
    """One immutable review event, keyed by the client-generated event id."""

    event_id: str = SQLField(primary_key=True)
    card_id: str | None = SQLField(default=None, index=True)
    word_snapshot: str
    notebook_id: str = SQLField(default="default", index=True)
    feedback: int = SQLField(ge=0, le=1)
    reviewed_at: datetime = SQLField(index=True)
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    # Server-assigned ingestion time. This is the sync watermark dimension: it is
    # monotonic in the order the server received events, so a cursor over it never
    # misses a late-arriving event whose reviewed_at lies in the past.
    ingested_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC), index=True)


class ReviewEventStore:
    """SQLite-backed per-user review event store."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_url = f"sqlite:///{self.path.absolute()}"
        self.engine = create_engine(sqlite_url)
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
            conn.exec_driver_sql("PRAGMA busy_timeout=30000;")
        ReviewEvent.metadata.create_all(self.engine, tables=[ReviewEvent.__table__], checkfirst=True)
        self._migrate_ingested_at()

    def _migrate_ingested_at(self) -> None:
        """Add the ingested_at column to pre-existing stores and backfill it from
        reviewed_at so legacy events sort correctly under the ingestion cursor."""
        table = ReviewEvent.__tablename__
        with self.engine.begin() as conn:
            columns = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").all()}
            if "ingested_at" in columns:
                return
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN ingested_at DATETIME")
            conn.exec_driver_sql(
                f"UPDATE {table} SET ingested_at = reviewed_at WHERE ingested_at IS NULL"
            )
            conn.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_ingested_at ON {table} (ingested_at)"
            )

    def insert_many(self, entries: list[ReviewEventEntry]) -> dict[str, int]:
        inserted = 0
        skipped = 0
        with Session(self.engine) as session:
            # Continue the monotonic ingestion clock from the current max so each new
            # event gets a strictly increasing, unique ingested_at — even across a
            # backward wall-clock step (NTP) or multiple inserts within one microsecond.
            last_ingested = session.exec(select(func.max(ReviewEvent.ingested_at))).one()
            if last_ingested is not None and last_ingested.tzinfo is None:
                last_ingested = last_ingested.replace(tzinfo=UTC)
            for entry in entries:
                existing = session.get(ReviewEvent, entry.event_id)
                if existing is not None:
                    skipped += 1
                    continue
                reviewed_at = _parse_required_timestamp(entry.reviewed_at, "reviewed_at")
                created_at = _parse_required_timestamp(entry.created_at, "created_at")
                now = datetime.now(UTC)
                if last_ingested is None or now > last_ingested:
                    ingested_at = now
                else:
                    ingested_at = last_ingested + timedelta(microseconds=1)
                last_ingested = ingested_at
                session.add(
                    ReviewEvent(
                        event_id=entry.event_id,
                        card_id=entry.card_id,
                        word_snapshot=entry.word_snapshot,
                        notebook_id=entry.notebook_id,
                        feedback=entry.feedback,
                        reviewed_at=reviewed_at,
                        created_at=created_at,
                        ingested_at=ingested_at,
                    )
                )
                inserted += 1
            session.commit()
        return {"inserted": inserted, "skipped": skipped}

    def all(self) -> list[ReviewEvent]:
        with Session(self.engine) as session:
            return list(session.exec(select(ReviewEvent).order_by(ReviewEvent.ingested_at)).all())

    def get_since(self, since: datetime) -> list[ReviewEvent]:
        # Strict ``>``: ingested_at is monotonic and unique (see insert_many), so the
        # cursor boundary event was already delivered and need not be re-pulled.
        with Session(self.engine) as session:
            return list(
                session.exec(
                    select(ReviewEvent)
                    .where(ReviewEvent.ingested_at > since)
                    .order_by(ReviewEvent.ingested_at)
                ).all()
            )

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None


def push_review_events(entries: list[ReviewEventEntry], *, event_store: Any) -> dict[str, int]:
    return event_store.insert_many(entries)


def pull_review_events(
    *, since: str | None, event_store: Any
) -> tuple[list[ReviewEventEntry], str | None]:
    """Return (entries, cursor). ``cursor`` is the max ingestion timestamp of the
    returned batch, to be sent back as ``since`` on the next pull. An empty batch
    leaves the caller's cursor unchanged (echoes ``since``)."""
    if since is not None:
        parsed_since = _parse_iso8601_timestamp(since)
        events = event_store.get_since(parsed_since)
    else:
        events = event_store.all()
    entries = [_entry_from_event(event) for event in events]
    cursor = _format_timestamp(max(event.ingested_at for event in events)) if events else since
    return entries, cursor


def _entry_from_event(event: ReviewEvent) -> ReviewEventEntry:
    return ReviewEventEntry(
        event_id=event.event_id,
        card_id=event.card_id,
        word_snapshot=event.word_snapshot,
        notebook_id=event.notebook_id,
        feedback=event.feedback,
        reviewed_at=_format_timestamp(event.reviewed_at),
        created_at=_format_timestamp(event.created_at),
    )


def _parse_iso8601_timestamp(raw: str) -> datetime:
    if "T" not in raw:
        raise BadRequestError("Invalid since timestamp format. Expected ISO 8601.")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise BadRequestError("Invalid since timestamp format. Expected ISO 8601.") from None
    if parsed.tzinfo is None:
        raise BadRequestError("Invalid since timestamp format. Expected ISO 8601.")
    return parsed.astimezone(UTC)


def _parse_required_timestamp(raw: str, field_name: str) -> datetime:
    if "T" not in raw:
        raise BadRequestError(f"Invalid {field_name} timestamp format. Expected ISO 8601.")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise BadRequestError(f"Invalid {field_name} timestamp format. Expected ISO 8601.") from None
    if parsed.tzinfo is None:
        raise BadRequestError(f"Invalid {field_name} timestamp format. Expected ISO 8601.")
    return parsed.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
