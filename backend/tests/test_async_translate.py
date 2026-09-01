from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kg.api_models import TranslateRequest
from kg.tracked_llm import TrackedLLM
from kg.translate_service import (
    run_explain_translate,
    run_phrase_translate,
    run_quick_translate,
)


def _fake_async_client(content: str):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=None,
    )
    mock_create = AsyncMock(return_value=response)
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=mock_create)
        )
    )


@pytest.fixture(autouse=True)
def reset_translate_sqlite_singletons():
    from kg import llm_error_log, translate_log

    try:
        yield
    finally:
        llm_error_log.reset()
        translate_log.reset()


@pytest.mark.asyncio
async def test_run_quick_translate_returns_expected_shape():
    req = TranslateRequest(word="evoke", context="The story can evoke deep memories.")
    client = _fake_async_client('{"t":"喚起","p":"v.","r":"evoke"}')
    result = await run_quick_translate(
        req,
        {"id": "u_test"},
        llm=TrackedLLM(client, "u_test"),
        logger=SimpleNamespace(error=lambda *args, **kwargs: None),
    )
    assert result.t == "喚起"
    assert result.p == "v."
    assert result.r == "evoke"


@pytest.mark.asyncio
async def test_run_phrase_translate_returns_expected_shape():
    req = TranslateRequest(word="on trial", context="He was on trial for fraud.")
    client = _fake_async_client('{"t":"受審"}')
    result = await run_phrase_translate(req, {"id": "u_test"}, llm=TrackedLLM(client, "u_test"))
    assert result == {"t": "受審"}


@pytest.mark.asyncio
async def test_run_explain_translate_returns_expected_shape():
    req = TranslateRequest(word="on trial", context="He was on trial for fraud.")
    client = _fake_async_client('{"e":"這裡表示因案件而受審。"}')
    result = await run_explain_translate(req, {"id": "u_test"}, llm=TrackedLLM(client, "u_test"))
    assert result.e == "這裡表示因案件而受審。"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runner", "operation", "content"),
    [
        (run_quick_translate, "translate_quick", '{"p":"v.","r":"evoke"}'),
        (run_quick_translate, "translate_quick", '{"t":"","p":"v.","r":"evoke"}'),
        (run_quick_translate, "translate_quick", "{not valid json"),
        (run_phrase_translate, "translate_phrase", "{}"),
        (run_phrase_translate, "translate_phrase", '{"t":""}'),
        (run_phrase_translate, "translate_phrase", "{not valid json"),
        (run_explain_translate, "translate_explain", '{"context":"extra"}'),
        (run_explain_translate, "translate_explain", '{"e":""}'),
        (run_explain_translate, "translate_explain", "{not valid json"),
    ],
)
async def test_invalid_provider_payload_is_external_error_and_not_cached(runner, operation, content):
    from kg.exceptions import ExternalServiceError

    req = TranslateRequest(word="evoke", context="context")
    client = _fake_async_client(content)
    logger = MagicMock()

    with (
        patch("kg.translate_service.translate_log.lookup", return_value=None),
        patch("kg.translate_service.translate_log.record") as record,
        pytest.raises(ExternalServiceError) as exc_info,
    ):
        await runner(
            req,
            {"id": "u_test"},
            llm=TrackedLLM(client, "u_test"),
            logger=logger,
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.label == f"{operation}/invalid_response"
    record.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_cached_provider_payload_is_not_served_or_counted_as_hit():
    from kg.exceptions import ExternalServiceError

    req = TranslateRequest(word="evoke", context="context")
    client = _fake_async_client('{"t":""}')
    logger = MagicMock()

    with (
        patch("kg.translate_service.translate_log.lookup", return_value='{"t":""}'),
        patch("kg.translate_service.translate_log.record_cache_hit") as record_cache_hit,
        pytest.raises(ExternalServiceError) as exc_info,
    ):
        await run_phrase_translate(
            req,
            {"id": "u_test"},
            llm=TrackedLLM(client, "u_test"),
            logger=logger,
        )

    assert exc_info.value.status_code == 502
    record_cache_hit.assert_not_called()


@pytest.mark.asyncio
async def test_run_quick_translate_raises_on_empty_choices():

    req = TranslateRequest(word="evoke", context="context")
    response = SimpleNamespace(choices=[], usage=None)
    mock_create = AsyncMock(return_value=response)
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=mock_create))
    )
    logger = MagicMock()
    from kg.exceptions import ExternalServiceError
    with pytest.raises(ExternalServiceError) as exc_info:
        await run_quick_translate(req, {"id": "u_test"}, llm=TrackedLLM(client, "u_test"), logger=logger)
    assert exc_info.value.status_code == 502
    logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_async_translate_quota_check_blocks_exceeded():
    """quota check 仍正常運作（exceeded 時 raise 429）"""
    from kg.exceptions import QuotaExceededError

    TranslateRequest(word="evoke", context="context")
    user = {"id": "u_test", "config": {}, "record": None}

    _fake_async_client('{"t":"喚起","p":"v.","r":"evoke"}')

    quota_exceeded = {
        "exceeded": True,
        "fraction": 0.0,
        "reset_seconds": 3600,
    }
    with patch("kg.quota_service.check_and_get_quota", return_value=quota_exceeded):
        from kg.api import _check_quota
        with pytest.raises(QuotaExceededError) as exc_info:
            _check_quota(user, "translate_quick", None)
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_safe_translate_maps_timeout_to_external_service_error():
    """asyncio.wait_for timeout (builtin TimeoutError) must map to ExternalServiceError, not raw 500."""
    from kg.exceptions import ExternalServiceError
    from kg.translate_handlers import _safe_translate

    req = TranslateRequest(word="evoke", context="context")
    user = {"id": "u_test", "config": {}, "record": None}

    async def timing_out(_req, _user, **_kw):
        raise TimeoutError("inflight leader stalled")

    logger = MagicMock()
    with patch("kg.translate_handlers.create_async_client", return_value=_fake_async_client("{}")):
        with pytest.raises(ExternalServiceError) as exc_info:
            await _safe_translate(
                timing_out, req, user,
                call_type="translate_quick", label="translate/quick", logger=logger,
            )
    assert exc_info.value.status_code == 502
    assert exc_info.value.to_detail().get("label") == "translate/quick"
    logger.exception.assert_called_once()


