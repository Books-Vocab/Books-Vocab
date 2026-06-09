"""Tests for GET /api/admin/users/search?q=&limit=."""
from __future__ import annotations

import pytest

from conftest import ADMIN_TOKEN

_USERS_SEED = {
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
}


@pytest.fixture()
def admin_app(admin_app_factory):
    return admin_app_factory(
        users_seed=_USERS_SEED,
        admin_token=ADMIN_TOKEN,
        admin_password="",
        inject_cookie=True,
    )


# ── 1. unauthenticated → 403 ──────────────────────────────────────────────
def test_search_requires_admin(admin_app_factory):
    harness = admin_app_factory(admin_token=ADMIN_TOKEN, admin_password="")
    resp = harness.client.get("/api/admin/users/search?q=alice")
    assert resp.status_code == 403


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
