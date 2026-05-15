"""Tests for admin password login flow (/admin/login)."""
from __future__ import annotations

import json
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kg.admin_handlers import _sign_cookie
from kg.api import app
from kg.settings import KGSettings

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"
ADMIN_TOKEN = "test-admin-token-value"
ADMIN_PASSWORD = "my-secret-admin-password"


def _swap_settings(new_settings):
    from kg.billing import default_subscription_payload
    from kg.user_store import CachedUserStore, normalize_users_payload

    app.state.kg_settings = new_settings

    def _normalize(users):
        from kg.secret_store import encrypt_value
        jwt_secret = app.state.kg_settings.jwt_secret
        encrypt_fn = (lambda v: encrypt_value(v, jwt_secret)) if jwt_secret else None
        return normalize_users_payload(users, default_subscription_payload, encrypt_fn=encrypt_fn)

    user_store = CachedUserStore(new_settings.users_file, _normalize)
    app.state.user_store = user_store
    app.state.load_users = lambda: user_store.load()
    app.state.save_users = lambda users: user_store.save(users)


@pytest.fixture()
def admin_app(tmp_path):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({"_meta": {}}))

    original_settings = app.state.kg_settings

    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        admin_token=ADMIN_TOKEN,
        admin_password=ADMIN_PASSWORD,
    )
    _swap_settings(test_settings)

    try:
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(client=client, data_dir=data_dir)
    finally:
        app.state.kg_settings = original_settings


@pytest.fixture()
def admin_app_no_password(tmp_path):
    """App with admin_password empty (password login disabled)."""
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({"_meta": {}}))

    original_settings = app.state.kg_settings

    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        admin_token=ADMIN_TOKEN,
        admin_password="",
    )
    _swap_settings(test_settings)

    try:
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(client=client, data_dir=data_dir)
    finally:
        app.state.kg_settings = original_settings


# ── 1. GET /admin/login returns 200 + HTML ─────────────────────────────────

def test_login_page_returns_html(admin_app):
    resp = admin_app.client.get("/admin/login")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "<form" in resp.text.lower()


# ── 2. POST /admin/login correct password → 302 + Set-Cookie ──────────────

def test_login_correct_password_redirects(admin_app):
    resp = admin_app.client.post(
        "/admin/login",
        data={"password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/admin"
    cookie_header = resp.headers.get("set-cookie", "")
    # Cookie value is now an expiry-bound token (expires_at.nonce.sig);
    # extract and verify it round-trips through _verify_cookie.
    import re

    from kg.admin_handlers import _verify_cookie
    m = re.search(r"admin_session=([^;]+)", cookie_header)
    assert m is not None
    assert _verify_cookie(m.group(1), ADMIN_TOKEN)


# ── 3. POST /admin/login wrong password → login page + error ──────────────

def test_login_wrong_password_shows_error(admin_app):
    resp = admin_app.client.post(
        "/admin/login",
        data={"password": "wrong-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    # Should contain an error message
    assert "密碼錯誤" in resp.text or "error" in resp.text.lower()


# ── 4. POST /admin/login with empty ADMIN_PASSWORD → 403 ─────────────────

def test_login_post_disabled_returns_403(admin_app_no_password):
    resp = admin_app_no_password.client.post(
        "/admin/login",
        data={"password": "anything"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


# ── 5. GET /admin unauthenticated → 302 redirect to /admin/login ─────────

def test_admin_ui_unauthenticated_redirects_to_login(admin_app):
    resp = admin_app.client.get("/admin", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["location"]


# ── 6. GET /api/admin/stats unauthenticated → 403 JSON (not 302) ─────────

def test_api_admin_unauthenticated_returns_403(admin_app):
    resp = admin_app.client.get("/api/admin/stats")
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/json")


# ── 7. GET /admin with valid token → 200 (existing auth works) ───────────

def test_admin_ui_with_token_returns_200(admin_app):
    resp = admin_app.client.get(
        "/admin",
        params={"token": ADMIN_TOKEN},
        follow_redirects=False,
    )
    assert resp.status_code == 200


# ── 8. GET /admin with valid cookie → 200 (cookie auth works) ────────────

def test_admin_ui_with_cookie_returns_200(admin_app):
    signed = _sign_cookie(ADMIN_TOKEN)
    admin_app.client.cookies.set("admin_session", signed)
    resp = admin_app.client.get("/admin", follow_redirects=False)
    assert resp.status_code == 200
