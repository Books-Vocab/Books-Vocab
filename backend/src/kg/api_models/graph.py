from __future__ import annotations

from pydantic import BaseModel, Field


class GraphLinkResponse(BaseModel):
    id: str
    fromId: str
    toId: str
    kind: str
    confidence: float
    reason: str


class ManualLinkRequest(BaseModel):
    from_id: str = Field(min_length=1)
    to_id: str = Field(min_length=1)
