"""
Tests for HTTP security response headers middleware.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def client():
    from kg.api import app
    from fastapi.testclient import TestClient

    return TestClient(app, raise_server_exceptions=False)


class TestSecurityHeaders:

    def test_x_content_type_options(self, client):
        r = client.get("/privacy")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        r = client.get("/privacy")
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy(self, client):
        r = client.get("/privacy")
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        r = client.get("/privacy")
        assert r.headers.get("Permissions-Policy") == "camera=(), microphone=(), geolocation=()"

    def test_error_response_has_security_headers(self, client):
        r = client.get("/nonexistent-path-404")
        assert r.status_code == 404
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert r.headers.get("Permissions-Policy") == "camera=(), microphone=(), geolocation=()"

    def test_unauthorized_response_has_security_headers(self, client):
        r = client.get("/api/health", headers={"Authorization": "Bearer invalid"})
        assert r.status_code == 401
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_rate_limited_response_has_security_headers(self, client):
        from kg.rate_limit import api_limiter
        import asyncio
        import time
        import collections

        token = "SECSEC1SECSEC123"
        auth_header = f"Bearer {token}"
        rate_key = auth_header[-16:]

        async def exhaust():
            dq = api_limiter._requests.setdefault(rate_key, collections.deque())
            now = time.monotonic()
            for _ in range(api_limiter.max_requests):
                dq.append(now)

        asyncio.run(exhaust())

        r = client.get("/api/health", headers={"Authorization": auth_header})
        assert r.status_code == 429
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
