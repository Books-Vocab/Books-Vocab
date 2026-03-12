from __future__ import annotations

import pytest

from fastapi import HTTPException

import kg.service_factories as sf


def setup_function():
    sf.reset_gemini_client()


def test_same_instance_returned(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    c1 = sf.create_gemini_client()
    c2 = sf.create_gemini_client()
    assert c1 is c2


def test_reset_creates_new_instance(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    c1 = sf.create_gemini_client()
    sf.reset_gemini_client()
    c2 = sf.create_gemini_client()
    assert c1 is not c2


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        sf.create_gemini_client()
    assert exc_info.value.status_code == 500
