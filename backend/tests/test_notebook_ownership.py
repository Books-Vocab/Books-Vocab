"""notebook_id ownership validation tests.

Verifies that vocab endpoints return 403 when the caller supplies a
notebook_id that does not belong to the authenticated user.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.deps as deps_mod
import kg.pipeline_log as pipeline_log_mod
import kg.routers.vocab as vocab_router_mod
from conftest import TEST_JWT_SECRET, _DummyEmbeddingStore, make_jwt
from kg.api import create_app
from kg.settings import KGSettings


@pytest.fixture()
def isolated_api(tmp_path, monkeypatch):
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

    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        app_store_allow_unsigned_sync=True,
        app_store_allow_unsigned_notifications=True,
    )
    test_app = create_app(test_settings)

    monkeypatch.setattr(pipeline_log_mod, "DB_PATH", data_dir / "pipeline_runs.db")
    pipeline_log_mod._reset()
    api_mod._USER_LOCKS.clear()
    deps_mod._USER_LOCKS_MUTEX = None
    try:
        with TestClient(test_app, raise_server_exceptions=False) as client:
            yield SimpleNamespace(
                client=client,
                user_id=user_id,
                headers=headers,
                data_dir=data_dir,
            )
    finally:
        pipeline_log_mod._reset()


@pytest.fixture()
def assert_client_context_manager(monkeypatch):
    exits = []
    original_exit = TestClient.__exit__

    def record_exit(client, *args):
        exits.append(client)
        return original_exit(client, *args)

    monkeypatch.setattr(TestClient, "__exit__", record_exit)
    yield
    assert len(exits) == 1


NONEXISTENT_NB = "nb_does_not_exist_xyz"


class TestNotebookOwnershipValidation:
    """All vocab endpoints that accept notebook_id must return 403 for unknown ids."""

    def test_isolated_api_closes_test_client(
        self, assert_client_context_manager, isolated_api
    ):
        del assert_client_context_manager, isolated_api

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
