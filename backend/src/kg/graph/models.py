"""Data models for the card relationship graph."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class LinkKind(StrEnum):
    """Types of relationships between cards."""

    CONTRASTS_WITH = "contrasts_with"
    SHARES_USAGE = "shares_usage"


LINK_LABELS: dict[LinkKind, str] = {
    LinkKind.CONTRASTS_WITH: "對比",
    LinkKind.SHARES_USAGE: "相關",
}


class GraphLink(BaseModel):
    """A relationship between two cards."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    from_id: str
    to_id: str
    kind: LinkKind
    confidence: float
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: Literal["candidate", "active", "deprecated", "hidden"] = "active"


class CandidatePair(BaseModel):
    """A pending pair awaiting LLM judgement."""

    from_id: str
    to_id: str
    similarity: float  # embedding similarity score
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
