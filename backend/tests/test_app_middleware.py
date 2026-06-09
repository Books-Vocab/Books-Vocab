from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kg.app_middleware import (
    AppMiddlewareDependencies,
    AppMiddlewareRuntime,
    install_app_middlewares,
    install_app_middlewares_from_dependencies,
)


class _AllowAllLimiter:
    window_seconds = 60

    async def is_allowed(self, _key: str) -> bool:
        return True


def _dependencies(app: FastAPI) -> AppMiddlewareDependencies:
    return AppMiddlewareDependencies(
        app=app,
        cors_origins=("https://example.com",),
        rate_limit_trusted_hops=1,
        request_id_var=ContextVar("request_id"),
        tag_request_id=lambda _rid: None,
        api_limiter=_AllowAllLimiter(),
        translate_limiter=_AllowAllLimiter(),
    )


def test_install_app_middlewares_returns_named_runtime_and_wires_headers():
    app = FastAPI()

    @app.get("/api/example")
    def example():
        return {"ok": True}

    captured_request_ids: list[str | None] = []
    runtime = install_app_middlewares_from_dependencies(
        dependencies=replace(
            _dependencies(app),
            tag_request_id=lambda rid: captured_request_ids.append(rid),
        )
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


def test_install_app_middlewares_from_dependencies_matches_compat_wrapper():
    named_app = FastAPI()
    compat_app = FastAPI()

    named = install_app_middlewares_from_dependencies(
        dependencies=_dependencies(named_app),
    )
    compat = install_app_middlewares(
        compat_app,
        cors_origins=("https://example.com",),
        rate_limit_trusted_hops=1,
        request_id_var=ContextVar("request_id"),
        tag_request_id=lambda _rid: None,
        api_limiter=_AllowAllLimiter(),
        translate_limiter=_AllowAllLimiter(),
    )

    assert isinstance(named, AppMiddlewareRuntime)
    assert isinstance(compat, AppMiddlewareRuntime)
    assert named.rate_limit_exempt_prefixes == compat.rate_limit_exempt_prefixes


def test_app_middleware_dependencies_are_replaceable_named_contract():
    deps = _dependencies(FastAPI())
    replacement = replace(deps, rate_limit_trusted_hops=2)

    assert deps.rate_limit_trusted_hops == 1
    assert replacement.rate_limit_trusted_hops == 2
