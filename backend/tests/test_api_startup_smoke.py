from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.admin_test_matrix as admin_test_matrix_mod
from kg.api import app

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"


def make_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "provider": "test",
        "iat": datetime.now(tz=timezone.utc),
        "exp": datetime.now(tz=timezone.utc) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture()
def startup_env(tmp_path):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    users_file = data_dir / "users.json"
    lock_file = data_dir / "users.json.lock"
    notifications_file = data_dir / "app_store_notifications.ndjson"
    users_file.write_text(
        json.dumps(
            {
                user_id: {
                    "config": {},
                    "subscription": {
                        "is_active": True,
                        "status": "active",
                        "plan_name": "Books & Vocab Pro",
                        "trial_days": 7,
                        "will_renew": True,
                    },
                }
            }
        )
    )

    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch.object(api_mod, "DATA_DIR", data_dir),
        patch.object(api_mod, "USERS_FILE", users_file),
        patch.object(api_mod, "USERS_LOCK_FILE", lock_file),
        patch.object(api_mod, "APP_STORE_NOTIFICATIONS_FILE", notifications_file),
        patch.object(api_mod, "ADMIN_TOKEN", "adm-secret"),
        patch.object(api_mod, "APP_STORE_ALLOW_UNSIGNED_SYNC", True),
        patch.object(api_mod, "APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS", True),
    ):
        api_mod._USER_LOCKS.clear()
        api_mod._USER_LOCKS_MUTEX = None
        admin_test_matrix_mod.LAST_TEST_RUN = None
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(
            client=client,
            user_id=user_id,
            headers=headers,
        )
        admin_test_matrix_mod.LAST_TEST_RUN = None


def test_startup_smoke_serves_admin_and_core_routes(startup_env):
    client = startup_env.client

    admin_ui = client.get("/admin", params={"token": "adm-secret"})
    assert admin_ui.status_code == 200, admin_ui.text
    assert "WordNexus Admin" in admin_ui.text

    admin_tests_ui = client.get("/admin/tests", params={"token": "adm-secret"})
    assert admin_tests_ui.status_code == 200, admin_tests_ui.text
    assert "WordNexus Admin" in admin_tests_ui.text

    admin_test_alias = client.get("/admin/test", params={"token": "adm-secret"})
    assert admin_test_alias.status_code == 200, admin_test_alias.text
    assert "WordNexus Admin" in admin_test_alias.text

    entitlements = client.get("/api/user/entitlements", headers=startup_env.headers)
    assert entitlements.status_code == 200, entitlements.text
    assert entitlements.json()["pro"]["is_active"] is True

    health = client.get("/api/health", headers=startup_env.headers)
    assert health.status_code == 200, health.text
    assert health.json()["status"] == "ok"


def test_startup_smoke_admin_catalog_and_last_result_routes(startup_env):
    client = startup_env.client

    catalog = client.get("/api/admin/tests/catalog", params={"token": "adm-secret"})
    assert catalog.status_code == 200, catalog.text
    body = catalog.json()
    assert "columns" in body
    assert "items" in body
    assert any(item["id"] == "pipeline_integration" for item in body["items"])

    last = client.get("/api/admin/tests/last", params={"token": "adm-secret"})
    assert last.status_code == 200, last.text
    assert last.json()["status"] == "idle"


def test_startup_smoke_admin_run_updates_last_result(startup_env):
    client = startup_env.client
    fake_result = {
        "runId": "20260307000100",
        "startedAt": "2026-03-07T00:01:00+00:00",
        "finishedAt": "2026-03-07T00:01:02+00:00",
        "durationSeconds": 2.0,
        "returnCode": 0,
        "outcome": "passed",
        "totals": {"passed": 1, "failed": 0, "errors": 0, "skipped": 0, "total": 1},
        "selectedItems": ["renderer_truncation"],
        "matrix": [],
        "cases": [],
        "itemResults": [],
        "stdoutTail": [],
        "stderrTail": [],
    }

    with patch("kg.admin_wiring.run_pytest_matrix", return_value=fake_result):
        run = client.post(
            "/api/admin/tests/run",
            params={"token": "adm-secret"},
            json={"itemIds": ["renderer_truncation"]},
        )
    assert run.status_code == 200, run.text
    assert run.json()["runId"] == fake_result["runId"]

    last = client.get("/api/admin/tests/last", params={"token": "adm-secret"})
    assert last.status_code == 200, last.text
    assert last.json()["runId"] == fake_result["runId"]
