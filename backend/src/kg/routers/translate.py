from __future__ import annotations

from fastapi import APIRouter, Response

from ..api_models import ExplainResponse, PhraseTranslateResponse, QuickTranslateResponse, TranslateRequest
from ..deps import (
    CurrentUser,
    _apply_quota_headers,
    _check_quota,
    _is_pro,
    logger,
)
from ..quota_service import get_quota_state
from ..translate_handlers import (
    translate_explain_response,
    translate_phrase_response,
    translate_quick_response,
)

router = APIRouter(tags=["translate"])


@router.post("/api/translate/quick", response_model=QuickTranslateResponse)
async def translate_quick(req: TranslateRequest, response: Response, user: CurrentUser):
    _check_quota(user, "translate_quick", response)
    result = await translate_quick_response(req, user, logger=logger)
    _apply_quota_headers(response, get_quota_state(user["id"], is_pro=_is_pro(user)))
    return result


@router.post("/api/translate/phrase", response_model=PhraseTranslateResponse)
async def translate_phrase(req: TranslateRequest, response: Response, user: CurrentUser):
    _check_quota(user, "translate_phrase", response)
    result = await translate_phrase_response(req, user, logger=logger)
    _apply_quota_headers(response, get_quota_state(user["id"], is_pro=_is_pro(user)))
    return result


@router.post("/api/translate/explain", response_model=ExplainResponse)
async def translate_explain(req: TranslateRequest, response: Response, user: CurrentUser):
    quota = _check_quota(user, "translate_explain", response)
    result = await translate_explain_response(req, user, logger=logger)
    _apply_quota_headers(response, quota)
    return result
