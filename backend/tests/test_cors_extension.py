"""Verify CORS allows chrome-extension origins."""
from kg.settings import load_settings


def test_cors_includes_chrome_extension(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://wordnexus.lol,chrome-extension://abcdef123")
    s = load_settings()
    assert any(o.startswith("chrome-extension://") for o in s.cors_origins)
