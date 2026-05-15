from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewStateEntry(BaseModel):
    word: str
    card_id: str | None = None  # precise matching; falls back to word if absent
    review_interval_hours: float = Field(ge=0)
    next_review_at: str  # ISO8601
    last_reviewed_at: str  # ISO8601
    review_count: int = Field(ge=0)
    lapse_count: int = Field(ge=0)
    review_streak: int = Field(ge=0)
    last_review_feedback: int


class ReviewStatePushRequest(BaseModel):
    entries: list[ReviewStateEntry] = Field(max_length=5000)


class ReviewStatePushResponse(BaseModel):
    updated: int
    skipped: int


class DailyReviewStatEntry(BaseModel):
    day_key: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")  # "yyyy-MM-dd"
    total: int = Field(ge=0)
    remembered: int = Field(ge=0)
    forgot: int = Field(ge=0)


class DailyReviewStatsPushRequest(BaseModel):
    entries: list[DailyReviewStatEntry] = Field(max_length=5000)


class DailyReviewStatsPushResponse(BaseModel):
    upserted: int


class DailyReviewStatsResponse(BaseModel):
    entries: list[DailyReviewStatEntry]
