"""Data models and constants for card relationship judgement."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

MAX_BATCH_SIZE = 15  # 避免超大 batch 導致 token 爆炸或回應截斷


class Judgement(BaseModel):
    """LLM judgement result."""

    # Defense-in-depth: reject NaN/inf at model construction even if a future
    # code path skips the parsing-layer finite check (see parsing.py). Keeps
    # confidence a plain float; does not alter accept semantics.
    model_config = ConfigDict(allow_inf_nan=False)

    link: str  # LinkKind value or "not_applicable"
    confidence: float
    reason: str
