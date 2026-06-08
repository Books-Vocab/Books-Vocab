from __future__ import annotations

from contextvars import ContextVar
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kg.app_middleware import AppMiddlewareRuntime, install_app_middlewares


class _AllowAllLimiter:
    window_seconds = 60

    async def is_allowed(self, _key: str) -> bool:
        return True


def test_install_app_middlewares_returns_named_runtime_and_wires_headers():
    app = FastAPI()

    @app.get("/api/example")
    def example():
        return {"ok": True}

    captured_request_ids: list[str | None] = []
    runtime = install_app_middlewares(
        app,
        cors_origins=("https://example.com",),
        rate_limit_trusted_hops=1,
        request_id_var=ContextVar("request_id"),
        tag_request_id=lambda rid: captured_request_ids.append(rid),
        api_limiter=_AllowAllLimiter(),
        translate_limiter=_AllowAllLimiter(),
    )

    assert isinstance(runtime, AppMiddlewareRuntime)
    assert "/auth/web/google/callback" in runtime.rate_limit_exempt_prefixes

    client = TestClient(app)
    response = client.get(
        "/api/example",
        headers={"X-Request-ID": "req-123", "Origin": "https://example.com"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-123"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["access-control-allow-origin"] == "https://example.com"
    assert captured_request_ids == ["req-123"]
