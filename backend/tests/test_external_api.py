from __future__ import annotations

import asyncio
import collections
import json
import math
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import kg.routers.external_api as external_router
from conftest import TEST_JWT_SECRET, _swap_settings, make_jwt
from kg.api import app
from kg.api_models.external_api import ExternalCardReviewRequest
from kg.external_api_keys import list_api_keys
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


def test_external_api_key_listing_orders_mixed_offsets_by_utc_and_key_id():
    user_id = "user-1"
    key_a = "a" * 32
    key_b = "b" * 32
    key_c = "c" * 32
    key_d = "d" * 32
    users = {
        user_id: {"config": {}},
        "other-user": {"config": {}},
        "_external_api_keys": {
            key_d: {
                "user_id": user_id,
                "label": "revoked",
                "created_at": "2026-08-29T00:30:00+00:00",
                "revoked_at": "2026-08-29T02:00:00+08:00",
            },
            key_a: {
                "user_id": user_id,
                "label": "tie-a",
                "created_at": "2026-08-29T09:00:00+08:00",
                "revoked_at": None,
            },
            key_c: {
                "user_id": user_id,
                "label": "tie-c",
                "created_at": "2026-08-29T01:00:00Z",
                "revoked_at": None,
            },
            key_b: {
                "user_id": user_id,
                "label": "newest",
                "created_at": "2026-08-29T00:30:00-04:00",
                "revoked_at": None,
            },
            "e" * 32: {
                "user_id": "other-user",
                "label": "filtered",
                "created_at": "2026-08-30T00:00:00Z",
                "revoked_at": None,
            },
        },
    }

    records = list_api_keys(user_id, load_users=lambda: users)

    assert [record["keyId"] for record in records] == [key_b, key_c, key_a, key_d]
    assert [record["label"] for record in records] == ["newest", "tie-c", "tie-a", "revoked"]
    assert records[-1]["createdAt"] == "2026-08-29T00:30:00+00:00"
    assert records[-1]["revokedAt"] == "2026-08-29T02:00:00+08:00"


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


