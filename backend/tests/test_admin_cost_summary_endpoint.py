"""HTTP-level smoke tests for /api/admin/user-cost-summary."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

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
def admin_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({"_meta": {}, "u1": {"config": {}}}))

    monkeypatch.setenv("KG_DATA_DIR", str(data_dir))
    import kg.token_tracker as tt

    monkeypatch.setattr(tt, "DATA_DIR", data_dir, raising=True)
    monkeypatch.setattr(tt, "DB_PATH", data_dir / "token_usage.db", raising=True)
    tt._conn = None

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
        if tt._conn is not None:
            tt._conn.close()
            tt._conn = None


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _seed(user_id: str, call_type: str, *, t_in: int, t_out: int, when: datetime | None = None) -> None:
    import kg.token_tracker as tt

    when = when or datetime.now(UTC)
    with tt._lock:
        conn = tt._get_conn()
        conn.execute(
            "INSERT INTO token_usage (user_id, call_type, input_tokens, output_tokens, created_at) VALUES (?,?,?,?,?)",
            (user_id, call_type, t_in, t_out, when.isoformat()),
        )
        conn.commit()


def test_cost_summary_empty(admin_client):
    """Empty token_usage table returns zeroed shape, not 500."""
    r = admin_client.client.get(
        "/api/admin/user-cost-summary?user_id=u1&range=month",
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u1"
    assert body["range"] == "month"
    assert body["total_calls"] == 0
    assert body["total_cost_usd"] == 0.0
    assert body["by_service"] == {}
    assert body["by_model"] == {}
    assert body["pricing_assumptions"]["model_inferred_from_call_type"] is True


def test_cost_summary_aggregates_by_service(admin_client):
    """Endpoint returns aggregated by_service / by_model / totals."""
    _seed("u1", "judge", t_in=1000, t_out=200)
    _seed("u1", "translate_quick", t_in=500, t_out=100)
    _seed("u1", "embed", t_in=2000, t_out=0)

    r = admin_client.client.get(
        "/api/admin/user-cost-summary?user_id=u1&range=month",
        headers=_auth(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_calls"] == 3
    assert body["total_input_tokens"] == 3500
    assert body["total_output_tokens"] == 300
    assert set(body["by_service"].keys()) == {"judge", "translate", "pipeline"}
    assert set(body["by_model"].keys()) == {
        "gemini-2.5-flash-lite", "gemini-embedding-2-preview",
    }


def test_cost_summary_requires_admin(admin_client):
    r = admin_client.client.get("/api/admin/user-cost-summary?user_id=u1")
    assert r.status_code in (401, 403)


def test_cost_summary_invalid_range_returns_400(admin_client):
    r = admin_client.client.get(
        "/api/admin/user-cost-summary?user_id=u1&range=forever",
        headers=_auth(),
    )
    assert r.status_code == 400
