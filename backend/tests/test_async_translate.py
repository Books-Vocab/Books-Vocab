from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kg.api_models import TranslateRequest
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


@pytest.mark.asyncio
async def test_run_quick_translate_returns_expected_shape():
    req = TranslateRequest(word="evoke", context="The story can evoke deep memories.")
    client = _fake_async_client('{"t":"喚起","p":"v.","r":"evoke"}')
    result = await run_quick_translate(
        req,
        {"id": "u_test"},
        client=client,
        logger=SimpleNamespace(error=lambda *args, **kwargs: None),
    )
    assert result.t == "喚起"
    assert result.p == "v."
    assert result.r == "evoke"


@pytest.mark.asyncio
async def test_run_phrase_translate_returns_expected_shape():
    req = TranslateRequest(word="on trial", context="He was on trial for fraud.")
    client = _fake_async_client('{"t":"受審"}')
    result = await run_phrase_translate(req, {"id": "u_test"}, client=client)
    assert result == {"t": "受審"}


@pytest.mark.asyncio
async def test_run_explain_translate_returns_expected_shape():
    req = TranslateRequest(word="on trial", context="He was on trial for fraud.")
    client = _fake_async_client('{"e":"這裡表示因案件而受審。"}')
    result = await run_explain_translate(req, {"id": "u_test"}, client=client)
    assert result.e == "這裡表示因案件而受審。"


@pytest.mark.asyncio
async def test_run_quick_translate_raises_on_empty_choices():
    from fastapi import HTTPException

    req = TranslateRequest(word="evoke", context="context")
    response = SimpleNamespace(choices=[], usage=None)
    mock_create = AsyncMock(return_value=response)
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=mock_create))
    )
    logger = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        await run_quick_translate(req, {"id": "u_test"}, client=client, logger=logger)
    assert exc_info.value.status_code == 500
    logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_async_translate_quota_check_blocks_exceeded():
    """quota check 仍正常運作（exceeded 時 raise 429）"""
    from fastapi import HTTPException

    from kg.translate_handlers import translate_quick_response

    req = TranslateRequest(word="evoke", context="context")
    user = {"id": "u_test", "config": {}, "record": None}

    def _require_pro_access_noop(u, cap):
        pass

    client = _fake_async_client('{"t":"喚起","p":"v.","r":"evoke"}')

    quota_exceeded = {
        "exceeded": True,
        "fraction": 0.0,
        "reset_seconds": 3600,
    }
    with patch("kg.quota_service.check_and_get_quota", return_value=quota_exceeded):
        from kg.api import _check_quota
        with pytest.raises(HTTPException) as exc_info:
            _check_quota(user, "translate_quick", None)
    assert exc_info.value.status_code == 429
