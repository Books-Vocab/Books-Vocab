from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
from kg.api import app, _mem_log
from kg.request_context import request_id_var

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"


def make_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "provider": "test",
        "iat": datetime.now(tz=UTC),
        "exp": datetime.now(tz=UTC) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture()
def isolated_api(tmp_path):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    users_file = data_dir / "users.json"
    lock_file = data_dir / "users.json.lock"
    notifications_file = data_dir / "app_store_notifications.ndjson"
    users_file.write_text(
        json.dumps({user_id: {"config": {}}, "subscription": {"is_active": True}})
    )

    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch.object(api_mod, "DATA_DIR", data_dir),
        patch.object(api_mod, "USERS_FILE", users_file),
        patch.object(api_mod, "USERS_LOCK_FILE", lock_file),
        patch.object(api_mod, "APP_STORE_NOTIFICATIONS_FILE", notifications_file),
    ):
        api_mod._USER_LOCKS.clear()
        api_mod._USER_LOCKS_MUTEX = None
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(
            client=client,
            user_id=user_id,
            headers=headers,
            data_dir=data_dir,
            users_file=users_file,
        )


class TestRequestIdMiddleware:

    def test_response_has_x_request_id_header(self, isolated_api):
        r = isolated_api.client.get("/privacy")
        assert "x-request-id" in r.headers

    def test_generated_request_id_is_nonempty(self, isolated_api):
        r = isolated_api.client.get("/privacy")
        assert len(r.headers["x-request-id"]) > 0

    def test_client_provided_request_id_echoed_back(self, isolated_api):
        custom_id = "my-trace-id-12345"
        r = isolated_api.client.get("/privacy", headers={"X-Request-ID": custom_id})
        assert r.headers["x-request-id"] == custom_id

    def test_different_requests_get_different_ids(self, isolated_api):
        r1 = isolated_api.client.get("/privacy")
        r2 = isolated_api.client.get("/privacy")
        assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


class TestMemoryLogHandlerRequestId:

    def test_log_entry_contains_request_id_field(self):
        tok = request_id_var.set("test-rid-abc")
        try:
            record = logging.LogRecord("kg.api", logging.INFO, "", 0, "observability test message", (), None)
            _mem_log.emit(record)
        finally:
            request_id_var.reset(tok)

        entries = _mem_log.get(n=50)
        matching = [e for e in entries if "observability test message" in e.get("msg", "")]
        assert matching, "log entry not found"
        assert matching[-1]["request_id"] == "test-rid-abc"

    def test_log_entry_default_request_id_when_no_context(self):
        record = logging.LogRecord("kg.api", logging.INFO, "", 0, "no-context observability message", (), None)
        _mem_log.emit(record)

        entries = _mem_log.get(n=50)
        matching = [e for e in entries if "no-context observability message" in e.get("msg", "")]
        assert matching
        assert "request_id" in matching[-1]


class TestHealthDeepCheck:

    def test_health_returns_disk_free_mb(self, isolated_api, tmp_path):
        user_id = isolated_api.user_id
        user_dir = isolated_api.data_dir / "users" / user_id
        user_dir.mkdir(parents=True, exist_ok=True)

        cards_mock = MagicMock()
        cards_mock.count.return_value = 0
        graph_mock = MagicMock()
        graph_mock.link_count.return_value = 0
        graph_mock.candidate_count.return_value = 0

        with (
            patch.object(api_mod, "_card_store", return_value=cards_mock),
            patch.object(api_mod, "_graph_store", return_value=graph_mock),
        ):
            r = isolated_api.client.get("/api/health", headers=isolated_api.headers)

        assert r.status_code == 200, r.text
        body = r.json()
        assert "disk_free_mb" in body
        assert isinstance(body["disk_free_mb"], int)
        assert body["disk_free_mb"] >= 0

    def test_health_returns_db_ok(self, isolated_api):
        user_id = isolated_api.user_id
        user_dir = isolated_api.data_dir / "users" / user_id
        user_dir.mkdir(parents=True, exist_ok=True)

        cards_mock = MagicMock()
        cards_mock.count.return_value = 5
        graph_mock = MagicMock()
        graph_mock.link_count.return_value = 0
        graph_mock.candidate_count.return_value = 0

        with (
            patch.object(api_mod, "_card_store", return_value=cards_mock),
            patch.object(api_mod, "_graph_store", return_value=graph_mock),
        ):
            r = isolated_api.client.get("/api/health", headers=isolated_api.headers)

        assert r.status_code == 200, r.text
        body = r.json()
        assert "db_ok" in body
        assert body["db_ok"] is True

    def test_health_returns_data_dir_exists(self, isolated_api):
        user_id = isolated_api.user_id
        user_dir = isolated_api.data_dir / "users" / user_id
        user_dir.mkdir(parents=True, exist_ok=True)

        cards_mock = MagicMock()
        cards_mock.count.return_value = 0
        graph_mock = MagicMock()
        graph_mock.link_count.return_value = 0
        graph_mock.candidate_count.return_value = 0

        with (
            patch.object(api_mod, "_card_store", return_value=cards_mock),
            patch.object(api_mod, "_graph_store", return_value=graph_mock),
        ):
            r = isolated_api.client.get("/api/health", headers=isolated_api.headers)

        assert r.status_code == 200, r.text
        body = r.json()
        assert "data_dir_exists" in body
        assert body["data_dir_exists"] is True
