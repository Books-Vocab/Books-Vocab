from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


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


class ReviewClockConfig(BaseModel):
    """Per-user 全局複習時鐘暫停態(對標 TranslationLanguageConfig 走 user config)。

    `is_paused` + `paused_at` 為**複合原子狀態**:暫停時鐘的錨點時間只在
    `is_paused=True` 時有意義。單一 `updated_at`(epoch 秒)驅動跨裝置 LWW —
    兩欄位共用一個時戳,確保整組原子收斂(不會 is_paused 與 paused_at 各自比較
    導致半套狀態)。resume(`is_paused=False`)時 `paused_at` 由 validator 正規化為
    `None`,杜絕儲存層自相矛盾;對 client 寬鬆(不 reject,只正規化)。
    """

    is_paused: bool = False
    paused_at: str | None = None  # ISO8601;僅 is_paused=True 時有意義
    updated_at: float | None = None  # LWW timestamp, epoch 秒

    @model_validator(mode="after")
    def _normalize_consistency(self) -> ReviewClockConfig:
        if not self.is_paused and self.paused_at is not None:
            self.paused_at = None
        return self
