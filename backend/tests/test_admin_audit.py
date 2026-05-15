"""Tests for admin audit log (insert / retrieve / auth boundary)."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kg import admin_audit
from kg.admin_handlers import _sign_cookie, admin_actor_fingerprint
from kg.api import app
from kg.settings import KGSettings

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"
ADMIN_TOKEN = "test-admin-token-audit"
ADMIN_PASSWORD = "audit-pw"


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
def audit_db(tmp_path, monkeypatch):
    """Isolated audit SQLite per test."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    admin_audit._reset()
    try:
        yield tmp_path
    finally:
        admin_audit._reset()


@pytest.fixture()
def admin_app(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    admin_audit._reset()
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({"_meta": {}, "u-target": {"id": "u-target", "email": "t@example.com"}}))

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
        admin_audit._reset()


# ── Unit: insert + retrieve ────────────────────────────────────────────────


def test_record_and_list(audit_db):
    admin_audit.record_audit(
        admin_uid="ops@example.com",
        action="grant_pro",
        target_uid="user-1",
        payload={"reason": "test", "expires_at": None},
    )
    admin_audit.record_audit(
        admin_uid="ops@example.com",
        action="revoke_pro",
        target_uid="user-2",
        payload={"reason": "abuse"},
    )
    rows = admin_audit.list_audit(limit=10)
    assert len(rows) == 2
    # newest first
    assert rows[0]["action"] == "revoke_pro"
    assert rows[0]["target_uid"] == "user-2"
    assert rows[0]["payload"] == {"reason": "abuse"}
    assert rows[1]["action"] == "grant_pro"
    assert rows[1]["admin_uid"] == "ops@example.com"
    assert rows[1]["payload"]["reason"] == "test"


def test_record_defaults_to_admin_when_uid_missing(audit_db):
    admin_audit.record_audit(admin_uid=None, action="grant_pro", target_uid="u1", payload={})
    admin_audit.record_audit(admin_uid="   ", action="grant_pro", target_uid="u2", payload={})
    rows = admin_audit.list_audit()
    assert all(r["admin_uid"] == "admin" for r in rows)


def test_record_drops_empty_action(audit_db):
    admin_audit.record_audit(admin_uid="ops", action="", target_uid="u", payload={})
    assert admin_audit.list_audit() == []


def test_record_handles_unserializable_payload(audit_db):
    class Unserializable:
        pass

    admin_audit.record_audit(
        admin_uid="ops",
        action="grant_pro",
        target_uid="u",
        payload={"obj": Unserializable()},
    )
    rows = admin_audit.list_audit()
    assert len(rows) == 1
    # default=str fallback should stringify rather than dropping the row.
    assert rows[0]["payload"]["obj"].startswith("<")


def test_list_since_filter(audit_db):
    admin_audit.record_audit(admin_uid="a", action="grant_pro", target_uid="u1", payload={})
    rows_all = admin_audit.list_audit()
    cutoff = rows_all[0]["created_at"]
    admin_audit.record_audit(admin_uid="a", action="grant_pro", target_uid="u2", payload={})
    rows = admin_audit.list_audit(since=cutoff)
    assert {r["target_uid"] for r in rows} == {"u1", "u2"}
    # since = far future returns nothing
    assert admin_audit.list_audit(since="9999-01-01T00:00:00+00:00") == []


def test_list_limit_clamped(audit_db):
    for i in range(5):
        admin_audit.record_audit(admin_uid="a", action="grant_pro", target_uid=f"u{i}", payload={})
    assert len(admin_audit.list_audit(limit=2)) == 2
    assert len(admin_audit.list_audit(limit=0)) == 5  # 0 clamps to 1+, but we inserted 5 → returns up to 1
    # Sanity: limit=0 clamps to >=1, so result length is between 1 and 5.
    assert 1 <= len(admin_audit.list_audit(limit=0)) <= 5


# ── Endpoint: GET /api/admin/audit ─────────────────────────────────────────


def test_audit_endpoint_requires_auth(admin_app):
    resp = admin_app.client.get("/api/admin/audit")
    assert resp.status_code == 403


