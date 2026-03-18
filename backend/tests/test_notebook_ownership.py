"""notebook_id ownership validation tests.

Verifies that vocab endpoints return 403 when the caller supplies a
notebook_id that does not belong to the authenticated user.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.deps as deps_mod
import kg.routers.vocab as vocab_router_mod
from kg.api import app
from kg.settings import KGSettings

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"


def make_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "provider": "test",
        "iat": datetime.now(tz=UTC),
        "exp": datetime.now(tz=UTC) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def _swap_settings(new_settings):
    from kg.user_store import CachedUserStore, load_users_from, save_users_to, normalize_users_payload
    from kg.billing import default_subscription_payload

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
    app.state.normalize_users_payload = _normalize


@pytest.fixture()
def isolated_api(tmp_path):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    users_file = data_dir / "users.json"
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
                },
            }
        )
    )

    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users

    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        app_store_allow_unsigned_sync=True,
        app_store_allow_unsigned_notifications=True,
    )
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
        )
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


NONEXISTENT_NB = "nb_does_not_exist_xyz"


class _DummyEmbeddingStore:
    def __init__(self) -> None:
        self._ids: set[str] = set()

    def has(self, card_id: str) -> bool:
        return card_id in self._ids

    def add(self, card_id: str, text: str) -> None:
        self._ids.add(card_id)

    def find_similar(self, card_id: str, k: int = 3):
        return []


class TestNotebookOwnershipValidation:
    """All vocab endpoints that accept notebook_id must return 403 for unknown ids."""

    def test_get_vocab_unknown_notebook_id_returns_403(self, isolated_api):
        r = isolated_api.client.get(
            "/api/vocab",
            params={"notebook_id": NONEXISTENT_NB},
            headers=isolated_api.headers,
        )
        assert r.status_code == 403, r.text

    def test_lookup_word_unknown_notebook_id_returns_403(self, isolated_api):
        r = isolated_api.client.get(
            "/api/vocab/hello",
            params={"notebook_id": NONEXISTENT_NB},
            headers=isolated_api.headers,
        )
        assert r.status_code == 403, r.text

    def test_archive_word_unknown_notebook_id_returns_403(self, isolated_api):
        r = isolated_api.client.patch(
            "/api/vocab/hello/archive",
            json={"archived": True},
            params={"notebook_id": NONEXISTENT_NB},
            headers=isolated_api.headers,
        )
        assert r.status_code == 403, r.text

    def test_delete_word_unknown_notebook_id_returns_403(self, isolated_api):
        r = isolated_api.client.delete(
            "/api/vocab/hello",
            params={"notebook_id": NONEXISTENT_NB},
            headers=isolated_api.headers,
        )
        assert r.status_code == 403, r.text

    def test_graph_links_unknown_notebook_id_returns_403(self, isolated_api):
        r = isolated_api.client.get(
            "/api/graph/links",
            params={"notebook_id": NONEXISTENT_NB},
            headers=isolated_api.headers,
        )
        assert r.status_code == 403, r.text

    def test_add_vocab_unknown_notebook_id_returns_403(self, isolated_api):
        emb = _DummyEmbeddingStore()
        with patch.object(vocab_router_mod, "_embedding_store", return_value=emb):
            r = isolated_api.client.post(
                "/api/vocab",
                json=[{"word": "test", "translation": "測試", "context": "A test sentence."}],
                params={"notebook_id": NONEXISTENT_NB},
                headers=isolated_api.headers,
            )
        assert r.status_code == 403, r.text

    def test_add_vocab_default_notebook_is_allowed(self, isolated_api):
        """POST /api/vocab with default notebook should succeed (not 403)."""
        emb = _DummyEmbeddingStore()
        with patch.object(vocab_router_mod, "_embedding_store", return_value=emb):
            r = isolated_api.client.post(
                "/api/vocab",
                json=[{"word": "test", "translation": "測試", "context": "A test sentence."}],
                params={"notebook_id": "default"},
                headers=isolated_api.headers,
            )
        assert r.status_code != 403, r.text

    def test_get_vocab_default_notebook_is_allowed(self, isolated_api):
        """The 'default' notebook always exists — must NOT be blocked."""
        r = isolated_api.client.get(
            "/api/vocab",
            params={"notebook_id": "default"},
            headers=isolated_api.headers,
        )
        # 200 OK (empty list is fine)
        assert r.status_code == 200, r.text

    def test_get_vocab_no_notebook_id_is_allowed(self, isolated_api):
        """Omitting notebook_id must also work — no validation needed when None."""
        r = isolated_api.client.get("/api/vocab", headers=isolated_api.headers)
        assert r.status_code == 200, r.text

    def test_deleted_notebook_is_rejected(self, isolated_api):
        """A soft-deleted notebook must return 403, not 200."""
        from kg.service_factories import create_notebook_store

        user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        nb_store = create_notebook_store(user_dir)
        nb = nb_store.create("Temp Notebook")
        nb_store.delete(nb.id)

        r = isolated_api.client.get(
            "/api/vocab",
            params={"notebook_id": nb.id},
            headers=isolated_api.headers,
        )
        assert r.status_code == 403, r.text
