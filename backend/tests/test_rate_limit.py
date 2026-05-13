"""
Tests for in-memory per-user sliding window rate limiter and middleware.
"""

from __future__ import annotations

import asyncio

import pytest

from kg.rate_limit import RateLimiter


# ============================================================================
# Unit tests for RateLimiter
# ============================================================================


class TestRateLimiterAllows:

    def test_requests_within_limit_are_allowed(self):
        async def run():
            limiter = RateLimiter(max_requests=5, window_seconds=60)
            results = [await limiter.is_allowed("user1") for _ in range(5)]
            return results

        results = asyncio.run(run())
        assert all(results), "All requests within limit should be allowed"

    def test_request_exceeding_limit_is_rejected(self):
        async def run():
            limiter = RateLimiter(max_requests=3, window_seconds=60)
            for _ in range(3):
                await limiter.is_allowed("user1")
            return await limiter.is_allowed("user1")

        allowed = asyncio.run(run())
        assert not allowed, "Request exceeding limit should be rejected"

    def test_different_keys_have_independent_counters(self):
        async def run():
            limiter = RateLimiter(max_requests=2, window_seconds=60)
            for _ in range(2):
                await limiter.is_allowed("user_a")
            # user_b should still be allowed despite user_a being exhausted
            return await limiter.is_allowed("user_b")

        allowed = asyncio.run(run())
        assert allowed, "Different keys must have independent counters"

    def test_window_expiry_restores_allowance(self):
        import time

        async def run():
            limiter = RateLimiter(max_requests=2, window_seconds=1)
            await limiter.is_allowed("user1")
            await limiter.is_allowed("user1")
            # Exhaust — should be rejected now
            rejected = not await limiter.is_allowed("user1")

            # Manually age the timestamps past the window
            dq = limiter._requests["user1"]
            old_ts = time.monotonic() - 2
            for i in range(len(dq)):
                dq[i] = old_ts
            # Now window should have expired and request is allowed
            allowed_after_expire = await limiter.is_allowed("user1")
            return rejected, allowed_after_expire

        rejected, allowed = asyncio.run(run())
        assert rejected, "Should be rejected after exhausting limit"
        assert allowed, "Should be allowed again after window expires"


# ============================================================================
# Middleware integration tests (whitelist paths)
# ============================================================================


class TestRateLimitMiddlewareWhitelist:

    @pytest.fixture()
    def client(self):
        from kg.api import app
        from fastapi.testclient import TestClient

        return TestClient(app, raise_server_exceptions=False)

    def test_privacy_not_rate_limited(self, client):
        # Hit /privacy many times — should never get 429
        for _ in range(70):
            r = client.get("/privacy")
            assert r.status_code != 429, "/privacy must be exempt from rate limiting"

    def test_docs_not_rate_limited(self, client):
        for _ in range(70):
            r = client.get("/docs")
            assert r.status_code != 429, "/docs must be exempt from rate limiting"

    def test_openapi_json_not_rate_limited(self, client):
        for _ in range(70):
            r = client.get("/openapi.json")
            assert r.status_code != 429, "/openapi.json must be exempt from rate limiting"

    def test_google_oauth_callback_not_rate_limited(self, client):
        """OAuth callbacks come from Google and ar single shots per login.
        A rate-limit 429 on the callback means the user can't sign in. The
        callback is naturally rare-per-IP but the limiter keys off the
        Authorization header tail / XFF, both of which can collide across
        users behind shared NAT. Exempt the path."""
        from kg.rate_limit import api_limiter
        api_limiter._requests.clear()
        # Hammer with no auth — should never get 429. Real callback will
        # error 400/401 (missing code / bad state) but must not be 429.
        for _ in range(api_limiter.max_requests + 30):
            r = client.get("/auth/web/google/callback")
            assert r.status_code != 429, (
                f"OAuth callback must be exempt from rate limiting (got {r.status_code})"
            )

    def test_apple_oauth_callback_not_rate_limited(self, client):
        from kg.rate_limit import api_limiter
        api_limiter._requests.clear()
        for _ in range(api_limiter.max_requests + 30):
            # Apple uses POST callback; the rate-limit middleware acts on all
            # methods, so a POST without form body should still bypass.
            r = client.post("/auth/web/apple/callback")
            assert r.status_code != 429, (
                f"Apple OAuth callback must be exempt from rate limiting (got {r.status_code})"
            )


# ============================================================================
# Rate limit enforcement via middleware (429 + Retry-After)
# ============================================================================


class TestRateLimitMiddlewareEnforcement:

    @pytest.fixture()
    def isolated_client(self):
        """Client with freshly reset limiters so test isolation is guaranteed."""
        from kg.rate_limit import api_limiter, translate_limiter
        from kg.api import app
        from fastapi.testclient import TestClient
        from unittest.mock import patch

        # Reset limiter state
        api_limiter._requests.clear()
        translate_limiter._requests.clear()

        return TestClient(app, raise_server_exceptions=False)

    def test_normal_request_passes(self, isolated_client):
        r = isolated_client.get("/privacy")
        assert r.status_code != 429

    def test_exceeding_api_limit_returns_429(self, isolated_client):
        from kg.rate_limit import api_limiter
        import time

        token = "AAAA0000BBBB1111"
        auth_header = f"Bearer {token}"
        rate_key = auth_header[-16:]

        async def exhaust():
            dq = api_limiter._requests.setdefault(rate_key, __import__("collections").deque())
            now = time.monotonic()
            for _ in range(api_limiter.max_requests):
                dq.append(now)

        asyncio.run(exhaust())

        r = isolated_client.get(
            "/api/health",
            headers={"Authorization": auth_header},
        )
        assert r.status_code == 429, f"Expected 429, got {r.status_code}"
        assert "Retry-After" in r.headers

    def test_retry_after_header_present_on_429(self, isolated_client):
        from kg.rate_limit import api_limiter
        import time
        import collections

        token = "CCCC2222DDDD3333"
        auth_header = f"Bearer {token}"
        rate_key = auth_header[-16:]

        async def exhaust():
            dq = api_limiter._requests.setdefault(rate_key, collections.deque())
            now = time.monotonic()
            for _ in range(api_limiter.max_requests):
                dq.append(now)

        asyncio.run(exhaust())

        r = isolated_client.get(
            "/api/health",
            headers={"Authorization": auth_header},
        )
        assert r.status_code == 429
        assert r.headers.get("Retry-After") == str(api_limiter.window_seconds)
