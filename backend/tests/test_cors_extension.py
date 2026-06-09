"""Verify CORS allows chrome-extension origins."""
from conftest import TEST_PUBLIC_WEB_BASE_URL
from kg.settings import load_settings


def test_cors_includes_chrome_extension(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", f"{TEST_PUBLIC_WEB_BASE_URL},chrome-extension://abcdef123")
    s = load_settings()
    assert any(o.startswith("chrome-extension://") for o in s.cors_origins)
