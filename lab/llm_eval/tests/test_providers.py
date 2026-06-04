"""Tests for provider resolution."""

from __future__ import annotations

import os

import pytest

from llm_eval.providers import OLLAMA_PROVIDER, list_available_providers, resolve_provider


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
