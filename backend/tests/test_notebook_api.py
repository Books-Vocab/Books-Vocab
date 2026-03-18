"""Integration tests for notebook CRUD HTTP endpoints.

Covers: GET /api/notebooks, POST /api/notebooks, PATCH /api/notebooks/{nb_id},
DELETE /api/notebooks/{nb_id}.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.deps as deps_mod
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
    from kg.user_store import CachedUserStore, normalize_users_payload
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nb_ids(body: list[dict]) -> set[str]:
    return {nb["id"] for nb in body}


# ---------------------------------------------------------------------------
# GET /api/notebooks
# ---------------------------------------------------------------------------


def test_list_notebooks_empty_state(isolated_api):
    """Fresh user — only the auto-created default notebook is returned."""
    r = isolated_api.client.get("/api/notebooks", headers=isolated_api.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    defaults = [nb for nb in body if nb["isDefault"]]
    assert len(defaults) == 1


def test_list_notebooks_after_create(isolated_api):
    """Notebooks created via POST appear in subsequent GET."""
    client = isolated_api.client
    h = isolated_api.headers

    client.post("/api/notebooks", json={"name": "Alpha", "color": "#ff0000"}, headers=h)
    client.post("/api/notebooks", json={"name": "Beta", "color": "#00ff00"}, headers=h)

    r = client.get("/api/notebooks", headers=h)
    assert r.status_code == 200, r.text
    names = {nb["name"] for nb in r.json()}
    assert {"Alpha", "Beta"}.issubset(names)


# ---------------------------------------------------------------------------
# POST /api/notebooks
# ---------------------------------------------------------------------------


def test_create_notebook_returns_201(isolated_api):
    r = isolated_api.client.post(
        "/api/notebooks",
        json={"name": "My Notebook", "color": "#abcdef"},
        headers=isolated_api.headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "My Notebook"
    assert body["color"] == "#abcdef"
    assert body["isDefault"] is False
    assert "id" in body


def test_create_notebook_appears_in_list(isolated_api):
    client = isolated_api.client
    h = isolated_api.headers

    r_create = client.post("/api/notebooks", json={"name": "NewNB", "color": "#111111"}, headers=h)
    assert r_create.status_code == 201
    nb_id = r_create.json()["id"]

    r_list = client.get("/api/notebooks", headers=h)
    assert nb_id in _nb_ids(r_list.json())


# ---------------------------------------------------------------------------
# PATCH /api/notebooks/{nb_id}
# ---------------------------------------------------------------------------


def test_patch_notebook_name(isolated_api):
    client = isolated_api.client
    h = isolated_api.headers

    nb_id = client.post("/api/notebooks", json={"name": "Old Name", "color": "#aabbcc"}, headers=h).json()["id"]

    r = client.patch(f"/api/notebooks/{nb_id}", json={"name": "New Name"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "New Name"


def test_patch_notebook_color(isolated_api):
    client = isolated_api.client
    h = isolated_api.headers

    nb_id = client.post("/api/notebooks", json={"name": "ColorTest", "color": "#000000"}, headers=h).json()["id"]

    r = client.patch(f"/api/notebooks/{nb_id}", json={"color": "#ffffff"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["color"] == "#ffffff"


def test_patch_nonexistent_notebook_returns_404(isolated_api):
    r = isolated_api.client.patch(
        "/api/notebooks/nonexistent-id",
        json={"name": "Ghost"},
        headers=isolated_api.headers,
    )
    assert r.status_code == 404, r.text


def test_patch_no_fields_returns_400(isolated_api):
    client = isolated_api.client
    h = isolated_api.headers

    nb_id = client.post("/api/notebooks", json={"name": "EmptyPatch", "color": "#123456"}, headers=h).json()["id"]

    r = client.patch(f"/api/notebooks/{nb_id}", json={}, headers=h)
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# DELETE /api/notebooks/{nb_id}
# ---------------------------------------------------------------------------


def test_delete_non_default_notebook(isolated_api):
    client = isolated_api.client
    h = isolated_api.headers

    nb_id = client.post("/api/notebooks", json={"name": "ToDelete", "color": "#ff0000"}, headers=h).json()["id"]

    r = client.delete(f"/api/notebooks/{nb_id}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == nb_id
    assert "cardsReassigned" in body


def test_delete_default_notebook_fails(isolated_api):
    """Deleting the default notebook must return 400."""
    r = isolated_api.client.delete("/api/notebooks/default", headers=isolated_api.headers)
    assert r.status_code == 400, r.text


def test_delete_nonexistent_notebook_fails(isolated_api):
    """Deleting a notebook that never existed returns 400 (not found)."""
    r = isolated_api.client.delete("/api/notebooks/does-not-exist", headers=isolated_api.headers)
    assert r.status_code == 400, r.text


def test_delete_idempotent(isolated_api):
    """Second delete on an already-deleted notebook returns 200 with cardsReassigned=0.

    store.delete returns None when notebook is already soft-deleted;
    the router treats None as idempotent success (not False → no 400).
    """
    client = isolated_api.client
    h = isolated_api.headers

    nb_id = client.post("/api/notebooks", json={"name": "Idempotent", "color": "#abc123"}, headers=h).json()["id"]

    r1 = client.delete(f"/api/notebooks/{nb_id}", headers=h)
    assert r1.status_code == 200, r1.text

    r2 = client.delete(f"/api/notebooks/{nb_id}", headers=h)
    assert r2.status_code == 200, r2.text
    assert r2.json()["deleted"] == nb_id
    assert r2.json()["cardsReassigned"] == 0
