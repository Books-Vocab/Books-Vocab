"""Phase 3 — translate call sites route through the LLM provider registry."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kg.api_models import TranslateRequest
from kg.translate_handlers import translate_quick_response

_ROUTING_PREFIX = "LLM_PROVIDER_"
_MODEL_ENV = ("GEMINI_MODEL", "DEEPSEEK_MODEL")

_USER = {"id": "u_route_test", "config": {}, "record": None}
_LOGGER = SimpleNamespace(error=lambda *a, **k: None, exception=lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _clean_routing_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith(_ROUTING_PREFIX) or name in _MODEL_ENV:
            monkeypatch.delenv(name, raising=False)
    yield


def _recording_client(content='{"t":"x","p":"v.","r":"x"}'):
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=None,
    )
    create = AsyncMock(return_value=resp)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.mark.asyncio
async def test_translate_defaults_to_gemini(monkeypatch):
    client = _recording_client()
    monkeypatch.setattr("kg.translate_handlers.create_async_client", lambda provider: client)
    req = TranslateRequest(word="zzqxdefault", context="A zzqxdefault appeared here.")
    await translate_quick_response(req, _USER, logger=_LOGGER)
    call = client.chat.completions.create.call_args.kwargs
    assert call["model"] == "gemini-2.5-flash-lite"
    assert "extra_body" not in call  # gemini injects nothing — behavior unchanged


@pytest.mark.asyncio
async def test_translate_routes_to_deepseek_via_group_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_TRANSLATE", "deepseek")
    client = _recording_client()
    monkeypatch.setattr("kg.translate_handlers.create_async_client", lambda provider: client)
    req = TranslateRequest(word="zzqxdeepseek", context="A zzqxdeepseek appeared here.")
    await translate_quick_response(req, _USER, logger=_LOGGER)
    call = client.chat.completions.create.call_args.kwargs
    assert call["model"] == "deepseek-v4-flash"
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert call["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_translate_per_call_type_env_beats_group(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_TRANSLATE", "deepseek")
    monkeypatch.setenv("LLM_PROVIDER_TRANSLATE_QUICK", "gemini")
    client = _recording_client()
    monkeypatch.setattr("kg.translate_handlers.create_async_client", lambda provider: client)
    req = TranslateRequest(word="zzqxoverride", context="A zzqxoverride appeared here.")
    await translate_quick_response(req, _USER, logger=_LOGGER)
    call = client.chat.completions.create.call_args.kwargs
    assert call["model"] == "gemini-2.5-flash-lite"
    assert "extra_body" not in call  # deepseek's thinking flag must not leak