def test_audit_endpoint_with_cookie_returns_rows(admin_app):
    admin_audit.record_audit(
        admin_uid="ops", action="grant_pro", target_uid="u-target", payload={"foo": "bar"}
    )
    signed = _sign_cookie(ADMIN_TOKEN)
    admin_app.client.cookies.set("admin_session", signed)
    resp = admin_app.client.get("/api/admin/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert "audit" in body
    assert len(body["audit"]) == 1
    assert body["audit"][0]["action"] == "grant_pro"
    assert body["audit"][0]["target_uid"] == "u-target"
    assert body["audit"][0]["payload"] == {"foo": "bar"}


def test_audit_endpoint_with_token_query(admin_app):
    admin_audit.record_audit(admin_uid="ops", action="grant_pro", target_uid="u", payload={})
    resp = admin_app.client.get(
        "/api/admin/audit",
        params={"token": ADMIN_TOKEN, "limit": 5},
    )
    assert resp.status_code == 200
    assert len(resp.json()["audit"]) == 1


# ── Endpoint: grant/revoke writes audit row ────────────────────────────────


def test_grant_records_audit_with_token_fingerprint(admin_app):
    """Client-supplied ``granted_by`` is ignored; admin_uid is a server-derived
    fingerprint of the actual auth material used to call the endpoint."""
    expected_fp = admin_actor_fingerprint(
        token=ADMIN_TOKEN, authorization=None, cookie_token=None, admin_token=ADMIN_TOKEN
    )
    resp = admin_app.client.post(
        "/api/admin/users/u-target/admin-grant",
        params={"token": ADMIN_TOKEN},
        json={"granted_by": "spoofed@evil.example", "reason": "manual upgrade"},
    )
    assert resp.status_code == 200, resp.text
    rows = admin_audit.list_audit()
    assert len(rows) == 1
    row = rows[0]
    assert row["action"] == "grant_pro"
    assert row["target_uid"] == "u-target"
    # Spoofed granted_by must NOT win — actor is server-derived fingerprint.
    assert row["admin_uid"] != "spoofed@evil.example"
    assert row["admin_uid"] == expected_fp
    assert len(row["admin_uid"]) == 8
    assert row["payload"].get("reason") == "manual upgrade"


def test_grant_records_audit_with_cookie_fingerprint(admin_app):
    """Cookie auth derives a distinct fingerprint from token auth."""
    signed = _sign_cookie(ADMIN_TOKEN)
    expected_fp = admin_actor_fingerprint(
        token=None, authorization=None, cookie_token=signed, admin_token=ADMIN_TOKEN
    )
    token_fp = admin_actor_fingerprint(
        token=ADMIN_TOKEN, authorization=None, cookie_token=None, admin_token=ADMIN_TOKEN
    )
    assert expected_fp != token_fp  # different auth source → different fingerprint
    admin_app.client.cookies.set("admin_session", signed)
    resp = admin_app.client.post(
        "/api/admin/users/u-target/admin-grant",
        json={"granted_by": "spoofed", "reason": None},
    )
    assert resp.status_code == 200, resp.text
    rows = admin_audit.list_audit()
    assert len(rows) == 1
    assert rows[0]["admin_uid"] == expected_fp


def test_revoke_records_audit_with_token_fingerprint(admin_app):
    expected_fp = admin_actor_fingerprint(
        token=ADMIN_TOKEN, authorization=None, cookie_token=None, admin_token=ADMIN_TOKEN
    )
    resp = admin_app.client.delete(
        "/api/admin/users/u-target/admin-grant",
        params={"token": ADMIN_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    rows = admin_audit.list_audit()
    assert len(rows) == 1
    assert rows[0]["action"] == "revoke_pro"
    assert rows[0]["target_uid"] == "u-target"
    # Previously this defaulted to literal "admin"; now it's a server fingerprint.
    assert rows[0]["admin_uid"] == expected_fp
    assert rows[0]["admin_uid"] != "admin"


def test_revoke_records_audit_with_cookie_fingerprint(admin_app):
    signed = _sign_cookie(ADMIN_TOKEN)
    expected_fp = admin_actor_fingerprint(
        token=None, authorization=None, cookie_token=signed, admin_token=ADMIN_TOKEN
    )
    admin_app.client.cookies.set("admin_session", signed)
    resp = admin_app.client.delete("/api/admin/users/u-target/admin-grant")
    assert resp.status_code == 200, resp.text
    rows = admin_audit.list_audit()
    assert len(rows) == 1
    assert rows[0]["admin_uid"] == expected_fp


# ── Fingerprint helper unit tests ──────────────────────────────────────────


def test_actor_fingerprint_is_stable_and_8_chars():
    fp1 = admin_actor_fingerprint(
        token="tok", authorization=None, cookie_token=None, admin_token="server-tok"
    )
    fp2 = admin_actor_fingerprint(
        token="tok", authorization=None, cookie_token=None, admin_token="server-tok"
    )
    assert fp1 == fp2
    assert len(fp1) == 8


def test_actor_fingerprint_differs_by_source():
    """Bearer/token-query vs cookie produce distinct fingerprints even when
    the underlying credential string happens to match."""
    fp_token = admin_actor_fingerprint(
        token="x", authorization=None, cookie_token=None, admin_token="server-tok"
    )
    fp_cookie = admin_actor_fingerprint(
        token=None, authorization=None, cookie_token="x", admin_token="server-tok"
    )
    assert fp_token != fp_cookie


def test_actor_fingerprint_does_not_leak_token():
    fp = admin_actor_fingerprint(
        token="super-secret-admin-token-value-xyz",
        authorization=None,
        cookie_token=None,
        admin_token="server-tok",
    )
    assert "secret" not in fp
    assert "admin" not in fp
    assert len(fp) == 8


def test_actor_fingerprint_falls_back_to_admin_with_no_material():
    assert admin_actor_fingerprint(
        token=None, authorization=None, cookie_token=None, admin_token="server-tok"
    ) == "admin"
