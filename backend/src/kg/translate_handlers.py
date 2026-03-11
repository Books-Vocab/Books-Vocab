from __future__ import annotations

from logging import Logger
from typing import Any, Callable

from fastapi import HTTPException

from .api_models import ExplainResponse, QuickTranslateResponse, TranslateRequest
from .translate_service import run_explain_translate, run_phrase_translate, run_quick_translate


def translate_quick_response(
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    gemini_client_factory: Callable[[], Any],
    logger: Logger,
) -> QuickTranslateResponse:
    require_pro_access(user, "reader_ai")
    client = gemini_client_factory()
    try:
        return run_quick_translate(req, user, client=client, logger=logger)
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        logger.error("translate/quick failed: %s", exc, exc_info=True)
        raise HTTPException(500, f"Quick translation failed: {exc}") from exc


def translate_phrase_response(
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    gemini_client_factory: Callable[[], Any],
) -> dict[str, str]:
    require_pro_access(user, "reader_ai")
    client = gemini_client_factory()
    try:
        return run_phrase_translate(req, user, client=client)
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise HTTPException(500, f"Phrase translation failed: {exc}") from exc


def translate_explain_response(
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    gemini_client_factory: Callable[[], Any],
) -> ExplainResponse:
    require_pro_access(user, "reader_ai")
    client = gemini_client_factory()
    try:
        return run_explain_translate(req, user, client=client)
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise HTTPException(500, f"Explanation failed: {exc}") from exc
