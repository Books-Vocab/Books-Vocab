from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from ..api_models import ExplainResponse, PhraseTranslateResponse, QuickTranslateResponse


def build_translate_router(
    *,
    translate_quick: Callable[..., Any],
    translate_phrase: Callable[..., Any],
    translate_explain: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()
    router.post("/api/translate/quick", response_model=QuickTranslateResponse)(translate_quick)
    router.post("/api/translate/phrase", response_model=PhraseTranslateResponse)(translate_phrase)
    router.post("/api/translate/explain", response_model=ExplainResponse)(translate_explain)
    return router
