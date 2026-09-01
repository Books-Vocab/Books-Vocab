from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .cards import CardResponse
from .common import VocabSource
from .graph import GraphLinkResponse


class ExternalApiKeyCreateRequest(BaseModel):
    label: str = Field(default="external client", min_length=1, max_length=64)


class ExternalApiKeyResponse(BaseModel):
    keyId: str
    label: str
    createdAt: str
    revokedAt: str | None = None
    # Returned only by POST /api/v1/api-keys. It is never persisted and never
    # included by GET /api/v1/api-keys.
    apiKey: str | None = None


class ExternalCardCreateRequest(BaseModel):
    """The deliberately small, non-template card intake contract.

    ``meaning`` may be empty because a reader can upload a captured word first
    and ask the enrich pipeline to fill the editorial fields later. Text is
    stored as plain text; this surface does not parse or require Markdown.
    """

    content: str = Field(min_length=1, max_length=200)
    meaning: str = Field(default="", max_length=1000)
    context: str = Field(default="", max_length=5000)
    pos: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=5000)
    examples: list[str] = Field(default_factory=list, max_length=10)
    collocations: list[str] = Field(default_factory=list, max_length=20)
    mode: Literal["recognition", "production"] = "recognition"
    notebookId: str = Field(default="default", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    clientId: str | None = Field(default=None, max_length=128)
    source: VocabSource | None = None


class ExternalCardBatchRequest(BaseModel):
    items: list[ExternalCardCreateRequest] = Field(min_length=1, max_length=100)


class ExternalCardIngestResponse(BaseModel):
    card: CardResponse
    created: bool
    clientId: str | None = None


class ExternalCardBatchResponse(BaseModel):
    items: list[ExternalCardIngestResponse]
    created: int
    duplicates: int


class ExternalCardListResponse(BaseModel):
    items: list[CardResponse]
    nextCursor: str | None = None


class ExternalCardUpdateRequest(BaseModel):
    meaning: str | None = Field(default=None, max_length=1000)
    pos: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=5000)
    examples: list[str] | None = Field(default=None, max_length=10)
    collocations: list[str] | None = Field(default=None, max_length=20)
    mode: Literal["recognition", "production"] | None = None


class ExternalCardArchiveRequest(BaseModel):
    archived: bool


class ExternalCardDeleteResponse(BaseModel):
    cardId: str
    deleted: bool


class ExternalCardReviewRequest(BaseModel):
    reviewIntervalHours: float = Field(ge=0, allow_inf_nan=False)
    nextReviewAt: str
    lastReviewedAt: str
    reviewCount: int = Field(ge=0)
    lapseCount: int = Field(ge=0)
    reviewStreak: int = Field(ge=0)
    lastReviewFeedback: int = Field(ge=-1, le=1)

    @field_validator("nextReviewAt", "lastReviewedAt")
    @classmethod
    def validate_iso_timestamp(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("must be an ISO 8601 timestamp") from exc
        return value

    @field_validator("reviewIntervalHours", mode="before")
    @classmethod
    def _replace_non_finite_interval_for_validation(cls, value: object) -> object:
        # Keep the validation error JSON-safe so the API can return its normal 422.
        if isinstance(value, float) and not math.isfinite(value):
            return -1.0
        return value


class ExternalEnrichRequest(BaseModel):
    notebookId: str = Field(default="default", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    force: bool = False


class ExternalOperationResponse(BaseModel):
    operationId: str
    status: str
    notebookId: str
    startedAt: str | None = None
    endedAt: str | None = None
    durationSeconds: float | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)


class ExternalOperationListResponse(BaseModel):
    items: list[ExternalOperationResponse]


class ExternalManualLinkRequest(BaseModel):
    fromId: str = Field(min_length=1)
    toId: str = Field(min_length=1)


class ExternalLinkListResponse(BaseModel):
    items: list[GraphLinkResponse]
