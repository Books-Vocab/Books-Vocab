"""Phase 2 — per-provider client factory + TrackedLLM provider-aware injection."""
from __future__ import annotations

import asyncio
import contextlib

import pytest

from kg.llm.providers import REGISTRY
from kg.tracked_llm import TrackedLLM


@pytest.fixture(autouse=True)
def _reset_client_cache():
    from kg import service_factories as sf
    _close_client_caches(sf)
    yield
    _close_client_caches(sf)


def _close_client_caches(sf):
    sf.reset_clients()
    asyncio.run(sf.reset_async_clients())


@pytest.fixture(autouse=True)
def _no_quota(monkeypatch):
    """Keep TrackedLLM tests pure — no quota reservation, no token DB write."""
    @contextlib.contextmanager
    def fake_reserve(*a, **k):
        yield
    monkeypatch.setattr("kg.tracked_llm.reserve", fake_reserve)
    monkeypatch.setattr("kg.tracked_llm.record", lambda *a, **k: None)


# ── client factory ───────────────────────────────────────────────────────

def test_create_client_uses_provider_base_url(monkeypatch):
    from kg.service_factories import create_client
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-ds-key")
    c = create_client(REGISTRY["deepseek"])
    assert str(c.base_url).rstrip("/") == "https://api.deepseek.com"


def test_create_client_caches_per_provider(monkeypatch):
    from kg.service_factories import create_client
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-ds-key")
    assert create_client(REGISTRY["gemini"]) is create_client(REGISTRY["gemini"])
    assert create_client(REGISTRY["deepseek"]) is create_client(REGISTRY["deepseek"])
    assert create_client(REGISTRY["gemini"]) is not create_client(REGISTRY["deepseek"])


def test_create_client_missing_api_key_raises(monkeypatch):
    from kg.service_factories import create_client
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        create_client(REGISTRY["deepseek"])


def test_create_gemini_client_alias_shares_cache():
    from kg.service_factories import create_client, create_gemini_client
    assert create_gemini_client() is create_client(REGISTRY["gemini"])


def test_create_async_client_uses_provider_base_url(monkeypatch):
    from kg.service_factories import create_async_client
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-ds-key")
    c = create_async_client(REGISTRY["deepseek"])
    assert str(c.base_url).rstrip("/") == "https://api.deepseek.com"
    assert create_async_client(REGISTRY["deepseek"]) is c


def test_client_cache_cleanup_closes_transports(monkeypatch):
    from kg import service_factories as sf
    from kg.service_factories import create_async_client, create_client

    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-ds-key")
    sync_client = create_client(REGISTRY["deepseek"])
    async_client = create_async_client(REGISTRY["deepseek"])

    _close_client_caches(sf)

    assert sync_client._client.is_closed is True
    assert async_client._client.is_closed is True


# ── TrackedLLM provider-aware injection ──────────────────────────────────

class _Usage:
    prompt_tokens = 10
    completion_tokens = 5


class _Resp:
    usage = _Usage()


class _Completions:
    def __init__(self):
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp()


class _AsyncCompletions:
    def __init__(self):
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp()


class _FakeClient:
    def __init__(self, async_=False):
        self.chat = type("C", (), {})()
        self.chat.completions = _AsyncCompletions() if async_ else _Completions()


def _last(client):
    return client.chat.completions.calls[-1]


def test_deepseek_provider_injects_thinking_disabled():
    client = _FakeClient()
    tl = TrackedLLM(client, "u1", provider=REGISTRY["deepseek"])
    tl.chat("judge", model="deepseek-v4-flash", messages=[{"role": "user", "content": "x"}])
    assert _last(client)["extra_body"] == {"thinking": {"type": "disabled"}}


def test_deepseek_provider_injects_max_tokens():
    client = _FakeClient()
    tl = TrackedLLM(client, "u1", provider=REGISTRY["deepseek"])
    tl.chat("enrich", model="deepseek-v4-flash", messages=[])
    assert _last(client)["max_tokens"] == 8192


def test_caller_max_tokens_not_overridden():
    client = _FakeClient()
    tl = TrackedLLM(client, "u1", provider=REGISTRY["deepseek"])
    tl.chat("enrich", model="deepseek-v4-flash", messages=[], max_tokens=256)
    assert _last(client)["max_tokens"] == 256


def test_caller_extra_body_merges_and_wins_on_conflict():
    client = _FakeClient()
    tl = TrackedLLM(client, "u1", provider=REGISTRY["deepseek"])
    tl.chat("judge", model="m", messages=[],
            extra_body={"thinking": {"type": "enabled"}, "foo": 1})
    eb = _last(client)["extra_body"]
    assert eb == {"thinking": {"type": "enabled"}, "foo": 1}


def test_gemini_provider_injects_nothing():
    client = _FakeClient()
    tl = TrackedLLM(client, "u1", provider=REGISTRY["gemini"])
    tl.chat("translate_quick", model="gemini-2.5-flash-lite", messages=[])
    call = _last(client)
    assert "extra_body" not in call
    assert "max_tokens" not in call


def test_no_provider_injects_nothing():
    """Legacy construction (no provider) keeps exact current behavior."""
    client = _FakeClient()
    tl = TrackedLLM(client, "u1")
    tl.chat("translate_quick", model="m", messages=[])
    call = _last(client)
    assert "extra_body" not in call
    assert "max_tokens" not in call


def test_registry_dict_not_mutated_by_injection():
    client = _FakeClient()
    tl = TrackedLLM(client, "u1", provider=REGISTRY["deepseek"])
    tl.chat("judge", model="m", messages=[], extra_body={"foo": 1})
    assert REGISTRY["deepseek"].extra_body == {"thinking": {"type": "disabled"}}


def test_chat_async_injects_extra_body():
    client = _FakeClient(async_=True)
    tl = TrackedLLM(client, "u1", provider=REGISTRY["deepseek"])
    asyncio.run(tl.chat_async("translate_quick", model="m", messages=[]))
    assert _last(client)["extra_body"] == {"thinking": {"type": "disabled"}}
    assert _last(client)["max_tokens"] == 8192


def test_caller_extra_body_none_uses_provider_default():
    """Explicit extra_body=None must not suppress the provider default."""
    client = _FakeClient()
    tl = TrackedLLM(client, "u1", provider=REGISTRY["deepseek"])
    tl.chat("judge", model="m", messages=[], extra_body=None)
    assert _last(client)["extra_body"] == {"thinking": {"type": "disabled"}}
