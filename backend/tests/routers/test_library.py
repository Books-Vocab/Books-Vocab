"""Contract tests for library router.

Covers: GET /api/library/books, POST /api/library/books,
PATCH /api/library/books/{book_id}, PUT /api/library/books/{book_id}/position.
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
    users_file.write_text(json.dumps({user_id: {"config": {}}}))

    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users

    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
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


def _create_book(client, headers, title="Test Book", client_book_id=None):
    payload = {
        "client_book_id": client_book_id or f"cbid-{uuid.uuid4().hex[:8]}",
        "title": title,
        "author": "Test Author",
        "language": "en",
        "format": "epub",
    }
    resp = client.post("/api/library/books", json=payload, headers=headers)
    assert resp.status_code == 201
    return resp.json()


class TestListBooks:
    def test_empty_list(self, isolated_api):
        resp = isolated_api.client.get("/api/library/books", headers=isolated_api.headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_returns_created_books(self, isolated_api):
        b1 = _create_book(isolated_api.client, isolated_api.headers, "Book A")
        b2 = _create_book(isolated_api.client, isolated_api.headers, "Book B")
        resp = isolated_api.client.get("/api/library/books", headers=isolated_api.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        titles = {d["title"] for d in data}
        assert titles == {"Book A", "Book B"}

    def test_list_with_since_filter(self, isolated_api):
        b1 = _create_book(isolated_api.client, isolated_api.headers, "Book A")
        since = b1["updated_at"]
        _create_book(isolated_api.client, isolated_api.headers, "Book B")
        resp = isolated_api.client.get(
            "/api/library/books", headers=isolated_api.headers, params={"since": since}
        )
        assert resp.status_code == 200
        data = resp.json()
        # Only Book B has updated_at > since (Book A's updated_at == since)
        assert len(data) >= 1
        assert any(d["title"] == "Book B" for d in data)

    def test_list_requires_auth(self, isolated_api):
        resp = isolated_api.client.get("/api/library/books")
        assert resp.status_code == 401


class TestCreateBook:
    def test_create_book(self, isolated_api):
        payload = {
            "client_book_id": "my-book-1",
            "title": "Atomic Habits",
            "author": "James Clear",
            "language": "en",
            "format": "epub",
        }
        resp = isolated_api.client.post("/api/library/books", json=payload, headers=isolated_api.headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Atomic Habits"
        assert data["author"] == "James Clear"
        assert data["client_book_id"] == "my-book-1"
        assert data["id"]
        assert "is_deleted" in data
        assert data["is_deleted"] is False

    def test_idempotent_via_client_book_id(self, isolated_api):
        payload = {
            "client_book_id": "same-id",
            "title": "First",
            "author": "A",
        }
        r1 = isolated_api.client.post("/api/library/books", json=payload, headers=isolated_api.headers)
        assert r1.status_code == 201
        id1 = r1.json()["id"]

        payload2 = {
            "client_book_id": "same-id",
            "title": "Second",
            "author": "B",
        }
        r2 = isolated_api.client.post("/api/library/books", json=payload2, headers=isolated_api.headers)
        assert r2.status_code == 201
        data2 = r2.json()
        # Should return existing book, not create new
        assert data2["id"] == id1
        assert data2["title"] == "First"  # Original title preserved

    def test_create_requires_auth(self, isolated_api):
        resp = isolated_api.client.post("/api/library/books", json={"client_book_id": "x", "title": "X"})
        assert resp.status_code == 401


class TestUpdateBook:
    def test_update_title_and_author(self, isolated_api):
        b = _create_book(isolated_api.client, isolated_api.headers, "Old Title")
        book_id = b["id"]
        resp = isolated_api.client.patch(
            f"/api/library/books/{book_id}",
            json={"title": "New Title", "author": "New Author"},
            headers=isolated_api.headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "New Title"
        assert data["author"] == "New Author"
        assert data["id"] == book_id

    def test_update_notebook_binding(self, isolated_api):
        b = _create_book(isolated_api.client, isolated_api.headers, "Book")
        book_id = b["id"]
        resp = isolated_api.client.patch(
            f"/api/library/books/{book_id}",
            json={"notebook_id": "nb-123"},
            headers=isolated_api.headers,
        )
        assert resp.status_code == 200
        assert resp.json()["notebook_id"] == "nb-123"

    def test_update_no_fields_raises_400(self, isolated_api):
        b = _create_book(isolated_api.client, isolated_api.headers, "Book")
        resp = isolated_api.client.patch(
            f"/api/library/books/{b['id']}",
            json={},
            headers=isolated_api.headers,
        )
        assert resp.status_code == 400

    def test_update_not_found(self, isolated_api):
        resp = isolated_api.client.patch(
            "/api/library/books/nonexistent",
            json={"title": "X"},
            headers=isolated_api.headers,
        )
        assert resp.status_code == 404

    def test_update_requires_auth(self, isolated_api):
        resp = isolated_api.client.patch("/api/library/books/abc", json={"title": "X"})
        assert resp.status_code == 401


class TestPutPosition:
    def test_put_position(self, isolated_api):
        b = _create_book(isolated_api.client, isolated_api.headers, "Book")
        book_id = b["id"]
        resp = isolated_api.client.put(
            f"/api/library/books/{book_id}/position",
            json={"locator": "epubcfi(/6/2[id4]!/4/1:0)", "progression": 0.42, "updated_at": "2026-06-13T10:00:00Z"},
            headers=isolated_api.headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["locator"] == "epubcfi(/6/2[id4]!/4/1:0)"
        assert data["progression"] == 0.42
        assert data["position_updated_at"] == "2026-06-13T10:00:00Z"

    def test_put_position_not_found(self, isolated_api):
        resp = isolated_api.client.put(
            "/api/library/books/nonexistent/position",
            json={"locator": "x", "progression": 0.1, "updated_at": "2026-06-13T10:00:00Z"},
            headers=isolated_api.headers,
        )
        assert resp.status_code == 404

    def test_put_position_requires_auth(self, isolated_api):
        resp = isolated_api.client.put(
            "/api/library/books/abc/position",
            json={"locator": "x", "progression": 0.1, "updated_at": "2026-06-13T10:00:00Z"},
        )
        assert resp.status_code == 401
