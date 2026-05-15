"""Data models and constants for card relationship judgement."""

from __future__ import annotations

from pydantic import BaseModel

MAX_BATCH_SIZE = 15  # 避免超大 batch 導致 token 爆炸或回應截斷


class Judgement(BaseModel):
    """LLM judgement result."""

    link: str  # LinkKind value or "not_applicable"
    confidence: float
    reason: str
