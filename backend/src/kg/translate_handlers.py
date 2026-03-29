from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from typing import Any

from fastapi import HTTPException
from openai import OpenAIError

from .api_models import ExplainResponse, QuickTranslateResponse, TranslateRequest
from .exceptions import ExternalServiceError
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
    gemini_client_factory: Callable[[], Any],
    label: str,
    logger: Logger | None = None,
    model: str | None = None,
):
    client = gemini_client_factory()
    try:
        kw: dict[str, Any] = {"client": client}
        if logger:
            kw["logger"] = logger
        if model:
            kw["model"] = model
        return await coro(req, user, **kw)
    except HTTPException:
        raise
    except OpenAIError as exc:
        if logger:
            logger.error("%s OpenAI error: %s", label, exc, exc_info=True)
        raise ExternalServiceError(f"{label} failed: {exc}") from exc
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        if logger:
            logger.error("%s failed: %s", label, exc, exc_info=True)
        raise HTTPException(500, f"{label} failed: {exc}") from exc


async def translate_quick_response(
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    gemini_client_factory: Callable[[], Any],
    logger: Logger,
    model: str | None = None,
) -> QuickTranslateResponse:
    return await _safe_translate(
        run_quick_translate, req, user,
        gemini_client_factory=gemini_client_factory,
        label="translate/quick", logger=logger, model=model,
    )


async def translate_phrase_response(
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    gemini_client_factory: Callable[[], Any],
    model: str | None = None,
) -> dict[str, str]:
    return await _safe_translate(
        run_phrase_translate, req, user,
        gemini_client_factory=gemini_client_factory,
        label="translate/phrase", model=model,
    )


async def translate_explain_response(
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    gemini_client_factory: Callable[[], Any],
    model: str | None = None,
) -> ExplainResponse:
    return await _safe_translate(
        run_explain_translate, req, user,
        gemini_client_factory=gemini_client_factory,
        label="translate/explain", model=model,
    )
