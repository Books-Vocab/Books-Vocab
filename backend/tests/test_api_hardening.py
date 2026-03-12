"""
Tests for API hardening: input validation, request size limit, _USER_LOCKS LRU cap.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
from kg.api import app

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"


def make_jwt(user_id: str) -> str:
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt

    payload = {
        "sub": user_id,
        "provider": "test",
        "iat": datetime.now(tz=UTC),
        "exp": datetime.now(tz=UTC) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture()
def client_env(tmp_path):
    (tmp_path / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:6]
    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    users_file = tmp_path / "users.json"
    lock_file = tmp_path / "users.json.lock"
    notifications_file = tmp_path / "app_store_notifications.ndjson"
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

    with (
        patch.object(api_mod, "DATA_DIR", tmp_path),
        patch.object(api_mod, "USERS_FILE", users_file),
        patch.object(api_mod, "USERS_LOCK_FILE", lock_file),
        patch.object(api_mod, "APP_STORE_NOTIFICATIONS_FILE", notifications_file),
        patch.object(api_mod, "APP_STORE_ALLOW_UNSIGNED_SYNC", True),
        patch.object(api_mod, "APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS", True),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        yield client, user_id, headers, tmp_path


# ============================================================================
# Task 1 — _USER_LOCKS LRU cap
# ============================================================================


class TestUserLocksLRU:

    def test_locks_capped_at_max(self):
        async def run():
            api_mod._USER_LOCKS.clear()
            api_mod._USER_LOCKS_MUTEX = None
            for i in range(api_mod._MAX_USER_LOCKS + 50):
                await api_mod.get_user_lock(f"user_{i}")
            return len(api_mod._USER_LOCKS)

        size = asyncio.run(run())
        assert size <= api_mod._MAX_USER_LOCKS, (
            f"_USER_LOCKS grew to {size}, expected <= {api_mod._MAX_USER_LOCKS}"
        )

    def test_recent_user_kept_after_eviction(self):
        async def run():
            api_mod._USER_LOCKS.clear()
            api_mod._USER_LOCKS_MUTEX = None
            # Fill to max
            for i in range(api_mod._MAX_USER_LOCKS):
                await api_mod.get_user_lock(f"old_user_{i}")
            # Access a recent user — should be kept
            lk = await api_mod.get_user_lock("recent_user")
            # Add one more to trigger eviction
            await api_mod.get_user_lock("new_user_trigger")
            return "recent_user" in api_mod._USER_LOCKS

        kept = asyncio.run(run())
        assert kept, "recently accessed user should not be evicted"

    def test_same_user_returns_same_lock_after_reaccess(self):
        async def run():
            api_mod._USER_LOCKS.clear()
            api_mod._USER_LOCKS_MUTEX = None
            l1 = await api_mod.get_user_lock("stable_user")
            # Access many other users to push eviction pressure
            for i in range(api_mod._MAX_USER_LOCKS - 1):
                await api_mod.get_user_lock(f"filler_{i}")
            # Re-access stable_user before eviction pressure hits it
            l2 = await api_mod.get_user_lock("stable_user")
            return l1 is l2

        assert asyncio.run(run()), "same lock object must be returned for reaccessed user"


# ============================================================================
# Task 2 — Input length validation (422)
# ============================================================================


class TestInputValidation:

    def test_translate_word_too_long_returns_422(self, client_env):
        client, user_id, headers, _ = client_env
        r = client.post(
            "/api/translate/quick",
            json={"word": "x" * 501, "context": "some context"},
            headers=headers,
        )
        assert r.status_code == 422, r.text

    def test_translate_context_too_long_returns_422(self, client_env):
        client, user_id, headers, _ = client_env
        r = client.post(
            "/api/translate/quick",
            json={"word": "hello", "context": "x" * 5001},
            headers=headers,
        )
        assert r.status_code == 422, r.text

    def test_translate_word_at_limit_accepted(self, client_env):
        client, user_id, headers, _ = client_env
        from unittest.mock import AsyncMock, patch as _patch

        with _patch("kg.translate_service.quick_translate", new=AsyncMock(return_value={"t": "hello", "p": None, "r": None})):
            r = client.post(
                "/api/translate/quick",
                json={"word": "x" * 500, "context": "some context"},
                headers=headers,
            )
        assert r.status_code != 422, f"Exactly 500 chars should be accepted, got {r.status_code}"

    def test_vocab_word_too_long_returns_422(self, client_env):
        client, user_id, headers, _ = client_env
        r = client.post(
            "/api/vocab",
            json=[{"word": "x" * 201, "translation": "test", "context": ""}],
            headers=headers,
        )
        assert r.status_code == 422, r.text

    def test_vocab_translation_too_long_returns_422(self, client_env):
        client, user_id, headers, _ = client_env
        r = client.post(
            "/api/vocab",
            json=[{"word": "hello", "translation": "x" * 1001, "context": ""}],
            headers=headers,
        )
        assert r.status_code == 422, r.text

    def test_vocab_context_too_long_returns_422(self, client_env):
        client, user_id, headers, _ = client_env
        r = client.post(
            "/api/vocab",
            json=[{"word": "hello", "translation": "test", "context": "x" * 5001}],
            headers=headers,
        )
        assert r.status_code == 422, r.text


# ============================================================================
# Task 3 — Request body size limit (413)
# ============================================================================


class TestRequestBodySizeLimit:

    def test_large_body_returns_413(self, client_env):
        client, user_id, headers, _ = client_env
        large_body = b"x" * (11 * 1024 * 1024)  # 11MB
        r = client.post(
            "/api/vocab",
            content=large_body,
            headers={**headers, "content-type": "application/json", "content-length": str(len(large_body))},
        )
        assert r.status_code == 413, r.text

    def test_body_at_limit_not_rejected_by_size(self, client_env):
        client, user_id, headers, _ = client_env
        # 9MB body — should NOT get 413 (may still get 422 from JSON parse, but not 413)
        small_body = b"x" * (9 * 1024 * 1024)
        r = client.post(
            "/api/vocab",
            content=small_body,
            headers={**headers, "content-type": "application/json", "content-length": str(len(small_body))},
        )
        assert r.status_code != 413, "9MB body should not be rejected by size limit middleware"
