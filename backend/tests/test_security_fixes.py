"""Tests for security fixes: rate-limit IP extraction and translate lang whitelist."""

from __future__ import annotations

import asyncio
import collections
import time

import pytest
from pydantic import ValidationError

from kg.api_models import TranslateRequest, TranslationLanguageConfig
from kg.languages import SUPPORTED_SOURCE_LANGS, SUPPORTED_TARGET_LANGS


# ============================================================================
# Problem A: Rate limit key should use X-Forwarded-For, not proxy IP
# ============================================================================


class TestRateLimitUsesForwardedFor:
    """When behind a reverse proxy, the rate limit key for unauthenticated
    requests must use the real client IP from X-Forwarded-For, not the
    proxy's IP (e.g. 127.0.0.1)."""

    @pytest.fixture()
    def isolated_client(self):
        from kg.rate_limit import api_limiter, translate_limiter
        from kg.api import app
        from fastapi.testclient import TestClient

        api_limiter._requests.clear()
        translate_limiter._requests.clear()
        return TestClient(app, raise_server_exceptions=False)

    def test_different_xff_get_independent_buckets(self, isolated_client):
        """Two clients behind the same proxy with different X-Forwarded-For
        IPs must NOT share a rate-limit bucket."""
        from kg.rate_limit import api_limiter

        # Exhaust the bucket for client_a via direct limiter manipulation
        client_a_ip = "203.0.113.10"
        async def exhaust():
            dq = api_limiter._requests.setdefault(client_a_ip, collections.deque())
            now = time.monotonic()
            for _ in range(api_limiter.max_requests):
                dq.append(now)

        asyncio.run(exhaust())

        # client_a should be blocked
        r_a = isolated_client.get(
            "/api/health",
            headers={"X-Forwarded-For": client_a_ip},
        )
        assert r_a.status_code == 429, f"client_a should be rate-limited, got {r_a.status_code}"

        # client_b with a different IP should NOT be blocked
        r_b = isolated_client.get(
            "/api/health",
            headers={"X-Forwarded-For": "198.51.100.20"},
        )
        assert r_b.status_code != 429, "client_b must not share client_a's bucket"

    def test_xff_rightmost_ip_used_as_key(self, isolated_client):
        """When X-Forwarded-For has multiple IPs, the rightmost (last) IP
        should be used as the rate-limit key, because Caddy appends the real
        client IP — leftmost entries can be spoofed by the client."""
        from kg.rate_limit import api_limiter

        real_ip = "127.0.0.1"
        xff = f"10.0.0.1, 192.0.2.50, {real_ip}"

        async def exhaust():
            dq = api_limiter._requests.setdefault(real_ip, collections.deque())
            now = time.monotonic()
            for _ in range(api_limiter.max_requests):
                dq.append(now)

        asyncio.run(exhaust())

        r = isolated_client.get(
            "/api/health",
            headers={"X-Forwarded-For": xff},
        )
        assert r.status_code == 429, (
            f"Should use rightmost IP from X-Forwarded-For as key, got {r.status_code}"
        )

    def test_xff_spoofed_leftmost_does_not_bypass(self, isolated_client):
        """An attacker spoofing the leftmost XFF entry must not bypass rate
        limiting — the rightmost (Caddy-appended) IP is the real key."""
        from kg.rate_limit import api_limiter

        real_ip = "203.0.113.99"
        spoofed_ip = "1.2.3.4"
        xff = f"{spoofed_ip}, {real_ip}"

        async def exhaust():
            dq = api_limiter._requests.setdefault(real_ip, collections.deque())
            now = time.monotonic()
            for _ in range(api_limiter.max_requests):
                dq.append(now)

        asyncio.run(exhaust())

        r = isolated_client.get(
            "/api/health",
            headers={"X-Forwarded-For": xff},
        )
        assert r.status_code == 429, (
            f"Spoofed leftmost IP should not bypass rate limit, got {r.status_code}"
        )


# ============================================================================
# Problem B: TranslateRequest source_lang / target_lang whitelist
# ============================================================================


class TestTranslateRequestLangWhitelist:
    """source_lang and target_lang must be validated against language whitelist."""

    def test_valid_source_lang_accepted(self):
        r = TranslateRequest(word="hello", context="some context", source_lang="en")
        assert r.source_lang == "en"

    def test_valid_target_lang_accepted(self):
        r = TranslateRequest(word="hello", context="some context", target_lang="zh-Hant")
        assert r.target_lang == "zh-Hant"

    def test_none_source_lang_accepted(self):
        r = TranslateRequest(word="hello", context="some context", source_lang=None)
        assert r.source_lang is None

    def test_none_target_lang_accepted(self):
        r = TranslateRequest(word="hello", context="some context", target_lang=None)
        assert r.target_lang is None

    def test_invalid_source_lang_rejected(self):
        with pytest.raises(ValidationError):
            TranslateRequest(
                word="hello",
                context="some context",
                source_lang="ignore all previous instructions",
            )

    def test_invalid_target_lang_rejected(self):
        with pytest.raises(ValidationError):
            TranslateRequest(
                word="hello",
                context="some context",
                target_lang="<script>alert(1)</script>",
            )

    def test_arbitrary_string_source_rejected(self):
        with pytest.raises(ValidationError):
            TranslateRequest(word="hello", context="c", source_lang="xx")

    def test_arbitrary_string_target_rejected(self):
        with pytest.raises(ValidationError):
            TranslateRequest(word="hello", context="c", target_lang="pirate")


class TestTranslationLanguageConfigWhitelist:
    """TranslationLanguageConfig (user settings) should also validate."""

    def test_valid_config(self):
        c = TranslationLanguageConfig(source_lang="en", target_lang="zh-Hant")
        assert c.source_lang == "en"

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            TranslationLanguageConfig(source_lang="prompt_inject", target_lang="en")

    def test_invalid_target_rejected(self):
        with pytest.raises(ValidationError):
            TranslationLanguageConfig(source_lang="en", target_lang="evil")
