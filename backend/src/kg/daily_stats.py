"""Daily review statistics storage and sync logic.

Stores per-day aggregated review counts for cross-device statistics sync.
Each record represents one calendar day's review activity.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select


class DailyReviewStat(SQLModel, table=True):
    """One day's aggregated review statistics."""

    id: str = SQLField(default_factory=lambda: uuid.uuid4().hex[:12], primary_key=True)
    day_key: str = SQLField(index=True)  # "yyyy-MM-dd"
    total: int = SQLField(default=0)
    remembered: int = SQLField(default=0)
    forgot: int = SQLField(default=0)
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


class DailyReviewStatsStore:
    """SQLite-based daily review stats storage."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_url = f"sqlite:///{self.path.absolute()}"
        self.engine = create_engine(sqlite_url)
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
            conn.exec_driver_sql("PRAGMA busy_timeout=30000;")
        DailyReviewStat.metadata.create_all(self.engine, tables=[DailyReviewStat.__table__], checkfirst=True)

    def upsert(self, day_key: str, total: int, remembered: int, forgot: int) -> DailyReviewStat:
        """Insert or update a day's stats. Client-wins: always takes the higher total."""
        with Session(self.engine) as session:
            existing = session.exec(
                select(DailyReviewStat).where(DailyReviewStat.day_key == day_key)
            ).first()

            if existing:
                # Take the max of each field (monotonically increasing)
                existing.total = max(existing.total, total)
                existing.remembered = max(existing.remembered, remembered)
                existing.forgot = max(existing.forgot, forgot)
                existing.updated_at = datetime.now(UTC)
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return existing
            else:
                stat = DailyReviewStat(
                    day_key=day_key,
                    total=total,
                    remembered=remembered,
                    forgot=forgot,
                )
                session.add(stat)
                session.commit()
                session.refresh(stat)
                return stat

    def all(self) -> list[DailyReviewStat]:
        """Return all daily stats, ordered by day_key."""
        with Session(self.engine) as session:
            return list(session.exec(
                select(DailyReviewStat).order_by(DailyReviewStat.day_key)
            ).all())

    def get_since(self, since_day: str) -> list[DailyReviewStat]:
        """Return stats for days >= since_day."""
        with Session(self.engine) as session:
            return list(session.exec(
                select(DailyReviewStat)
                .where(DailyReviewStat.day_key >= since_day)
                .order_by(DailyReviewStat.day_key)
            ).all())

    def close(self) -> None:
        """Dispose the SQLAlchemy engine and release connections."""
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None
