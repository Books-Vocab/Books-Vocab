"""
Tests for HTTP security response headers middleware.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from kg.api import app

    test_client = TestClient(app, raise_server_exceptions=False)
    try:
        yield test_client
    finally:
        test_client.close()


def test_client_fixture_closes_owned_client(monkeypatch):
    events = []

    class FakeTestClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            events.append("enter")
            raise AssertionError("fixture must not start the app lifespan")

        def close(self):
            events.append("close")

    monkeypatch.setattr("fastapi.testclient.TestClient", FakeTestClient)
    fixture_generator = client.__wrapped__()

    next(fixture_generator)
    fixture_generator.close()

    assert events == ["close"]


class TestSecurityHeaders:

    @pytest.mark.parametrize(
        ("header_name", "expected_value"),
        [
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "strict-origin-when-cross-origin"),
            ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
        ],
    )
    def test_single_security_header(self, client, header_name, expected_value):
        r = client.get("/privacy")
        assert r.headers.get(header_name) == expected_value

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
        import asyncio
        import collections
        import time

        from kg.rate_limit import api_limiter

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
