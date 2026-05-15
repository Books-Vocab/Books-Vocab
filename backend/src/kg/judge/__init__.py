"""LLM-based narrow judgement for card relationships."""

from __future__ import annotations

from .batch import Judge
from .manual import ManualLinkJudge
from .models import MAX_BATCH_SIZE, Judgement
from .parsing import _parse_batch_response
from .prompts import (
    BATCH_SYSTEM_PROMPT,
    BATCH_USER_TEMPLATE,
    MANUAL_LINK_SYSTEM_PROMPT,
    SELECTIVE_BATCH_SYSTEM_PROMPT,
)

__all__ = [
    "BATCH_SYSTEM_PROMPT",
    "BATCH_USER_TEMPLATE",
    "MANUAL_LINK_SYSTEM_PROMPT",
    "MAX_BATCH_SIZE",
    "SELECTIVE_BATCH_SYSTEM_PROMPT",
    "Judge",
    "Judgement",
    "ManualLinkJudge",
    "_parse_batch_response",
]
