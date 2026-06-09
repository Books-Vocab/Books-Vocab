from __future__ import annotations

from logging import Logger
from typing import Any

import httpx
from fastapi import HTTPException
from openai import OpenAIError

from .api_models import ExplainResponse, QuickTranslateResponse, TranslateRequest
from .deps_quota import _is_pro
from .exceptions import ExternalServiceError, KGError
from .llm.providers import provider_for
from .service_factories import create_async_client
from .tracked_llm import TrackedLLM
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
    call_type: str,
    label: str,
    logger: Logger | None = None,
):
    provider = provider_for(call_type)
    llm = TrackedLLM(
        create_async_client(provider),
        user["id"],
        provider=provider,
        enforce_quota=True,
        is_pro=_is_pro(user),
    )
    try:
        kw: dict[str, Any] = {"llm": llm, "model": provider.chat_model}
        if logger:
            kw["logger"] = logger
        return await coro(req, user, **kw)
    except HTTPException:
        raise
    except OpenAIError as exc:
        if logger:
            logger.exception("%s OpenAI error: %s", label, exc)
        raise ExternalServiceError(label, exc=exc) from exc
    except (TimeoutError, httpx.HTTPError) as exc:
        # Inflight follower-wait timeout (asyncio.wait_for -> builtin TimeoutError
        # on 3.11+) or raw network failures from the HTTP client. Map to a stable
        # external-service surface instead of leaking a generic 500.
        if logger:
            logger.exception("%s upstream/network error: %s", label, exc)
        raise ExternalServiceError(label, exc=exc) from exc
    except (ValueError, KeyError, TypeError, RuntimeError) as exc:
        if logger:
            logger.exception("%s failed: %s", label, exc)
        # Do not embed inner exception text in client-visible detail.
        raise KGError(f"{label} failed") from exc


async def translate_quick_response(
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    logger: Logger,
) -> QuickTranslateResponse:
    return await _safe_translate(
        run_quick_translate, req, user,
        call_type="translate_quick", label="translate/quick", logger=logger,
    )


async def translate_phrase_response(
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    logger: Logger | None = None,
) -> dict[str, str]:
    return await _safe_translate(
        run_phrase_translate, req, user,
        call_type="translate_phrase", label="translate/phrase", logger=logger,
    )


async def translate_explain_response(
    req: TranslateRequest,
    user: dict[str, Any],
    *,
    logger: Logger | None = None,
) -> ExplainResponse:
    return await _safe_translate(
        run_explain_translate, req, user,
        call_type="translate_explain", label="translate/explain", logger=logger,
    )
