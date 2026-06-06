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
    last_review_feedback: int = Field(ge=-1, le=1)


class ReviewStatePushRequest(BaseModel):
    entries: list[ReviewStateEntry] = Field(max_length=5000)


class ReviewStatePushResponse(BaseModel):
    updated: int
    skipped: int


class ReviewEventEntry(BaseModel):
    event_id: str
    card_id: str | None = None
    word_snapshot: str
    notebook_id: str = "default"
    feedback: int = Field(ge=0, le=1)
    reviewed_at: str
    created_at: str


class ReviewEventsPushRequest(BaseModel):
    entries: list[ReviewEventEntry] = Field(max_length=10000)


class ReviewEventsPushResponse(BaseModel):
    inserted: int
    skipped: int


class ReviewEventsResponse(BaseModel):
    entries: list[ReviewEventEntry]
    cursor: str | None = None
