"""Unit tests for translate_handlers._safe_translate exception mapping.

`_safe_translate` is the single choke point that turns translate-pipeline
failures into a stable HTTP surface. These tests pin each exception branch and,
critically, the security invariant that inner exception text never leaks into a
client-visible 500 detail. Provider/client construction is monkeypatched out so
the tests exercise only the error-mapping logic.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from openai import OpenAIError

from kg import translate_handlers as th
from kg.api_models import TranslateRequest
from kg.exceptions import ExternalServiceError, KGError

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _isolate_provider(monkeypatch):
    """Stub provider/client construction so only error mapping is under test."""
    monkeypatch.setattr(th, "provider_for", lambda call_type: SimpleNamespace(chat_model="m"))
    monkeypatch.setattr(th, "create_async_client", lambda provider: object())
    monkeypatch.setattr(th, "TrackedLLM", lambda client, uid, provider=None, **_kwargs: object())


def _run(exc):
    """Call _safe_translate with a coro that raises ``exc``; return the coroutine."""

    async def boom(req, user, **kw):
        raise exc

    return th._safe_translate(
        boom,
        TranslateRequest(word="x"),
        {"id": "u1"},
        call_type="translate_quick",
        label="translate/quick",
    )


async def test_success_passthrough():
    async def ok(req, user, **kw):
        return {"ok": True}

    result = await th._safe_translate(
        ok,
        TranslateRequest(word="x"),
        {"id": "u1"},
        call_type="translate_quick",
        label="translate/quick",
    )
    assert result == {"ok": True}


async def test_http_exception_passes_through_unchanged():
    original = HTTPException(429, "rate limited")
    with pytest.raises(HTTPException) as ei:
        await _run(original)
    assert ei.value is original  # re-raised, not rewrapped


async def test_openai_error_maps_to_external_service_error():
    with pytest.raises(ExternalServiceError) as ei:
        await _run(OpenAIError("upstream boom"))
    assert ei.value.label == "translate/quick"
    assert ei.value.to_detail() == {"code": "EXTERNAL_SERVICE_ERROR", "label": "translate/quick"}


async def test_client_setup_errors_map_to_opaque_500(monkeypatch):
    def fail_client_setup(_provider):
        raise RuntimeError("GEMINI_API_KEY=secret was not configured")

    monkeypatch.setattr(th, "create_async_client", fail_client_setup)

    async def never_called(req, user, **kw):
        raise AssertionError("translation coroutine must not be called")

    with pytest.raises(KGError) as ei:
        await th._safe_translate(
            never_called,
            TranslateRequest(word="x"),
            {"id": "u1"},
            call_type="translate_quick",
            label="translate/quick",
        )

    assert ei.value.status_code == 500
    assert str(ei.value) == "translate/quick failed"
    assert "secret" not in str(ei.value.to_detail())


@pytest.mark.parametrize("exc", [TimeoutError("waited"), httpx.ConnectError("no route")])
async def test_timeout_and_network_errors_map_to_external_service_error(exc):
    with pytest.raises(ExternalServiceError) as ei:
        await _run(exc)
    assert ei.value.label == "translate/quick"


@pytest.mark.parametrize(
    "exc",
    [ValueError("secret-detail"), KeyError("k"), TypeError("t"), RuntimeError("r")],
)
async def test_value_errors_map_to_opaque_500(exc):
    # Service layer raises a domain KGError (status_code 500); the api.py
    # exception handler renders it to an opaque HTTP 500.
    with pytest.raises(KGError) as ei:
        await _run(exc)
    assert ei.value.status_code == 500
    assert str(ei.value) == "translate/quick failed"
    assert ei.value.to_detail() == {"code": "KGError", "detail": "translate/quick failed"}


async def test_inner_exception_text_not_leaked_to_client():
    """Security: the opaque 500 must not embed the inner exception message."""
    with pytest.raises(KGError) as ei:
        await _run(ValueError("DB_PASSWORD=hunter2 leaked"))
    detail = ei.value.to_detail()
    assert "hunter2" not in str(detail)
    assert str(ei.value) == "translate/quick failed"
