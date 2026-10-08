from __future__ import annotations

import re
import secrets
from contextvars import ContextVar
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from conftest import make_jwt, make_settings
from kg.app_middleware import (
    AppMiddlewareDependencies,
    AppMiddlewareRuntime,
    install_app_middlewares,
    install_app_middlewares_from_dependencies,
)
from kg.rate_limit import RateLimiter


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


def test_install_app_middlewares_returns_named_runtime_and_wires_headers(monkeypatch):
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

    close_calls = 0
    original_close = TestClient.close

    def close_and_count(client: TestClient):
        nonlocal close_calls
        close_calls += 1
        original_close(client)

    monkeypatch.setattr(TestClient, "close", close_and_count)
    client = TestClient(app)
    try:
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
    finally:
        client.close()

    assert close_calls == 1


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


# ── rate-limit key derivation (#2056) ─────────────────────────────────────────
#
# The generic limiter used to key on the last 16 characters of the raw
# Authorization header, read *before* any JWT verification. That tail is fully
# client-controlled, so rotating it bought a fresh bucket per request and, at
# the key cap, flooded the table so every new key was rejected. These tests pin
# the replacement contract: only a signature-verified JWT `sub` earns a
# per-user bucket; everything else shares the client-IP bucket; a full table
# never turns into a 429 for a new key.

_LIMIT = 5


def _rate_limited_app(tmp_path, *, max_requests: int = _LIMIT, max_keys: int = 10_000) -> FastAPI:
    app = FastAPI()
    app.state.kg_settings = make_settings(tmp_path)
    limiter = RateLimiter(max_requests=max_requests, window_seconds=60, max_keys=max_keys)
    install_app_middlewares_from_dependencies(
        dependencies=replace(_dependencies(app), api_limiter=limiter, translate_limiter=limiter)
    )

    @app.get("/api/example")
    def example():
        return {"ok": True}

    @app.post("/auth/verify")
    def auth_verify():
        return {"ok": True}

    return app


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_rotating_unverified_authorization_tails_share_the_client_ip_bucket(tmp_path):
    client = TestClient(_rate_limited_app(tmp_path))
    statuses = [client.get("/api/example", headers=_bearer(secrets.token_urlsafe(24))).status_code for _ in range(100)]

    assert statuses.count(200) == _LIMIT
    assert statuses.count(429) == 100 - _LIMIT


def test_non_ascii_authorization_header_falls_back_to_ip_bucket(tmp_path):
    client = TestClient(_rate_limited_app(tmp_path))
    statuses = [
        client.get("/api/example", headers={"Authorization": f"Bearer {i}-é-密".encode()}).status_code
        for i in range(_LIMIT + 1)
    ]

    assert statuses == [200] * _LIMIT + [429]


def test_verified_tokens_for_the_same_user_share_one_bucket(tmp_path):
    client = TestClient(_rate_limited_app(tmp_path))
    first = make_jwt("shared-user", expires_in=timedelta(hours=1))
    second = make_jwt("shared-user", expires_in=timedelta(hours=2))
    assert first[-16:] != second[-16:]

    statuses = [client.get("/api/example", headers=_bearer(token)).status_code for token in [first, second] * _LIMIT]

    assert statuses.count(200) == _LIMIT


def test_verified_user_is_not_charged_for_anonymous_traffic_from_the_same_ip(tmp_path):
    client = TestClient(_rate_limited_app(tmp_path))
    for _ in range(_LIMIT):
        assert client.get("/api/example").status_code == 200
    assert client.get("/api/example").status_code == 429

    response = client.get("/api/example", headers=_bearer(make_jwt("nat-neighbour")))

    assert response.status_code == 200


def test_forged_or_expired_jwt_cannot_spend_the_claimed_users_bucket(tmp_path):
    client = TestClient(_rate_limited_app(tmp_path))
    now = datetime.now(tz=UTC)
    forged = pyjwt.encode(
        {"sub": "victim", "iat": now, "exp": now + timedelta(hours=1)},
        "attacker-chosen-secret-at-least-32-bytes",
        algorithm="HS256",
    )
    expired = make_jwt("victim", expires_in=timedelta(seconds=-60))

    attacker = [client.get("/api/example", headers=_bearer(token)).status_code for token in [forged, expired] * _LIMIT]
    assert attacker.count(200) == _LIMIT

    response = client.get("/api/example", headers=_bearer(make_jwt("victim")))

    assert response.status_code == 200


def test_anonymous_xff_value_cannot_alias_a_verified_user_bucket(tmp_path):
    client = TestClient(_rate_limited_app(tmp_path))
    for _ in range(_LIMIT + 1):
        client.get("/api/example", headers={"X-Forwarded-For": "user:victim"})

    response = client.get("/api/example", headers=_bearer(make_jwt("victim")))

    assert response.status_code == 200


def test_full_key_table_does_not_reject_verified_users_or_auth_verify(tmp_path):
    client = TestClient(_rate_limited_app(tmp_path, max_keys=3))
    for i in range(3):
        filler = client.get("/api/example", headers={"X-Forwarded-For": f"198.51.100.{i}"})
        assert filler.status_code == 200

    verified = client.get("/api/example", headers=_bearer(make_jwt("signed-in-user")))
    sign_in = client.post("/auth/verify", headers={"X-Forwarded-For": "203.0.113.200"})

    assert verified.status_code == 200
    assert sign_in.status_code == 200


def _request_id_probe_app() -> tuple[FastAPI, list[str | None], ContextVar[str]]:
    app = FastAPI()
    captured: list[str | None] = []
    var: ContextVar[str] = ContextVar("request_id")

    @app.get("/api/rid")
    def rid(request: Request):
        return {"state": request.state.request_id, "var": var.get()}

    install_app_middlewares_from_dependencies(
        dependencies=replace(
            _dependencies(app),
            request_id_var=var,
            tag_request_id=lambda r: captured.append(r),
        )
    )
    return app, captured, var


@pytest.mark.parametrize(
    "hostile",
    ["<img src=x onerror=alert(1)>", "a" * 65, "has space", "ü-non-ascii"],
)
def test_invalid_request_id_header_is_replaced_with_generated_id(hostile):
    app, captured, _var = _request_id_probe_app()
    client = TestClient(app)
    try:
        response = client.get("/api/rid", headers={"X-Request-ID": hostile.encode()})
    finally:
        client.close()

    body = response.json()
    generated = response.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{16}", generated)
    assert body["state"] == generated
    assert body["var"] == generated
    assert captured == [generated]


def test_valid_request_id_header_is_propagated_unchanged():
    app, captured, _var = _request_id_probe_app()
    client = TestClient(app)
    try:
        response = client.get("/api/rid", headers={"X-Request-ID": "abc-123_x.y"})
    finally:
        client.close()

    assert response.headers["x-request-id"] == "abc-123_x.y"
    assert response.json() == {"state": "abc-123_x.y", "var": "abc-123_x.y"}
    assert captured == ["abc-123_x.y"]
