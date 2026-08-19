"""Shared helpers for sync merge tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from kg.api_models import ReviewStateEntry
from kg.cards import CardStore

# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path) -> CardStore:
    return CardStore(tmp_path / "cards.db")


def _iso(dt: datetime) -> str:
    s = dt.isoformat()
    if not s.endswith("Z") and "+" not in s:
        s += "Z"
    return s


def _now() -> datetime:
    return datetime.now(UTC)


def _entry(
    word: str,
    last_reviewed_at: str,
    *,
    card_id: str | None = None,
    review_interval_hours: float = 24.0,
    next_review_at: str | None = None,
    review_count: int = 1,
    lapse_count: int = 0,
    review_streak: int = 1,
    last_review_feedback: int = 1,
) -> ReviewStateEntry:
    return ReviewStateEntry(
        word=word,
        card_id=card_id,
        review_interval_hours=review_interval_hours,
        next_review_at=next_review_at or _iso(_now() + timedelta(hours=review_interval_hours)),
        last_reviewed_at=last_reviewed_at,
        review_count=review_count,
        lapse_count=lapse_count,
        review_streak=review_streak,
        last_review_feedback=last_review_feedback,
    )


# ============================================================================
