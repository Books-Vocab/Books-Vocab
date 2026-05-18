"""Phase 5 — manual link creation routes through the LLM provider registry."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from kg.api_models import ManualLinkRequest
from kg.vocab_handlers.graph import create_manual_link_response

_PREFIX = "LLM_PROVIDER_"
_JUDGE_JSON = '{"link": "shares_usage", "confidence": 0.9, "reason": "相關"}'
_USER = {"id": "u_ml", "dir": "/tmp/u_ml"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith(_PREFIX) or name in ("GEMINI_MODEL", "DEEPSEEK_MODEL"):
            monkeypatch.delenv(name, raising=False)
    yield


def _mock_client(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage = None
    client.chat.completions.create.return_value = resp
    return client


def _recorder(content):
    seen: list[str] = []
    clients: list = []

    def factory(provider):
        seen.append(provider.name)
        c = _mock_client(content)
        clients.append(c)
        return c

    return factory, seen, clients


def _card(cid, content):
    return SimpleNamespace(id=cid, content=content, meaning=f"m-{content}",
                           is_deleted=False, is_archived=False)


class _Cards:
    def __init__(self):
        self._c = {"a": _card("a", "alpha"), "b": _card("b", "beta")}

    def get(self, cid):
        return self._c.get(cid)

    def touch(self, cid):
        pass


class _Link:
    def __init__(self, kind, reason):
        self.id, self.from_id, self.to_id = "L1", "a", "b"
        self.kind, self.confidence, self.reason = kind, 1.0, reason


class _Graph:
    def find_link_between(self, a, b):
        return None

    def is_blocked(self, a, b):
        return False

    def add_link(self, fr, to, kind, confidence, reason):
        return _Link(kind, reason)


def _run(client_factory):
    return create_manual_link_response(
        ManualLinkRequest(from_id="a", to_id="b"),
        _USER,
        card_store_factory=lambda d: _Cards(),
        graph_store_factory=lambda d, notebook_id="default": _Graph(),
        client_factory=client_factory,
        notebook_id="default",
    )


def test_manual_link_routes_to_gemini_by_default():
    factory, seen, clients = _recorder(_JUDGE_JSON)
    _run(factory)
    assert seen == ["gemini"]
    call = clients[0].chat.completions.create.call_args.kwargs
    assert call["model"] == "gemini-2.5-flash-lite"
    assert "extra_body" not in call


def test_manual_link_routes_to_deepseek_via_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_MANUAL_LINK_JUDGE", "deepseek")
    factory, seen, clients = _recorder(_JUDGE_JSON)
    _run(factory)
    assert seen == ["deepseek"]
    call = clients[0].chat.completions.create.call_args.kwargs
    assert call["model"] == "deepseek-v4-flash"
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