def test_external_card_concurrent_duplicate_requests_are_idempotent(external_api, monkeypatch):
    api_key = _create_key(external_api)
    headers = {"X-KG-API-Key": api_key}
    store = external_router._card_store(external_api.data_dir / "users" / external_api.user_id)
    original_find = type(store).find_by_content
    find_barrier = threading.Barrier(2)
    find_calls_lock = threading.Lock()
    find_calls = 0
    request_barrier = threading.Barrier(2)

    def synchronize_initial_lookup(self, *args, **kwargs):
        nonlocal find_calls
        result = original_find(self, *args, **kwargs)
        with find_calls_lock:
            find_calls += 1
            synchronize = find_calls <= 2
        if synchronize:
            find_barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(type(store), "find_by_content", synchronize_initial_lookup)
    payload = {
        "content": "concurrent single card",
        "meaning": "created exactly once",
        "clientId": "concurrent-single-client",
    }

    def post_card():
        request_barrier.wait(timeout=5)
        return external_api.client.post("/api/v1/cards", json=payload, headers=headers)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: post_card(), range(2)))

    assert sorted(response.status_code for response in responses) == [201, 201]
    bodies = [response.json() for response in responses]
    assert sorted(body["created"] for body in bodies) == [False, True]
    assert len({body["card"]["id"] for body in bodies}) == 1

    listed = external_api.client.get("/api/v1/cards", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [item["content"] for item in listed.json()["items"]] == ["concurrent single card"]


def test_external_card_batch_rolls_back_when_later_entry_is_invalid(external_api):
    api_key = _create_key(external_api)
    headers = {"X-KG-API-Key": api_key}

    response = external_api.client.post(
        "/api/v1/cards/batch",
        json={
            "items": [
                {
                    "content": "batch atomic survivor",
                    "meaning": "must be rolled back",
                    "clientId": "valid-first",
                },
                {
                    "content": "...",
                    "meaning": "invalid after content cleanup",
                    "clientId": "invalid-second",
                },
            ]
        },
        headers=headers,
    )

    assert response.status_code == 422, response.text
    listed = external_api.client.get("/api/v1/cards", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []


def test_external_card_batch_rolls_back_when_later_write_fails(external_api, monkeypatch):
    api_key = _create_key(external_api)
    headers = {"X-KG-API-Key": api_key}
    store = external_router._card_store(external_api.data_dir / "users" / external_api.user_id)
    original_add = type(store).add
    add_calls = 0

    def fail_second_add(self, *args, **kwargs):
        nonlocal add_calls
        add_calls += 1
        if add_calls == 2:
            raise OSError("simulated second card write failure")
        return original_add(self, *args, **kwargs)

    monkeypatch.setattr(type(store), "add", fail_second_add)

    response = external_api.client.post(
        "/api/v1/cards/batch",
        json={
            "items": [
                {"content": "batch write first", "clientId": "write-first"},
                {"content": "batch write second", "clientId": "write-second"},
            ]
        },
        headers=headers,
    )

    assert response.status_code == 500, response.text
    listed = external_api.client.get("/api/v1/cards", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []


def test_external_card_batch_preserves_success_and_duplicate_semantics(external_api):
    api_key = _create_key(external_api)
    headers = {"X-KG-API-Key": api_key}
    existing = external_api.client.post(
        "/api/v1/cards",
        json={"content": "batch duplicate", "meaning": "existing"},
        headers=headers,
    )
    assert existing.status_code == 201, existing.text

    response = external_api.client.post(
        "/api/v1/cards/batch",
        json={
            "items": [
                {
                    "content": "Batch duplicate!",
                    "meaning": "ignored duplicate payload",
                    "clientId": "duplicate-client",
                },
                {
                    "content": "batch newly created",
                    "meaning": "new card",
                    "clientId": "new-client",
                },
                {
                    "content": "Batch newly created!",
                    "meaning": "same-batch duplicate payload",
                    "clientId": "same-batch-duplicate-client",
                },
            ]
        },
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] == 1
    assert body["duplicates"] == 2
    assert [item["clientId"] for item in body["items"]] == [
        "duplicate-client",
        "new-client",
        "same-batch-duplicate-client",
    ]
    assert [item["created"] for item in body["items"]] == [False, True, False]
    assert body["items"][0]["card"]["id"] == existing.json()["card"]["id"]
    assert body["items"][1]["card"]["content"] == "batch newly created"
    assert body["items"][2]["card"]["id"] == body["items"][1]["card"]["id"]


def test_external_card_batch_concurrent_duplicate_requests_are_idempotent(external_api, monkeypatch):
    api_key = _create_key(external_api)
    headers = {"X-KG-API-Key": api_key}
    store = external_router._card_store(external_api.data_dir / "users" / external_api.user_id)
    original_add = type(store).add
    add_barrier = threading.Barrier(2)
    add_calls_lock = threading.Lock()
    add_calls = 0
    request_barrier = threading.Barrier(2)

    def synchronize_duplicate_add(self, *args, **kwargs):
        nonlocal add_calls
        with add_calls_lock:
            add_calls += 1
            synchronize = add_calls <= 2
        if synchronize:
            add_barrier.wait(timeout=5)
        return original_add(self, *args, **kwargs)

    monkeypatch.setattr(type(store), "add", synchronize_duplicate_add)
    payload = {
        "items": [
            {
                "content": "concurrent batch duplicate",
                "meaning": "created exactly once",
                "clientId": "concurrent-client",
            }
        ]
    }

    def post_batch():
        request_barrier.wait(timeout=5)
        return external_api.client.post("/api/v1/cards/batch", json=payload, headers=headers)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: post_batch(), range(2)))

    assert sorted(response.status_code for response in responses) == [201, 201]
    bodies = [response.json() for response in responses]
    assert sorted(body["created"] for body in bodies) == [0, 1]
    assert sorted(body["duplicates"] for body in bodies) == [0, 1]
    assert sorted(body["items"][0]["created"] for body in bodies) == [False, True]
    assert len({body["items"][0]["card"]["id"] for body in bodies}) == 1

    listed = external_api.client.get("/api/v1/cards", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [item["content"] for item in listed.json()["items"]] == ["concurrent batch duplicate"]


def _review_payload(interval):
    return {
        "reviewIntervalHours": interval,
        "nextReviewAt": "2026-01-02T00:00:00Z",
        "lastReviewedAt": "2026-01-01T00:00:00Z",
        "reviewCount": 1,
        "lapseCount": 0,
        "reviewStreak": 1,
        "lastReviewFeedback": 1,
    }


@pytest.mark.parametrize("value", [math.inf, math.nan])
def test_external_card_review_request_rejects_non_finite_interval(value):
    with pytest.raises(ValidationError):
        ExternalCardReviewRequest(**_review_payload(value))


@pytest.mark.parametrize("raw_interval", ["Infinity", "NaN"])
def test_external_card_review_route_rejects_non_finite_interval_without_write(external_api, raw_interval):
    api_key = _create_key(external_api)
    headers = {"X-KG-API-Key": api_key}
    created = external_api.client.post(
        "/api/v1/cards",
        json={"content": "finite review", "meaning": "有限複習"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    card_id = created.json()["card"]["id"]

    payload = json.dumps(_review_payload(0)).replace("0", raw_interval, 1)
    response = external_api.client.post(
        f"/api/v1/cards/{card_id}/review",
        content=payload,
        headers={**headers, "Content-Type": "application/json"},
    )

    assert response.status_code == 422, response.text
    fetched = external_api.client.get(f"/api/v1/cards/{card_id}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["reviewIntervalHours"] == 12.0


def test_external_card_review_route_preserves_finite_interval(external_api):
    api_key = _create_key(external_api)
    headers = {"X-KG-API-Key": api_key}
    created = external_api.client.post(
        "/api/v1/cards",
        json={"content": "finite review accepted", "meaning": "有限複習通過"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    card_id = created.json()["card"]["id"]

    response = external_api.client.post(
        f"/api/v1/cards/{card_id}/review",
        json=_review_payload(24.5),
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["reviewIntervalHours"] == 24.5


def test_external_rate_limiter_preserves_active_windows_at_key_cap():
    async def run():
        limiter = ExternalRateLimiter(limit=1, window_seconds=60, max_keys=2)
        decisions = [await limiter.admit(key) for key in ("victim", "noise-a", "noise-b", "victim")]
        return decisions, list(limiter._events)

    decisions, keys = asyncio.run(run())

    assert [decision.allowed for decision in decisions] == [True, True, False, False]
    assert keys == ["noise-a", "victim"]


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


def test_external_rate_limiter_rejects_non_positive_max_keys():
    with pytest.raises(ValueError, match="max_keys must be positive"):
        ExternalRateLimiter(limit=1, window_seconds=60, max_keys=0)

    with pytest.raises(ValueError, match="max_keys must be positive"):
        ExternalRateLimiter(limit=1, window_seconds=60, max_keys=-1)


def test_external_api_is_not_double_limited_by_generic_ip_limiter(external_api):
    api_key = _create_key(external_api)
    from kg.rate_limit import api_limiter

    client_ip = "198.51.100.77"
    now = time.monotonic()
    api_limiter._requests[client_ip] = collections.deque([now] * api_limiter.max_requests)

    response = external_api.client.get(
        "/api/v1/cards",
        headers={"X-KG-API-Key": api_key, "X-Forwarded-For": client_ip},
    )

    assert response.status_code == 200, response.text


def test_external_card_delete_treats_embedding_eviction_as_best_effort(external_api, monkeypatch):
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
