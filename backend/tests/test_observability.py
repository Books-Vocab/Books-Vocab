from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.deps as deps_mod
import kg.routers.user as user_router_mod
from conftest import TEST_JWT_SECRET, _swap_settings, make_jwt
from kg.api import _mem_log, app
from kg.request_context import request_id_var
from kg.settings import KGSettings


@pytest.fixture()
def isolated_api(tmp_path):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    users_file = data_dir / "users.json"
    data_dir / "users.json.lock"
    data_dir / "app_store_notifications.ndjson"
    users_file.write_text(
        json.dumps({user_id: {"config": {}}, "subscription": {"is_active": True}})
    )

    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users
    test_settings = KGSettings(data_dir=data_dir, jwt_secret=TEST_JWT_SECRET)
    _swap_settings(test_settings)

    try:
        api_mod._USER_LOCKS.clear()
        deps_mod._USER_LOCKS_MUTEX = None
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(
            client=client,
            user_id=user_id,
            headers=headers,
            data_dir=data_dir,
            users_file=users_file,
        )
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


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


class TestKGErrorObservability:
    """Domain errors (KGError 4xx/5xx) must leave a server-side log line.

    Regression guard for the silent-400 blind spot: the review-event watermark
    deadlock returned HTTP 400 on every background sync yet produced no log,
    no Sentry event, and no metric — invisible server-side until a user sent a
    screenshot. ``kg_error_handler`` now logs every domain error.
    """

    def test_client_error_is_logged_with_status_and_path(self, isolated_api):
        r = isolated_api.client.get(
            "/api/vocab/review-events?since=garbage", headers=isolated_api.headers
        )
        assert r.status_code == 400, r.text
        warnings = _mem_log.get(n=200, level="WARNING")
        matching = [
            e
            for e in warnings
            if "BadRequestError" in e["msg"]
            and "/api/vocab/review-events" in e["msg"]
            and "400" in e["msg"]
        ]
        assert matching, f"expected a warning log for the silent 400; got {warnings[-5:]}"


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
            patch.object(user_router_mod, "_card_store", return_value=cards_mock),
            patch.object(user_router_mod, "_graph_store", return_value=graph_mock),
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
            patch.object(user_router_mod, "_card_store", return_value=cards_mock),
            patch.object(user_router_mod, "_graph_store", return_value=graph_mock),
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
            patch.object(user_router_mod, "_card_store", return_value=cards_mock),
            patch.object(user_router_mod, "_graph_store", return_value=graph_mock),
        ):
            r = isolated_api.client.get("/api/health", headers=isolated_api.headers)

        assert r.status_code == 200, r.text
        body = r.json()
        assert "data_dir_exists" in body
        assert body["data_dir_exists"] is True
