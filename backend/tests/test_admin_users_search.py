"""Tests for GET /api/admin/users/search?q=&limit=."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kg.admin_handlers import _sign_cookie
from kg.api import app
from kg.settings import KGSettings

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"
ADMIN_TOKEN = "test-admin-token-value"


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
    users_file.write_text(json.dumps({
        "_meta": {},
        "uid-alice-001": {
            "email": "alice@example.com",
            "display_name": "Alice Wonderland",
            "provider": "apple",
        },
        "uid-bob-002": {
            "email": "bob@workmail.org",
            "display_name": "Bobby Tables",
            "provider": "google",
        },
        "uid-carol-003": {
            "email": "carol@example.com",
            "displayName": "Carol Singer",
            "provider": "apple",
        },
        "uid-dave-004": {
            "email": None,
            "display_name": None,
            "provider": "apple",
        },
    }))

    original_settings = app.state.kg_settings
    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        admin_token=ADMIN_TOKEN,
        admin_password="",
    )
    _swap_settings(test_settings)

    try:
        cookie = _sign_cookie(ADMIN_TOKEN)
        client = TestClient(app, raise_server_exceptions=False, cookies={"admin_session": cookie})
        yield SimpleNamespace(client=client, data_dir=data_dir)
    finally:
        app.state.kg_settings = original_settings


# ── 1. unauthenticated → 403 ──────────────────────────────────────────────
def test_search_requires_admin(tmp_path):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({"_meta": {}}))

    original_settings = app.state.kg_settings
    _swap_settings(KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        admin_token=ADMIN_TOKEN,
        admin_password="",
    ))
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/admin/users/search?q=alice")
        assert resp.status_code == 403
    finally:
        app.state.kg_settings = original_settings


# ── 2. empty q returns all (capped by limit) ──────────────────────────────
def test_search_empty_returns_all(admin_app):
    resp = admin_app.client.get("/api/admin/users/search?q=")
    assert resp.status_code == 200
    body = resp.json()
    assert "users" in body and "total" in body
    assert body["total"] == 4
    assert len(body["users"]) == 4
    # rows must expose minimal identifying fields, no token/quota bloat
    sample = body["users"][0]
    assert "user_id" in sample
    assert "email" in sample
    assert "display_name" in sample


# ── 3. uid prefix match ───────────────────────────────────────────────────
def test_search_by_uid_prefix(admin_app):
    resp = admin_app.client.get("/api/admin/users/search?q=uid-ali")
    assert resp.status_code == 200
    uids = [u["user_id"] for u in resp.json()["users"]]
    assert uids == ["uid-alice-001"]


# ── 4. email substring match (case-insensitive) ───────────────────────────
def test_search_by_email_substring(admin_app):
    resp = admin_app.client.get("/api/admin/users/search?q=WORKMAIL")
    assert resp.status_code == 200
    uids = [u["user_id"] for u in resp.json()["users"]]
    assert uids == ["uid-bob-002"]


# ── 5. display name substring match (supports both display_name & displayName) ─
def test_search_by_display_name_substring(admin_app):
    resp = admin_app.client.get("/api/admin/users/search?q=singer")
    assert resp.status_code == 200
    uids = [u["user_id"] for u in resp.json()["users"]]
    assert uids == ["uid-carol-003"]

    resp2 = admin_app.client.get("/api/admin/users/search?q=Wonder")
    assert resp2.status_code == 200
    uids2 = [u["user_id"] for u in resp2.json()["users"]]
    assert uids2 == ["uid-alice-001"]


# ── 6. limit caps results ─────────────────────────────────────────────────
def test_search_respects_limit(admin_app):
    resp = admin_app.client.get("/api/admin/users/search?q=&limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 4
    assert len(body["users"]) == 2


# ── 7. _meta and underscore-prefixed uids excluded ────────────────────────
def test_search_excludes_meta(admin_app):
    resp = admin_app.client.get("/api/admin/users/search?q=_meta")
    assert resp.status_code == 200
    assert resp.json()["users"] == []


# ── 8. no match → empty users, total still real ──────────────────────────
def test_search_no_match(admin_app):
    resp = admin_app.client.get("/api/admin/users/search?q=zzznotfound")
    assert resp.status_code == 200
    body = resp.json()
    assert body["users"] == []
    assert body["total"] == 4