@pytest.mark.asyncio
async def test_safe_translate_maps_httpx_error_to_external_service_error():
    """httpx network errors (non-OpenAIError) must map to ExternalServiceError, not raw 500."""
    import httpx

    from kg.exceptions import ExternalServiceError
    from kg.translate_handlers import _safe_translate

    req = TranslateRequest(word="evoke", context="context")
    user = {"id": "u_test", "config": {}, "record": None}

    async def network_failing(_req, _user, **_kw):
        raise httpx.ConnectError("connection refused")

    logger = MagicMock()
    with patch("kg.translate_handlers.create_async_client", return_value=_fake_async_client("{}")):
        with pytest.raises(ExternalServiceError) as exc_info:
            await _safe_translate(
                network_failing, req, user,
                call_type="translate_quick", label="translate/quick", logger=logger,
            )
    assert exc_info.value.status_code == 502
    logger.exception.assert_called_once()


@pytest.mark.asyncio
async def test_phrase_and_explain_pass_logger_on_error():
    """phrase/explain paths must forward logger so LLM errors are observable."""
    from openai import OpenAIError

    from kg.exceptions import ExternalServiceError
    from kg.translate_handlers import (
        translate_explain_response,
        translate_phrase_response,
    )

    req = TranslateRequest(word="evoke", context="context")
    user = {"id": "u_test", "config": {}, "record": None}

    def raising_factory():
        mock_create = AsyncMock(side_effect=OpenAIError("boom"))
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=mock_create))
        )

    for handler in (translate_phrase_response, translate_explain_response):
        logger = MagicMock()
        with patch("kg.translate_handlers.create_async_client", return_value=raising_factory()):
            with pytest.raises(ExternalServiceError):
                await handler(req, user, logger=logger)
        logger.exception.assert_called_once()


@pytest.mark.asyncio
async def test_translate_handler_does_not_leak_openai_exc_to_client():
    """When upstream raises, ExternalServiceError.to_detail must not embed str(exc)."""
    from openai import OpenAIError

    from kg.exceptions import ExternalServiceError
    from kg.translate_handlers import translate_quick_response

    req = TranslateRequest(word="evoke", context="context")
    user = {"id": "u_test", "config": {}, "record": None}

    secret_msg = "API key sk-leak-me-123 invalid for model gemini-internal"

    def raising_factory():
        mock_create = AsyncMock(side_effect=OpenAIError(secret_msg))
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=mock_create))
        )

    logger = MagicMock()
    with patch("kg.translate_handlers.create_async_client", return_value=raising_factory()):
        with pytest.raises(ExternalServiceError) as exc_info:
            await translate_quick_response(req, user, logger=logger)
    # The wire-format detail must NOT contain the inner exception string
    detail = exc_info.value.to_detail()
    serialized = str(detail)
    assert "sk-leak-me-123" not in serialized
    assert "gemini-internal" not in serialized
    assert detail.get("label") == "translate/quick"
    assert detail.get("code") == "EXTERNAL_SERVICE_ERROR"
    # But the logger must have captured the full context for ops
    assert logger.exception.called or logger.error.called
