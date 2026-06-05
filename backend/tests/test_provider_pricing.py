"""Phase 5 — quota_service.token_cost_usd prices each call_type by its
currently-routed provider."""
from __future__ import annotations

import pytest

from kg.quota_service import token_cost_usd


@pytest.fixture(autouse=True)
def _clean_env(clean_routing_env):
    yield


def test_chat_cost_uses_gemini_pricing_by_default():
    # gemini: $0.10/1M input, $0.40/1M output
    assert token_cost_usd("judge", 1_000_000, 1_000_000) == pytest.approx(0.50)


def test_chat_cost_uses_deepseek_pricing_when_routed(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_JUDGE", "deepseek")
    # deepseek: $0.14/1M input, $0.28/1M output
    assert token_cost_usd("judge", 1_000_000, 1_000_000) == pytest.approx(0.42)


def test_embed_cost_independent_of_chat_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_DEFAULT", "deepseek")
    # embed never inherits the chat default → gemini embed price $0.00025/1M
    assert token_cost_usd("embed", 1_000_000, 0) == pytest.approx(0.00025)
