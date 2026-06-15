"""Tests for the web OAuth flow."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.deps as deps_mod
from conftest import TEST_GOOGLE_REDIRECT_URI, TEST_JWT_SECRET, _swap_settings
from kg.api import app
from kg.settings import KGSettings


@pytest.fixture()
def web_auth_env(tmp_path):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({}))

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users
    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        google_client_id="test-google-client-id",
        google_client_secret="test-google-client-secret",
        google_redirect_uri=TEST_GOOGLE_REDIRECT_URI,
    )
    _swap_settings(test_settings)

    try:
        api_mod._USER_LOCKS.clear()
        deps_mod._USER_LOCKS_MUTEX = None
        client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
        yield SimpleNamespace(client=client, data_dir=data_dir)
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


def test_login_page_returns_200_with_google(web_auth_env):
    resp = web_auth_env.client.get("/login")
    assert resp.status_code == 200
    assert "Google" in resp.text


def test_login_page_returns_200_with_apple(web_auth_env):
    resp = web_auth_env.client.get("/login")
    assert resp.status_code == 200
    assert "Apple" in resp.text


def test_google_login_redirects_to_google(web_auth_env):
    resp = web_auth_env.client.get("/auth/web/google/login", follow_redirects=False)
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert "accounts.google.com" in location
    assert "client_id=test-google-client-id" in location
    assert "redirect_uri=" in location
    assert "response_type=code" in location
    assert "scope=" in location


def test_web_auth_router_is_registered(web_auth_env):
    """The web_auth router should be included in the app."""
    routes = [r.path for r in app.routes]
    assert "/login" in routes
    assert "/auth/web/google/login" in routes
    assert "/auth/web/google/callback" in routes
    assert "/auth/web/apple/callback" in routes


# ── Google callback token-exchange failure branches ─────────────────────────
# Regression net for the two non-network failure paths in google_callback that
# the sibling suites do not cover (state CSRF lives in test_web_auth_state.py,
# network 502 + retry there too; replay in test_web_auth_security.py).


def _bootstrap_google_state(client: TestClient) -> str:
    resp = client.get("/auth/web/google/login", follow_redirects=False)
    assert resp.status_code == 307
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]


def test_google_callback_token_exchange_non_200_returns_401(web_auth_env):
    """Upstream token endpoint replying non-200 (e.g. invalid_grant) → 401,
    not a leaked 500/200."""
    client = web_auth_env.client
    state = _bootstrap_google_state(client)

    fake_resp = httpx.Response(
        400,
        json={"error": "invalid_grant"},
        request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
    )

    async def fake_post(self, url, data=None, **kwargs):
        return fake_resp

    with patch("httpx.AsyncClient.post", new=fake_post):
        resp = client.get(
            f"/auth/web/google/callback?code=fake-code&state={state}",
            follow_redirects=False,
        )
    assert resp.status_code == 401, resp.text


def test_google_callback_missing_id_token_returns_401(web_auth_env):
    """A 200 token response that omits ``id_token`` → 401 (no OIDC identity to
    verify), guarding against a None slipping into verify_google_token."""
    client = web_auth_env.client
    state = _bootstrap_google_state(client)

    fake_resp = httpx.Response(
        200,
        json={"access_token": "opaque-no-id-token"},
        request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
    )

    async def fake_post(self, url, data=None, **kwargs):
        return fake_resp

    with patch("httpx.AsyncClient.post", new=fake_post):
        resp = client.get(
            f"/auth/web/google/callback?code=fake-code&state={state}",
            follow_redirects=False,
        )
    assert resp.status_code == 401, resp.text


# ── Provider error redaction (B1) ────────────────────────────────────────────
# OAuth callbacks must NOT echo the upstream provider's ``error`` string back to
# the client (it can carry provider-internal hints). The client receives a
# generic 400; the raw provider error is logged server-side at WARNING.

_PROVIDER_ERROR_SENTINEL = "access_denied_internal_provider_hint_xyz"


def test_google_callback_provider_error_is_redacted(web_auth_env, caplog):
    """Google callback ``?error=<x>`` → 400 with generic body (no ``<x>``) and a
    server-side WARNING carrying the raw provider error."""
    client = web_auth_env.client
    with caplog.at_level("WARNING", logger="kg.routers.web_auth"):
        resp = client.get(
            f"/auth/web/google/callback?error={_PROVIDER_ERROR_SENTINEL}",
            follow_redirects=False,
        )
    assert resp.status_code == 400, resp.text
    assert _PROVIDER_ERROR_SENTINEL not in resp.text
    assert any(
        _PROVIDER_ERROR_SENTINEL in record.getMessage() for record in caplog.records
    ), "raw provider error must be logged server-side"


def test_apple_callback_provider_error_is_redacted(web_auth_env, caplog):
    """Apple callback ``error=<x>`` (form POST) → 400 with generic body (no
    ``<x>``) and a server-side WARNING carrying the raw provider error."""
    client = web_auth_env.client
    with caplog.at_level("WARNING", logger="kg.routers.web_auth"):
        resp = client.post(
            "/auth/web/apple/callback",
            data={
                "id_token": "unused-when-error-present",
                "error": _PROVIDER_ERROR_SENTINEL,
            },
            follow_redirects=False,
        )
    assert resp.status_code == 400, resp.text
    assert _PROVIDER_ERROR_SENTINEL not in resp.text
    assert any(
        _PROVIDER_ERROR_SENTINEL in record.getMessage() for record in caplog.records
    ), "raw provider error must be logged server-side"


# ── Cookie security attributes (full assertion) ──────────────────────────────


def test_google_login_state_cookie_security_attributes(web_auth_env):
    """The oauth_state cookie must be HttpOnly + Secure + scoped to
    Path=/auth/web/ so it never leaks to other paths or to JS."""
    resp = web_auth_env.client.get("/auth/web/google/login", follow_redirects=False)
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "oauth_state=" in set_cookie
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "path=/auth/web/" in set_cookie
    assert "samesite=lax" in set_cookie


def test_apple_login_state_cookie_security_attributes(web_auth_env):
    """Apple's state cookie is SameSite=None (cross-site form_post) but must
    still be HttpOnly + Secure + Path=/auth/web/."""
    resp = web_auth_env.client.get("/auth/web/apple/login", follow_redirects=False)
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "oauth_state=" in set_cookie
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "path=/auth/web/" in set_cookie
    assert "samesite=none" in set_cookie
