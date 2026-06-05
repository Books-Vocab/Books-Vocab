"""Tests for the pluggable LLM provider registry + per-call-type routing."""
from __future__ import annotations

import pytest

from kg.llm.providers import REGISTRY, LLMProvider, provider_for


@pytest.fixture(autouse=True)
def _clean_routing_env(clean_routing_env):
    yield


def test_registry_has_gemini_and_deepseek():
    assert {"gemini", "deepseek"} <= set(REGISTRY)
    for name, prov in REGISTRY.items():
        assert isinstance(prov, LLMProvider)
        assert prov.name == name
        assert prov.base_url.startswith("https://")
        assert prov.api_key_env
        assert prov.chat_model


def test_default_routing_is_gemini():
    for ct in ("translate_quick", "translate_phrase", "translate_explain",
               "judge", "enrich", "judge_manual"):
        assert provider_for(ct).name == "gemini"


def test_llm_provider_default_routes_all_chat_call_types(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_DEFAULT", "deepseek")
    for ct in ("translate_quick", "judge", "enrich", "judge_manual"):
        assert provider_for(ct).name == "deepseek"


def test_per_call_type_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_JUDGE", "deepseek")
    assert provider_for("judge").name == "deepseek"
    assert provider_for("enrich").name == "gemini"
    assert provider_for("translate_quick").name == "gemini"


def test_judge_group_covers_manual_link_judge(monkeypatch):
    """LLM_PROVIDER_JUDGE must cover manual link judging (judge_manual)
    alongside the auto pipeline judge — they belong to the same group."""
    monkeypatch.setenv("LLM_PROVIDER_JUDGE", "deepseek")
    assert provider_for("judge_manual").name == "deepseek"
    assert provider_for("judge").name == "deepseek"


def test_judge_manual_default_routes_with_judge(monkeypatch):
    """Absent overrides, judge_manual resolves like judge → gemini default."""
    assert provider_for("judge_manual").name == "gemini"


def test_per_call_type_beats_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_DEFAULT", "gemini")
    monkeypatch.setenv("LLM_PROVIDER_JUDGE", "deepseek")
    assert provider_for("judge").name == "deepseek"
    assert provider_for("enrich").name == "gemini"


def test_translate_group_knob(monkeypatch):
    """LLM_PROVIDER_TRANSLATE flips all translate_* in one env var."""
    monkeypatch.setenv("LLM_PROVIDER_TRANSLATE", "deepseek")
    for ct in ("translate_quick", "translate_phrase", "translate_explain"):
        assert provider_for(ct).name == "deepseek"
    assert provider_for("judge").name == "gemini"


def test_exact_call_type_beats_group(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_TRANSLATE", "deepseek")
    monkeypatch.setenv("LLM_PROVIDER_TRANSLATE_QUICK", "gemini")
    assert provider_for("translate_quick").name == "gemini"
    assert provider_for("translate_phrase").name == "deepseek"


def test_embed_ignores_chat_default(monkeypatch):
    """Flipping the chat default must never break embeddings."""
    monkeypatch.setenv("LLM_PROVIDER_DEFAULT", "deepseek")
    assert provider_for("embed").name == "gemini"


def test_embed_explicit_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_EMBED", "gemini")
    assert provider_for("embed").name == "gemini"


def test_embed_rejects_non_embedding_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_EMBED", "deepseek")
    with pytest.raises(ValueError, match="embedding"):
        provider_for("embed")


def test_unknown_provider_name_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_DEFAULT", "bogus")
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        provider_for("judge")


def test_model_env_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_DEFAULT", "deepseek")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    assert provider_for("judge").chat_model == "deepseek-v4-pro"


def test_gemini_model_env_backward_compat(monkeypatch):
    """GEMINI_MODEL keeps overriding the gemini model (legacy behavior)."""
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3-flash")
    assert provider_for("translate_quick").chat_model == "gemini-3-flash"


def test_deepseek_extra_body_disables_thinking():
    assert REGISTRY["deepseek"].extra_body == {"thinking": {"type": "disabled"}}


def test_gemini_extra_body_is_empty():
    assert REGISTRY["gemini"].extra_body == {}


def test_deepseek_has_no_embeddings_and_gemini_does():
    assert REGISTRY["deepseek"].supports_embeddings is False
    assert REGISTRY["gemini"].supports_embeddings is True


def test_empty_env_value_falls_through(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_JUDGE", "")
    monkeypatch.setenv("LLM_PROVIDER_DEFAULT", "")
    assert provider_for("judge").name == "gemini"


def test_call_type_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_JUDGE", "deepseek")
    assert provider_for("JUDGE").name == "deepseek"
    assert provider_for("Embed").name == "gemini"


def test_empty_call_type_resolves_to_default():
    assert provider_for("").name == "gemini"
