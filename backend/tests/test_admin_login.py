"""Tests for admin password login flow (/admin/login)."""
from __future__ import annotations

import pytest

from conftest import ADMIN_TOKEN
from kg.admin_handlers import _sign_cookie

ADMIN_PASSWORD = "my-secret-admin-password"


@pytest.fixture()
def admin_app(admin_app_factory):
    return admin_app_factory(admin_token=ADMIN_TOKEN, admin_password=ADMIN_PASSWORD)


@pytest.fixture()
def admin_app_no_password(admin_app_factory):
    """App with admin_password empty (password login disabled)."""
    return admin_app_factory(admin_token=ADMIN_TOKEN, admin_password="")


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
