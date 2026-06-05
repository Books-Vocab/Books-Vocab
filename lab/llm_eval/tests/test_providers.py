"""Tests for provider resolution."""

from __future__ import annotations

import os

import pytest

from llm_eval.providers import (
    MissingProviderApiKeyError,
    create_eval_async_client,
    create_eval_client,
    list_available_providers,
    resolve_provider,
)


def test_resolve_cloud_provider():
    p = resolve_provider("gemini")
    assert p.name == "gemini"
    assert p.chat_model == "gemini-2.5-flash-lite"


def test_resolve_deepseek():
    p = resolve_provider("deepseek")
    assert p.name == "deepseek"


def test_resolve_ollama():
    p = resolve_provider("ollama")
    assert p.name == "ollama"
    assert "11434" in p.base_url


def test_resolve_ollama_with_env():
    os.environ["OLLAMA_MODEL"] = "llama3:8b"
    try:
        p = resolve_provider("ollama")
        assert p.chat_model == "llama3:8b"
    finally:
        del os.environ["OLLAMA_MODEL"]


def test_resolve_ollama_host_env():
    os.environ["OLLAMA_HOST"] = "http://192.168.1.100:11434/v1"
    try:
        p = resolve_provider("ollama")
        assert p.base_url == "http://192.168.1.100:11434/v1"
    finally:
        del os.environ["OLLAMA_HOST"]


def test_resolve_unknown():
    with pytest.raises(ValueError):
        resolve_provider("nonexistent")


def test_list_available_providers():
    providers = list_available_providers()
    names = [p.name for p in providers]
    assert "ollama" in names


def test_create_cloud_client_requires_configured_api_key(monkeypatch):
    p = resolve_provider("gemini")
    monkeypatch.delenv(p.api_key_env, raising=False)

    with pytest.raises(MissingProviderApiKeyError, match=p.api_key_env):
        create_eval_client(p)


def test_create_cloud_async_client_requires_configured_api_key(monkeypatch):
    p = resolve_provider("gemini")
    monkeypatch.delenv(p.api_key_env, raising=False)

    with pytest.raises(MissingProviderApiKeyError, match=p.api_key_env):
        create_eval_async_client(p)


def test_create_ollama_client_does_not_require_dummy_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_DUMMY_KEY", raising=False)

    assert create_eval_client(resolve_provider("ollama")) is not None


def test_create_ollama_async_client_does_not_require_dummy_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_DUMMY_KEY", raising=False)

    assert create_eval_async_client(resolve_provider("ollama")) is not None
