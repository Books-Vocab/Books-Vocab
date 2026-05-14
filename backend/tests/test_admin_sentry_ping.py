"""Tests for /api/admin/sentry/ping — admin-only Sentry smoke-ping endpoint.

Covers the three contract surfaces:
  1. Auth boundary — unauthenticated calls return 403 (never 200, never 500).
  2. Sentry active — endpoint dispatches via sentry_sdk and returns sent=True
     with an event_id, without raising.
  3. Sentry inactive — endpoint returns sent=False, never raises, even though
     no DSN is configured.

We avoid standing up a real DSN by monkeypatching ``kg.sentry_init`` module
state (mirrors the pattern in ``test_sentry_init.test_bind_user_only_sends_id``).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kg.api import app
from kg.settings import KGSettings

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"
ADMIN_TOKEN = "test-admin-token-sentry-ping"


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
def admin_app(tmp_path, monkeypatch):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({"_meta": {}}))

    monkeypatch.setenv("KG_DATA_DIR", str(data_dir))

    original_settings = app.state.kg_settings
    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        admin_token=ADMIN_TOKEN,
    )
    _swap_settings(test_settings)
    try:
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(client=client, data_dir=data_dir)
    finally:
        app.state.kg_settings = original_settings


# ── Auth boundary ─────────────────────────────────────────────────────────────


def test_sentry_ping_requires_admin_session(admin_app):
    """Anonymous POST → 403 (handled by ``get_admin_user`` dependency)."""
    resp = admin_app.client.post("/api/admin/sentry/ping")
    assert resp.status_code == 403


def test_sentry_ping_rejects_wrong_token(admin_app):
    resp = admin_app.client.post(
        "/api/admin/sentry/ping",
        headers={"Authorization": "Bearer not-the-admin-token"},
    )
    assert resp.status_code == 403


# ── Sentry inactive (no DSN) ──────────────────────────────────────────────────


def test_sentry_ping_inactive_returns_sent_false(admin_app, monkeypatch):
    """When ``init_sentry()`` returned False (no DSN), the endpoint must:
       • respond 200 with ``sent=False, is_active=False``
       • NOT raise — admin should always get a clean status payload.
    """
    import kg.sentry_init as si

    # Force the inactive branch regardless of host env.
    monkeypatch.setattr(si, "_initialized", False, raising=False)
    monkeypatch.setattr(si, "_sentry_module", None, raising=False)

    resp = admin_app.client.post(
        "/api/admin/sentry/ping",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"sent": False, "is_active": False, "event_id": None}


# ── Sentry active (DSN wired) ─────────────────────────────────────────────────


def test_sentry_ping_active_dispatches_message_and_exception(admin_app, monkeypatch):
    """When Sentry is initialized:
       • capture_message + capture_exception are called exactly once each
       • response contains the latest event_id
       • is_active=True, sent=True
       • endpoint never raises
    """
    captured_messages: list[tuple[str, str]] = []
    captured_exceptions: list[BaseException] = []

    class FakeSentry:
        @staticmethod
        def capture_message(msg, level="info"):
            captured_messages.append((msg, level))
            return "evt-msg-001"

        @staticmethod
        def capture_exception(exc):
            captured_exceptions.append(exc)
            return "evt-exc-002"

    import kg.sentry_init as si

    monkeypatch.setattr(si, "_initialized", True, raising=False)
    monkeypatch.setattr(si, "_sentry_module", FakeSentry, raising=False)
    # The endpoint imports ``sentry_sdk`` directly so we shim the import too.
    import sys

    monkeypatch.setitem(sys.modules, "sentry_sdk", FakeSentry)

    resp = admin_app.client.post(
        "/api/admin/sentry/ping",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sent"] is True
    assert body["is_active"] is True
    assert body["event_id"] == "evt-exc-002"  # exception id wins (last write)

    # Verify Sentry was actually called with the documented signature.
    assert captured_messages == [("admin smoke ping", "info")]
    assert len(captured_exceptions) == 1
    assert isinstance(captured_exceptions[0], RuntimeError)
    assert "admin smoke ping" in str(captured_exceptions[0])


def test_sentry_ping_active_swallows_transport_error(admin_app, monkeypatch):
    """If Sentry transport explodes mid-ping, the endpoint must NOT 500 —
    crash reporting infrastructure must never crash the request flow."""

    class BoomSentry:
        @staticmethod
        def capture_message(msg, level="info"):  # noqa: ARG004
            raise RuntimeError("simulated sentry transport failure")

        @staticmethod
        def capture_exception(exc):  # noqa: ARG004 — never reached
            return None

    import kg.sentry_init as si

    monkeypatch.setattr(si, "_initialized", True, raising=False)
    monkeypatch.setattr(si, "_sentry_module", BoomSentry, raising=False)
    import sys

    monkeypatch.setitem(sys.modules, "sentry_sdk", BoomSentry)

    resp = admin_app.client.post(
        "/api/admin/sentry/ping",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"sent": False, "is_active": True, "event_id": None}
