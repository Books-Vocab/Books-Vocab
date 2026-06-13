"""Integration tests for DELETE /api/library/books/{id} soft-delete.

Soft-delete sets is_deleted on the per-user LibraryBook row (library.db, the
SAME store create/list/patch use). Mirrors notebook soft-delete semantics:
idempotent on an already deleted book, 404 on an unknown id.
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
    (data_dir / "users.json").write_text(json.dumps({user_id: {"config": {}}}))

    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users

    _swap_settings(KGSettings(data_dir=data_dir, jwt_secret=TEST_JWT_SECRET))
    try:
        api_mod._USER_LOCKS.clear()
        deps_mod._USER_LOCKS_MUTEX = None
        yield SimpleNamespace(
            client=TestClient(app, raise_server_exceptions=False),
            user_id=user_id,
            headers=headers,
            data_dir=data_dir,
        )
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


def _seed_book(api, client_book_id: str = "book-1", title: str = "Pride and Prejudice"):
    """Seed a book through the real POST route (LibraryStore / library.db).

    Returns the server-assigned book id. Seeding via the route guarantees every
    test exercises the same store production reads/writes — no bypass.
    """
    resp = api.client.post(
        "/api/library/books",
        json={"client_book_id": client_book_id, "title": title, "format": "epub"},
        headers=api.headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _fetch_book(api, book_id: str):
    """Return the book row (incl. deleted) from the real store via GET, or None."""
    resp = api.client.get("/api/library/books", headers=api.headers)
    assert resp.status_code == 200, resp.text
    for b in resp.json():
        if b["id"] == book_id:
            return b
    return None


def test_soft_delete_book(isolated_api):
    book_id = _seed_book(isolated_api)
    r = isolated_api.client.delete(f"/api/library/books/{book_id}", headers=isolated_api.headers)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == book_id

    # Verify the row is flagged is_deleted, not physically removed.
    book = _fetch_book(isolated_api, book_id)
    assert book is not None
    assert book["is_deleted"] is True


def test_soft_delete_is_idempotent(isolated_api):
    book_id = _seed_book(isolated_api)
    first = isolated_api.client.delete(f"/api/library/books/{book_id}", headers=isolated_api.headers)
    second = isolated_api.client.delete(f"/api/library/books/{book_id}", headers=isolated_api.headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text


def test_delete_unknown_book_returns_404(isolated_api):
    r = isolated_api.client.delete("/api/library/books/nope", headers=isolated_api.headers)
    assert r.status_code == 404, r.text


def test_delete_requires_auth(isolated_api):
    book_id = _seed_book(isolated_api)
    r = isolated_api.client.delete(f"/api/library/books/{book_id}")
    assert r.status_code == 401, r.text


def test_create_then_delete_roundtrip(isolated_api):
    """A book created via POST must be deletable via DELETE in the SAME store.

    Regression guard: create writes to LibraryStore (library.db); DELETE must
    read/write the same store, not a separate orphan BookStore (books.db).
    """
    create = isolated_api.client.post(
        "/api/library/books",
        json={"client_book_id": "rt-1", "title": "Round Trip", "format": "epub"},
        headers=isolated_api.headers,
    )
    assert create.status_code == 201, create.text
    book_id = create.json()["id"]

    delete = isolated_api.client.delete(
        f"/api/library/books/{book_id}", headers=isolated_api.headers
    )
    assert delete.status_code == 200, delete.text
    assert delete.json()["deleted"] == book_id

    # The book must be flagged is_deleted in the store the create wrote to.
    listed = isolated_api.client.get("/api/library/books", headers=isolated_api.headers)
    assert listed.status_code == 200, listed.text
    by_id = {b["id"]: b for b in listed.json()}
    assert book_id in by_id, "created book vanished from its own store"
    assert by_id[book_id]["is_deleted"] is True
