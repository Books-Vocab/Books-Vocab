from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from ..api_models import ExplainResponse, PhraseTranslateResponse, QuickTranslateResponse, TranslateRequest
from ..deps import (
    _apply_quota_headers,
    _check_quota,
    _gemini_async_client,
    _require_pro_access,
    get_current_user,
    logger,
)
from ..translate_handlers import (
    translate_explain_response,
    translate_phrase_response,
    translate_quick_response,
)

router = APIRouter()


@router.post("/api/translate/quick", response_model=QuickTranslateResponse)
async def translate_quick(req: TranslateRequest, request: Request, user: dict = Depends(get_current_user), response: Response = None):
    quota = _check_quota(user, "translate_quick", response)
    model = request.app.state.kg_settings.gemini_model
    result = await translate_quick_response(
        req, user, require_pro_access=_require_pro_access, gemini_client_factory=_gemini_async_client, logger=logger, model=model,
    )
    _apply_quota_headers(response, quota)
    return result


@router.post("/api/translate/phrase", response_model=PhraseTranslateResponse)
async def translate_phrase(req: TranslateRequest, request: Request, user: dict = Depends(get_current_user), response: Response = None):
    quota = _check_quota(user, "translate_phrase", response)
    model = request.app.state.kg_settings.gemini_model
    result = await translate_phrase_response(
        req, user, require_pro_access=_require_pro_access, gemini_client_factory=_gemini_async_client, model=model,
    )
    _apply_quota_headers(response, quota)
    return result


@router.post("/api/translate/explain", response_model=ExplainResponse)
async def translate_explain(req: TranslateRequest, request: Request, user: dict = Depends(get_current_user), response: Response = None):
    quota = _check_quota(user, "translate_explain", response)
    model = request.app.state.kg_settings.gemini_model
    result = await translate_explain_response(
        req, user, require_pro_access=_require_pro_access, gemini_client_factory=_gemini_async_client, model=model,
    )
    _apply_quota_headers(response, quota)
    return result
