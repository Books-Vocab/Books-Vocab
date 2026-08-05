"""Review event storage and sync operations."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select

from .api_models import ReviewEventEntry
from .exceptions import BadRequestError
from .sqlite_ledger import (
    install_serializable_sqlite as _install_serializable_sqlite,
)
from .sqlite_ledger import (
    next_ingested_at,
    normalize_last_ingested,
)
from .sqlite_ledger import (
    now_utc as _now,
)

# Ids per ``IN`` clause when checking which events the store already has. Kept
# below SQLite's pre-3.32 default limit of 999 bound variables per statement.
_EXISTS_QUERY_CHUNK = 500


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
    # SRS 前後狀態快照 — 複習當下由 iOS 計算,backend 原樣鏡像(不算 SRS)。逐筆事件自包含
    # 複習當下的間隔/下次複習/count/streak/lapse,研究「每張卡學習曲線 / 遺忘規律」才有料。
    # 舊事件無此資訊(migration 落 NULL),Phase 5 iOS 固化後新事件帶值。
    interval_before: float | None = SQLField(default=None)
    interval_after: float | None = SQLField(default=None)
    next_review_before: datetime | None = SQLField(default=None)
    next_review_after: datetime | None = SQLField(default=None)
    review_count_after: int | None = SQLField(default=None)
    streak_after: int | None = SQLField(default=None)
    lapse_after: int | None = SQLField(default=None)
    # 合成的過去(一次性遷移回填) vs 真實的未來(上線後 iOS 上報),研究時 WHERE 篩選互不污染。
    is_synthetic: bool = SQLField(default=False, index=True)


# SRS 快照 + is_synthetic 加寬欄位。為既有 store ADD COLUMN(SQLite 不支援改既有欄約束,
# 故全部 nullable;既有列 SRS 快照落 NULL、is_synthetic 落 0)。card_id 維持 nullable —
# 根治不靠 schema 約束而靠 Phase 5 iOS 固化 + 一次性遷移清舊垃圾,符合「不向後兼容、用資料
# 適配架構」(實驗階段)。
_WIDEN_COLUMNS: tuple[tuple[str, str], ...] = (
    ("interval_before", "REAL"),
    ("interval_after", "REAL"),
    ("next_review_before", "DATETIME"),
    ("next_review_after", "DATETIME"),
    ("review_count_after", "INTEGER"),
    ("streak_after", "INTEGER"),
    ("lapse_after", "INTEGER"),
    ("is_synthetic", "BOOLEAN NOT NULL DEFAULT 0"),
)


class ReviewEventStore:
    """SQLite-backed per-user review event store."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_url = f"sqlite:///{self.path.absolute()}"
        self.engine = create_engine(sqlite_url)
        _install_serializable_sqlite(self.engine)
        ReviewEvent.metadata.create_all(self.engine, tables=[ReviewEvent.__table__], checkfirst=True)
        self._migrate_ingested_at()
        self._migrate_widen_schema()

    def _migrate_widen_schema(self) -> None:
        """為既有 store 補上 SRS 前後快照 + is_synthetic 欄位。逐欄 ADD COLUMN(冪等:
        已存在則跳過);既有列的 SRS 快照落 NULL、is_synthetic 落 0。is_synthetic 補 index
        對齊全新表(create_all 已含),使研究 WHERE is_synthetic 篩選兩條建表路徑一致。"""
        table = ReviewEvent.__tablename__
        with self.engine.begin() as conn:
            columns = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").all()}
            for name, ddl in _WIDEN_COLUMNS:
                if name not in columns:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            conn.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_is_synthetic ON {table} (is_synthetic)"
            )

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

    def _existing_event_ids(self, session: Session, event_ids: list[str]) -> set[str]:
        """Return which of ``event_ids`` this store already holds.

        A client without a push watermark re-sends its whole review history every
        sync, so this lookup runs over thousands of ids that are all already
        present. One ``session.get`` per id turned that into thousands of point
        queries; one ``IN`` per chunk cuts that by the chunk size (9,542 ids: 20
        queries instead of 9,542). The chunk stays under SQLite's pre-3.32
        999-variable ceiling so the query never has to care which SQLite the host
        shipped — and production really does send ~1000 events per PATCH, so the
        multi-chunk path is live, not hypothetical.
        """
        known: set[str] = set()
        for start in range(0, len(event_ids), _EXISTS_QUERY_CHUNK):
            chunk = event_ids[start : start + _EXISTS_QUERY_CHUNK]
            known.update(
                session.exec(
                    select(ReviewEvent.event_id).where(ReviewEvent.event_id.in_(chunk))
                ).all()
            )
        return known

    def insert_many(self, entries: list[ReviewEventEntry]) -> dict[str, int]:
        inserted = 0
        skipped = 0
        with Session(self.engine) as session:
            # Continue the monotonic ingestion clock from the current max so each new
            # event gets a strictly increasing, unique ingested_at — even across a
            # backward wall-clock step (NTP) or multiple inserts within one microsecond.
            last_ingested = normalize_last_ingested(
                session.exec(select(func.max(ReviewEvent.ingested_at))).one()
            )
            # Pre-fetched ids only cover what was already committed. The loop adds
            # each accepted id so a repeated event_id *inside* one payload is still
            # skipped — the per-entry `session.get` used to catch that via autoflush.
            known_ids = self._existing_event_ids(session, [e.event_id for e in entries])
            for entry in entries:
                if entry.event_id in known_ids:
                    skipped += 1
                    continue
                reviewed_at = _parse_required_timestamp(entry.reviewed_at, "reviewed_at")
                created_at = _parse_required_timestamp(entry.created_at, "created_at")
                ingested_at = next_ingested_at(last_ingested, _now())
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
                        interval_before=entry.interval_before,
                        interval_after=entry.interval_after,
                        next_review_before=_parse_optional_timestamp(entry.next_review_before),
                        next_review_after=_parse_optional_timestamp(entry.next_review_after),
                        review_count_after=entry.review_count_after,
                        streak_after=entry.streak_after,
                        lapse_after=entry.lapse_after,
                        is_synthetic=entry.is_synthetic,
                    )
                )
                known_ids.add(entry.event_id)
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
        interval_before=event.interval_before,
        interval_after=event.interval_after,
        next_review_before=_format_optional_timestamp(event.next_review_before),
        next_review_after=_format_optional_timestamp(event.next_review_after),
        review_count_after=event.review_count_after,
        streak_after=event.streak_after,
        lapse_after=event.lapse_after,
        is_synthetic=event.is_synthetic,
    )


