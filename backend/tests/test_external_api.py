from __future__ import annotations

import collections
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import kg.routers.external_api as external_router
from conftest import TEST_JWT_SECRET, _swap_settings, make_jwt
from kg.api import app
from kg.external_api_rate_limit import ExternalRateLimiter, enrich_limiter, read_limiter, write_limiter
from kg.settings import KGSettings


@pytest.fixture()
def external_api(tmp_path):
    user_id = "u_" + uuid.uuid4().hex[:8]
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps(
            {
                user_id: {
                    "config": {},
                    "subscription": {
                        "is_active": True,
                        "status": "active",
                        "will_renew": True,
                        "expires_at": None,
                    },
                }
            }
        )
    )
    (tmp_path / "users").mkdir()

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users
    _swap_settings(
        KGSettings(
            data_dir=tmp_path,
            jwt_secret=TEST_JWT_SECRET,
            app_store_allow_unsigned_sync=True,
            app_store_allow_unsigned_notifications=True,
        )
    )
    external_router._OPERATIONS.clear()
    for limiter in (read_limiter, write_limiter, enrich_limiter):
        limiter.reset()

    client = TestClient(app, raise_server_exceptions=False)
    jwt_headers = {"Authorization": f"Bearer {make_jwt(user_id)}"}
    try:
        yield SimpleNamespace(
            client=client,
            user_id=user_id,
            jwt_headers=jwt_headers,
            users_file=users_file,
            data_dir=tmp_path,
        )
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


