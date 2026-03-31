"""Verify CORS allows chrome-extension origins."""
import os

from kg.settings import load_settings


def test_cors_includes_chrome_extension():
    os.environ["CORS_ORIGINS"] = "https://wordnexus.lol,chrome-extension://abcdef123"
    try:
        s = load_settings()
        assert any(o.startswith("chrome-extension://") for o in s.cors_origins)
    finally:
        del os.environ["CORS_ORIGINS"]
