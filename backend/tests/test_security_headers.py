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


def _set_public_web_base_url(client, monkeypatch, url):
    import dataclasses

    state = client.app.state
    monkeypatch.setattr(state, "kg_settings", dataclasses.replace(state.kg_settings, public_web_base_url=url))


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

    def test_hsts_sent_when_public_base_url_is_https_over_http_scheme(self, client, monkeypatch):
        # TLS terminates at Cloudflare, so the app sees plain http; HSTS keys off the public URL.
        _set_public_web_base_url(client, monkeypatch, "https://wordnexus.lol")
        assert client.base_url.scheme == "http"
        r = client.get("/privacy")
        assert r.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"

    def test_hsts_not_sent_when_public_base_url_is_http(self, client, monkeypatch):
        _set_public_web_base_url(client, monkeypatch, "http://localhost:8000")
        r = client.get("/privacy")
        assert "Strict-Transport-Security" not in r.headers

    def test_unauthorized_response_has_security_headers(self, client):
        r = client.get("/api/health", headers={"Authorization": "Bearer invalid"})
        assert r.status_code == 401
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_rate_limited_response_has_security_headers(self, client):
        import asyncio
        import collections
        import time

        from kg.app_middleware import anonymous_rate_limit_key
        from kg.rate_limit import api_limiter

        client_ip = "203.0.113.42"
        rate_key = anonymous_rate_limit_key(client_ip)

        async def exhaust():
            dq = api_limiter._requests.setdefault(rate_key, collections.deque())
            now = time.monotonic()
            for _ in range(api_limiter.max_requests):
                dq.append(now)

        asyncio.run(exhaust())

        r = client.get("/api/health", headers={"X-Forwarded-For": client_ip})
        assert r.status_code == 429
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
