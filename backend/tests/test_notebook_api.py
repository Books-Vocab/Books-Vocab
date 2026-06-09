"""Integration tests for notebook CRUD HTTP endpoints.

Covers: GET /api/notebooks, POST /api/notebooks, PATCH /api/notebooks/{nb_id},
DELETE /api/notebooks/{nb_id}.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.deps as deps_mod
from conftest import TEST_JWT_SECRET, _swap_settings, make_jwt
from kg.api import app
from kg.settings import KGSettings


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
    """Deleting a notebook should hard-delete its cards, not reassign to default."""
    client = isolated_api.client
    h = isolated_api.headers

    nb_id = client.post("/api/notebooks", json={"name": "ToDelete", "color": "#ff0000"}, headers=h).json()["id"]

    # Add vocab cards to this notebook
    client.post("/api/vocab", json=[{"word": "apple", "translation": "蘋果"}], params={"notebook_id": nb_id}, headers=h)
    client.post("/api/vocab", json=[{"word": "banana", "translation": "香蕉"}], params={"notebook_id": nb_id}, headers=h)

    r = client.delete(f"/api/notebooks/{nb_id}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == nb_id
    assert "cardsDeleted" in body
    assert body["cardsDeleted"] == 2
    # Cards must NOT appear in default notebook
    r_vocab = client.get("/api/vocab", params={"notebook_id": "default"}, headers=h)
    default_words = [c["content"] for c in r_vocab.json()]
    assert "apple" not in default_words
    assert "banana" not in default_words


def test_delete_notebook_removes_all_artifact_kinds(isolated_api):
    """delete_notebook must remove a file for EVERY kind in NOTEBOOK_FILE_SPECS
    (plus its .bak/.tmp siblings). It derives filenames from the ops_shared SoT,
    so adding a new per-notebook artifact kind cannot silently orphan a file."""
    from kg.ops_shared import notebook_files

    client = isolated_api.client
    h = isolated_api.headers
    nb_id = client.post("/api/notebooks", json={"name": "Artifacts"}, headers=h).json()["id"]

    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    created = []
    for path in notebook_files(user_dir, nb_id).values():
        for suffix in ("", ".bak", ".tmp"):
            sibling = path.with_name(path.name + suffix)
            sibling.write_text("x")
            created.append(sibling)
    assert all(f.exists() for f in created)

    r = client.delete(f"/api/notebooks/{nb_id}", headers=h)
    assert r.status_code == 200, r.text

    leftover = [str(f) for f in created if f.exists()]
    assert not leftover, f"orphan artifacts left after delete: {leftover}"


def test_delete_default_notebook_fails(isolated_api):
    """Deleting the default notebook must return 400."""
    r = isolated_api.client.delete("/api/notebooks/default", headers=isolated_api.headers)
    assert r.status_code == 400, r.text


def test_delete_nonexistent_notebook_fails(isolated_api):
    """Deleting a notebook that never existed returns 400 (not found)."""
    r = isolated_api.client.delete("/api/notebooks/does-not-exist", headers=isolated_api.headers)
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# cover_pattern
# ---------------------------------------------------------------------------


def test_create_notebook_with_cover_pattern(isolated_api):
    r = isolated_api.client.post(
        "/api/notebooks",
        json={"name": "Patterned", "cover_pattern": "dots"},
        headers=isolated_api.headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["coverPattern"] == "dots"


def test_create_notebook_invalid_cover_pattern_returns_422(isolated_api):
    r = isolated_api.client.post(
        "/api/notebooks",
        json={"name": "BadPattern", "cover_pattern": "zigzag"},
        headers=isolated_api.headers,
    )
    assert r.status_code == 422, r.text
    assert "detail" in r.json()


def test_update_notebook_cover_pattern(isolated_api):
    client = isolated_api.client
    h = isolated_api.headers
    nb_id = client.post("/api/notebooks", json={"name": "Pat"}, headers=h).json()["id"]

    r = client.patch(f"/api/notebooks/{nb_id}", json={"cover_pattern": "waves"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["coverPattern"] == "waves"

    r = client.patch(f"/api/notebooks/{nb_id}", json={"cover_pattern": ""}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["coverPattern"] is None


def test_update_notebook_cover_pattern_preserved_when_not_sent(isolated_api):
    client = isolated_api.client
    h = isolated_api.headers
    nb_id = client.post("/api/notebooks", json={"name": "Keep", "cover_pattern": "dots"}, headers=h).json()["id"]

    r = client.patch(f"/api/notebooks/{nb_id}", json={"name": "Renamed"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["coverPattern"] == "dots"


# ---------------------------------------------------------------------------
# Lifecycle: duplicate name / delete-with-cards / rename id stability
# ---------------------------------------------------------------------------


def test_create_notebook_duplicate_name(isolated_api):
    """Two notebooks with the same name for one user.

    Contract: the API does NOT enforce name uniqueness or dedup — each POST
    creates a distinct notebook with its own id. Both appear in the listing.
    """
    client = isolated_api.client
    h = isolated_api.headers

    r1 = client.post("/api/notebooks", json={"name": "Duplicate", "color": "#111111"}, headers=h)
    r2 = client.post("/api/notebooks", json={"name": "Duplicate", "color": "#222222"}, headers=h)
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text

    id1, id2 = r1.json()["id"], r2.json()["id"]
    assert id1 != id2, "duplicate-named notebooks must still get distinct ids"

    r_list = client.get("/api/notebooks", headers=h)
    listed = r_list.json()
    dup_named = [nb for nb in listed if nb["name"] == "Duplicate"]
    assert len(dup_named) == 2
    assert {id1, id2}.issubset(_nb_ids(listed))


def test_delete_notebook_with_cards(isolated_api):
    """Deleting a notebook holding cards cascades a soft-delete to those cards.

    Contract: delete is NOT blocked by card presence; cardsDeleted reflects the
    cascade count and the cards no longer surface under their old notebook.
    """
    client = isolated_api.client
    h = isolated_api.headers

    nb_id = client.post(
        "/api/notebooks", json={"name": "HasCards", "color": "#abcdef"}, headers=h
    ).json()["id"]

    client.post(
        "/api/vocab", json=[{"word": "cat", "translation": "貓"}],
        params={"notebook_id": nb_id}, headers=h,
    )
    client.post(
        "/api/vocab", json=[{"word": "dog", "translation": "狗"}],
        params={"notebook_id": nb_id}, headers=h,
    )

    r_before = client.get("/api/vocab", params={"notebook_id": nb_id}, headers=h)
    assert len(r_before.json()) == 2, "cards should exist before delete"

    r_del = client.delete(f"/api/notebooks/{nb_id}", headers=h)
    assert r_del.status_code == 200, r_del.text
    assert r_del.json()["cardsDeleted"] == 2, "delete must cascade to all cards"

    # Cards are hard-deleted with the notebook, not reassigned to default.
    r_default = client.get("/api/vocab", params={"notebook_id": "default"}, headers=h)
    default_words = [c["content"] for c in r_default.json()]
    assert "cat" not in default_words
    assert "dog" not in default_words


def test_rename_notebook_keeps_id_stable(isolated_api):
    """Renaming a notebook mutates the name in place but keeps its id.

    Contract: the id is the primary key — a rename must not break a client's
    cached activeNotebookId. The renamed notebook still appears in the listing
    under the same id.
    """
    client = isolated_api.client
    h = isolated_api.headers

    r_create = client.post(
        "/api/notebooks", json={"name": "Before", "color": "#0a0a0a"}, headers=h
    )
    nb_id = r_create.json()["id"]

    r_patch = client.patch(f"/api/notebooks/{nb_id}", json={"name": "After"}, headers=h)
    assert r_patch.status_code == 200, r_patch.text
    assert r_patch.json()["id"] == nb_id, "rename must not change the id"
    assert r_patch.json()["name"] == "After"

    r_list = client.get("/api/notebooks", headers=h)
    matched = [nb for nb in r_list.json() if nb["id"] == nb_id]
    assert len(matched) == 1
    assert matched[0]["name"] == "After"
    assert nb_id in _nb_ids(r_list.json())


def test_delete_idempotent(isolated_api):
    """Second delete on an already-deleted notebook returns 200 with cardsDeleted=0.

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
    assert r2.json()["cardsDeleted"] == 0
