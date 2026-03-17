from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from typing import Any

from fastapi import HTTPException

from .api_models import ExplainResponse, QuickTranslateResponse, TranslateRequest
from .translate_service import (
    run_explain_translate,
    run_phrase_translate,
    run_quick_translate,
)


async def _safe_translate(
    coro,
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    gemini_client_factory: Callable[[], Any],
    label: str,
    logger: Logger | None = None,
):
    require_pro_access(user, "reader_ai")
    client = gemini_client_factory()
    try:
        kw: dict[str, Any] = {"client": client}
        if logger:
            kw["logger"] = logger
        return await coro(req, user, **kw)
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        if logger:
            logger.error("%s failed: %s", label, exc, exc_info=True)
        raise HTTPException(500, f"{label} failed: {exc}") from exc


async def translate_quick_response(
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    gemini_client_factory: Callable[[], Any],
    logger: Logger,
) -> QuickTranslateResponse:
    return await _safe_translate(
        run_quick_translate, req, user,
        require_pro_access=require_pro_access,
        gemini_client_factory=gemini_client_factory,
        label="translate/quick", logger=logger,
    )


async def translate_phrase_response(
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    gemini_client_factory: Callable[[], Any],
) -> dict[str, str]:
    return await _safe_translate(
        run_phrase_translate, req, user,
        require_pro_access=require_pro_access,
        gemini_client_factory=gemini_client_factory,
        label="translate/phrase",
    )


async def translate_explain_response(
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    gemini_client_factory: Callable[[], Any],
) -> ExplainResponse:
    return await _safe_translate(
        run_explain_translate, req, user,
        require_pro_access=require_pro_access,
        gemini_client_factory=gemini_client_factory,
        label="translate/explain",
    )