def _parse_optional_timestamp(raw: str | None) -> datetime | None:
    """SRS 快照的 next_review 時間戳:None 直通;否則寬鬆 parse(對齊 since watermark 的
    容忍度,naive 補 UTC)。這些是研究用快照,backend 不對其算 SRS,故比 reviewed_at 寬鬆。"""
    if raw is None:
        return None
    return _parse_iso8601_timestamp(raw)


def _format_optional_timestamp(value: datetime | None) -> str | None:
    return _format_timestamp(value) if value is not None else None


def _parse_iso8601_timestamp(raw: str) -> datetime:
    """Parse the pull watermark ``since``. Deliberately lenient: ``since`` is a value
    the client echoes back, and historical app versions persisted non-strict formats
    (naive, space-separated, basic offset). Rejecting them would deadlock the client
    (bad watermark → 400 → watermark never advances → 400 forever). We accept anything
    that maps to a single instant and normalize to tz-aware UTC; naive values are
    assumed UTC. Stricter than ingestion timestamps on purpose — see
    ``_parse_required_timestamp``, which still demands tz-aware input."""
    candidate = raw.strip().replace("Z", "+00:00")
    # Space-separated date/time → ISO 'T' (e.g. "2026-06-01 10:00:00").
    if "T" not in candidate and " " in candidate:
        candidate = candidate.replace(" ", "T", 1)
    # Swift Date.description style leaves a space before the offset ("...00 +0000").
    candidate = candidate.replace(" +", "+").replace(" -", "-")
    # A '+' offset is eaten to a space by x-www-form-urlencoded query decoding: the
    # client sends a literal '+' (URLComponents does not percent-encode it), and '+'
    # means space in a query string, so the handler receives "...10:00:00 00:00".
    # After the date/time 'T' is settled, a space immediately before a trailing
    # HH:MM(:SS) / HHMM offset can only be that eaten '+' (negative offsets keep
    # their '-' — URL decode never touches it). Restore it so our own UTC cursor,
    # which always carries a '+00:00' offset, round-trips back instead of 400-ing.
    candidate = re.sub(r" (?=\d{2}:?\d{2}$)", "+", candidate)
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise BadRequestError("Invalid since timestamp format. Expected ISO 8601.") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
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
    # Emit the UTC offset as 'Z', never '+00:00'. This cursor is echoed back by the
    # client as the `since` query value; a literal '+' there is decoded to a space by
    # x-www-form-urlencoded handling and breaks the round-trip (the 2026-06-08 download
    # deadlock). 'Z' (and ':' '.' '-') traverse a query string untouched for every
    # client. See _parse_iso8601_timestamp for the matching restore of legacy '+00:00'
    # watermarks already stored in the field.
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
