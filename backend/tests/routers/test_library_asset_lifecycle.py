"""Regression tests for library asset access across book lifecycle changes."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.deps as deps_mod
import kg.routers.library as library_router
from conftest import TEST_JWT_SECRET, _swap_settings, make_jwt
from kg.api import app
from kg.settings import KGSettings


@pytest.fixture()
def isolated_api(tmp_path):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    (data_dir / "users.json").write_text(json.dumps({user_id: {"config": {}}}))

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
            headers={"Authorization": f"Bearer {make_jwt(user_id)}"},
            data_dir=data_dir,
        )
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


def _seed_book(api):
    response = api.client.post(
        "/api/library/books",
        json={"client_book_id": "asset-lifecycle-1", "title": "Book", "format": "epub"},
        headers=api.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_deleted_book_asset_is_not_downloadable(isolated_api, monkeypatch):
    """A soft-deleted book must not mint a fresh presigned asset URL."""
    _swap_settings(
        KGSettings(
            data_dir=isolated_api.data_dir,
            jwt_secret=TEST_JWT_SECRET,
            library_bucket="kg-library-test",
        )
    )

    class FakeS3Client:
        def generate_presigned_url(self, operation, *, Params, ExpiresIn):
            return "https://storage.test/presigned"

    monkeypatch.setattr(library_router, "_library_s3_client", lambda settings: FakeS3Client())

    book_id = _seed_book(isolated_api)
    uploaded = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": 10},
        headers=isolated_api.headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["storage"] == "object"

    deleted = isolated_api.client.delete(f"/api/library/books/{book_id}", headers=isolated_api.headers)
    assert deleted.status_code == 200, deleted.text

    response = isolated_api.client.get(
        f"/api/library/books/{book_id}/asset",
        headers=isolated_api.headers,
        follow_redirects=False,
    )
    assert response.status_code == 404, response.text
