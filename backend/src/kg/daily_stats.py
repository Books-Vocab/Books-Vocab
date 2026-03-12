"""Daily review statistics storage and sync logic.

Stores per-day aggregated review counts for cross-device statistics sync.
Each record represents one calendar day's review activity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from sqlmodel import SQLModel, Field as SQLField, Session, select, create_engine


class DailyReviewStat(SQLModel, table=True):
    """One day's aggregated review statistics."""

    id: str = SQLField(default_factory=lambda: uuid.uuid4().hex[:12], primary_key=True)
    day_key: str = SQLField(index=True)  # "yyyy-MM-dd"
    total: int = SQLField(default=0)
    remembered: int = SQLField(default=0)
    forgot: int = SQLField(default=0)
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))


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
        SQLModel.metadata.create_all(self.engine, checkfirst=True)

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
                existing.updated_at = datetime.now(timezone.utc)
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
