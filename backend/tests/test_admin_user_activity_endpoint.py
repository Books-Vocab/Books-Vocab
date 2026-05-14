"""HTTP-level smoke tests for admin user-activity + translate-history endpoints."""
from __future__ import annotations

import json
from dataclasses import replace
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
    import kg.judge_log as jl
    import kg.pipeline_log as pl
    import kg.translate_log as tl

    monkeypatch.setattr(pl, "DATA_DIR", data_dir, raising=True)
    monkeypatch.setattr(pl, "DB_PATH", data_dir / "pipeline_runs.db", raising=True)
    monkeypatch.setattr(jl, "DATA_DIR", data_dir, raising=True)
    monkeypatch.setattr(jl, "DB_PATH", data_dir / "judge_log.db", raising=True)
    tl._reset()
    pl._reset()
    jl._reset()

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
        tl._reset()
        pl._reset()
        jl._reset()


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _seed_translate(user_id: str, *, word: str, op: str = "translate_quick") -> None:
    import kg.translate_log as tl

    tl.record(
        user_id=user_id, operation=op, word=word, context="",
        context_hash="h_" + word, source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"x"}', latency_ms=8,
    )


def test_translate_history_no_filter(admin_client):
    _seed_translate("u1", word="apple")
    _seed_translate("u1", word="banana")

    r = admin_client.client.get(
        "/api/admin/translate-history?user_id=u1",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert {row["word"] for row in body["history"]} == {"apple", "banana"}


def test_translate_history_q_filter(admin_client):
    _seed_translate("u1", word="apple")
    _seed_translate("u1", word="pineapple")
    _seed_translate("u1", word="banana")

    r = admin_client.client.get(
        "/api/admin/translate-history?user_id=u1&q=apple",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    words = {row["word"] for row in r.json()["history"]}
    assert words == {"apple", "pineapple"}


def test_translate_history_op_filter(admin_client):
    _seed_translate("u1", word="apple", op="translate_quick")
    _seed_translate("u1", word="banana", op="translate_explain")

    r = admin_client.client.get(
        "/api/admin/translate-history?user_id=u1&op=translate_explain",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["op"] == "translate_explain"
    assert [row["word"] for row in body["history"]] == ["banana"]


def test_translate_history_requires_admin(admin_client):
    r = admin_client.client.get("/api/admin/translate-history?user_id=u1")
    assert r.status_code in (401, 403)


def test_user_activity_empty(admin_client):
    r = admin_client.client.get(
        "/api/admin/user-activity?user_id=u1&hours=24",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u1"
    assert body["hours"] == 24
    assert body["events"] == []
    assert body["counts"] == {"translate": 0, "pipeline": 0, "judge": 0}


def test_user_activity_returns_translate_event(admin_client):
    _seed_translate("u1", word="hello")
    r = admin_client.client.get(
        "/api/admin/user-activity?user_id=u1&hours=24",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["translate"] == 1
    assert body["events"][0]["type"] == "translate"
    assert body["events"][0]["word"] == "hello"


def test_user_activity_requires_admin(admin_client):
    r = admin_client.client.get("/api/admin/user-activity?user_id=u1")
    assert r.status_code in (401, 403)


def test_user_activity_hours_clamped(admin_client):
    r = admin_client.client.get(
        "/api/admin/user-activity?user_id=u1&hours=99999",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["hours"] == 168


def test_user_activity_isolates_user(admin_client):
    _seed_translate("u1", word="apple")
    _seed_translate("other", word="banana")

    r = admin_client.client.get(
        "/api/admin/user-activity?user_id=u1&hours=24",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == 1
    assert events[0]["word"] == "apple"
