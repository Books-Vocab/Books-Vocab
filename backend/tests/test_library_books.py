"""Integration tests for DELETE /api/library/books/{id} soft-delete.

Soft-delete sets is_deleted on the per-user Book row (column exists on the
model). Mirrors notebook soft-delete semantics: idempotent on an already
deleted book, 404 on an unknown id.
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
from kg.book_store import BookStore
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


def _seed_book(api, book_id: str = "book-1", title: str = "Pride and Prejudice"):
    store = BookStore(api.data_dir / "users" / api.user_id / "books.db")
    book = store.add(book_id=book_id, title=title)
    store.close()
    return book.id


def test_soft_delete_book(isolated_api):
    book_id = _seed_book(isolated_api)
    r = isolated_api.client.delete(f"/api/library/books/{book_id}", headers=isolated_api.headers)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == book_id

    # Verify the row is flagged is_deleted, not physically removed.
    store = BookStore(isolated_api.data_dir / "users" / isolated_api.user_id / "books.db")
    book = store.get(book_id)
    store.close()
    assert book is not None
    assert book.is_deleted is True


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