def _create_key(ctx) -> str:
    response = ctx.client.post(
        "/api/v1/api-keys",
        json={"label": "reader automation"},
        headers=ctx.jwt_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["apiKey"].startswith("kg_")
    return body["apiKey"]


def test_external_api_requires_pro_for_key_creation(external_api):
    users = json.loads(external_api.users_file.read_text())
    free_id = "free_" + uuid.uuid4().hex[:8]
    users[free_id] = {"config": {}}
    external_api.users_file.write_text(json.dumps(users))
    app.state.user_store.invalidate()

    response = external_api.client.post(
        "/api/v1/api-keys",
        json={"label": "free"},
        headers={"Authorization": f"Bearer {make_jwt(free_id)}"},
    )

    assert response.status_code == 403
    assert "Pro" in response.json()["detail"]


def test_external_api_key_is_listed_without_secret_and_can_be_revoked(external_api):
    api_key = _create_key(external_api)
    listed = external_api.client.get("/api/v1/api-keys", headers=external_api.jwt_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "apiKey" not in listed.json()[0]
    key_id = listed.json()[0]["keyId"]

    revoked = external_api.client.delete(
        f"/api/v1/api-keys/{key_id}",
        headers=external_api.jwt_headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["revokedAt"]
    rejected = external_api.client.get(
        "/api/v1/cards",
        headers={"X-KG-API-Key": api_key},
    )
    assert rejected.status_code == 401


def test_external_card_ingest_is_idempotent_and_supports_card_operations(external_api):
    api_key = _create_key(external_api)
    headers = {"X-KG-API-Key": api_key}
    payload = {
        "content": "  Invoked! ",
        "context": "The lawyer invoked the law.",
        "clientId": "local-queue-1",
    }

    first = external_api.client.post("/api/v1/cards", json=payload, headers=headers)
    assert first.status_code == 201, first.text
    first_body = first.json()
    assert first_body["created"] is True
    assert first_body["card"]["content"] == "invoked"
    assert first_body["card"]["examples"] == ["The lawyer invoked the law."]
    card_id = first_body["card"]["id"]

    retry = external_api.client.post("/api/v1/cards", json=payload, headers=headers)
    assert retry.status_code == 201, retry.text
    assert retry.json()["created"] is False
    assert retry.json()["card"]["id"] == card_id

    fetched = external_api.client.get(f"/api/v1/cards/{card_id}", headers=headers)
    assert fetched.status_code == 200

    updated = external_api.client.patch(
        f"/api/v1/cards/{card_id}",
        json={"meaning": "引用；援引", "pos": "v", "note": "plain text note"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["meaning"] == "引用；援引"
    assert updated.json()["pos"] == "v."

    archived = external_api.client.post(
        f"/api/v1/cards/{card_id}/archive",
        json={"archived": True},
        headers=headers,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["isArchived"] is True

    deleted = external_api.client.delete(f"/api/v1/cards/{card_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"cardId": card_id, "deleted": True}


def test_external_rate_limit_returns_standard_headers(external_api, monkeypatch):
    api_key = _create_key(external_api)
    limiter = ExternalRateLimiter(limit=1, window_seconds=60)
    monkeypatch.setattr(external_router, "write_limiter", limiter)
    headers = {"X-KG-API-Key": api_key}

    first = external_api.client.post(
        "/api/v1/cards",
        json={"content": "first", "meaning": "第一"},
        headers=headers,
    )
    second = external_api.client.post(
        "/api/v1/cards",
        json={"content": "second", "meaning": "第二"},
        headers=headers,
    )

    assert first.status_code == 201
    assert first.headers["X-RateLimit-Limit"] == "1"
    assert first.headers["X-RateLimit-Remaining"] == "0"
    assert second.status_code == 429
    assert second.headers["X-RateLimit-Limit"] == "1"
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert int(second.headers["Retry-After"]) >= 1


def test_external_api_is_not_double_limited_by_generic_ip_limiter(external_api):
    api_key = _create_key(external_api)
    from kg.rate_limit import api_limiter

    client_ip = "198.51.100.77"
    now = time.monotonic()
    api_limiter._requests[client_ip] = collections.deque(
        [now] * api_limiter.max_requests
    )

    response = external_api.client.get(
        "/api/v1/cards",
        headers={"X-KG-API-Key": api_key, "X-Forwarded-For": client_ip},
    )

    assert response.status_code == 200, response.text


def test_external_card_delete_treats_embedding_eviction_as_best_effort(
    external_api, monkeypatch
):
    api_key = _create_key(external_api)
    headers = {"X-KG-API-Key": api_key}
    created = external_api.client.post(
        "/api/v1/cards",
        json={"content": "eviction", "meaning": "驅逐"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    card_id = created.json()["card"]["id"]

    def fail_embedding_eviction(*_args, **_kwargs):
        raise OSError("embedding store unavailable")

    monkeypatch.setattr(external_router, "_embedding_store", fail_embedding_eviction)

    deleted = external_api.client.delete(f"/api/v1/cards/{card_id}", headers=headers)

    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"cardId": card_id, "deleted": True}
    assert external_api.client.get(f"/api/v1/cards/{card_id}", headers=headers).status_code == 404


def test_external_enrich_operation_survives_process_memory_reset(external_api, monkeypatch):
    from kg import pipeline_log

    old_db_path = pipeline_log.DB_PATH
    pipeline_log._reset()
    pipeline_log.DB_PATH = external_api.data_dir / "pipeline_runs.db"
    try:
        api_key = _create_key(external_api)
        monkeypatch.setattr(external_router, "_run_external_pipeline", AsyncMock())
        response = external_api.client.post(
            "/api/v1/enrich",
            json={"notebookId": "default"},
            headers={"X-KG-API-Key": api_key},
        )
        assert response.status_code == 202, response.text
        operation_id = response.json()["operationId"]
        assert response.json()["status"] == "queued"

        pipeline_log.end_run(operation_id, "completed")
        external_router._OPERATIONS.clear()
        status = external_api.client.get(
            f"/api/v1/operations/{operation_id}",
            headers={"X-KG-API-Key": api_key},
        )
    finally:
        pipeline_log._reset()
        pipeline_log.DB_PATH = old_db_path

    assert status.status_code == 200, status.text
    assert status.json()["operationId"] == operation_id
    assert status.json()["status"] == "succeeded"


def test_account_erasure_removes_external_api_keys(external_api):
    api_key = _create_key(external_api)
    response = external_api.client.delete("/api/user/account", headers=external_api.jwt_headers)
    assert response.status_code == 200, response.text
    assert "_external_api_keys" not in json.loads(external_api.users_file.read_text())

    rejected = external_api.client.get(
        "/api/v1/cards",
        headers={"X-KG-API-Key": api_key},
    )
    assert rejected.status_code == 401
