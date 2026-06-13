"""Contract tests for book asset endpoints (Architecture PR #7).

POST /api/library/books/{book_id}/asset-upload  -> request an object-storage
upload target OR declare a local-only asset.
GET  /api/library/books/{book_id}/asset         -> download / redirect to the
authorized asset URL.

Storage backend is env-gated exactly like podcast media: when `library_bucket`
is configured, the upload endpoint mints a presigned PUT target and download
redirects (307) to a presigned GET; when unset (dev / local-only), the asset is
declared local-only and download returns 409 (not server-hosted).

All write/read paths run through the SAME per-user LibraryStore (library.db)
that create/list/patch/position/delete use — no bypass store.
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
    resp = api.client.post(
        "/api/library/books",
        json={"client_book_id": client_book_id, "title": title, "format": "epub"},
        headers=api.headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# asset-upload
# ---------------------------------------------------------------------------


def test_asset_upload_local_only_when_no_bucket(isolated_api):
    """No bucket configured -> server declares the asset local-only (no URL)."""
    book_id = _seed_book(isolated_api)
    r = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": 1024},
        headers=isolated_api.headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["storage"] == "local"
    assert body["upload_url"] is None
    assert body["book_id"] == book_id


def test_asset_upload_respects_explicit_local_only_flag(isolated_api):
    book_id = _seed_book(isolated_api)
    r = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": 2048, "local_only": True},
        headers=isolated_api.headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["storage"] == "local"
    assert r.json()["upload_url"] is None


def test_asset_upload_unknown_book_returns_404(isolated_api):
    r = isolated_api.client.post(
        "/api/library/books/nope/asset-upload",
        json={"format": "epub", "byte_size": 10},
        headers=isolated_api.headers,
    )
    assert r.status_code == 404, r.text


def test_asset_upload_requires_auth(isolated_api):
    book_id = _seed_book(isolated_api)
    r = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": 10},
    )
    assert r.status_code == 401, r.text


def test_asset_upload_rejects_oversize_asset(isolated_api):
    """Quota policy: an absurdly large asset is rejected with 400."""
    book_id = _seed_book(isolated_api)
    huge = 5 * 1024 * 1024 * 1024  # 5 GiB, well over any per-asset cap
    r = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": huge},
        headers=isolated_api.headers,
    )
    assert r.status_code == 400, r.text


def test_asset_upload_object_storage_when_bucket_configured(isolated_api):
    """With a bucket configured, the endpoint mints a presigned PUT target and
    records the object key on the book row."""
    _swap_settings(
        KGSettings(
            data_dir=isolated_api.data_dir,
            jwt_secret=TEST_JWT_SECRET,
            library_bucket="kg-library-test",
        )
    )
    book_id = _seed_book(isolated_api, client_book_id="obj-1")
    r = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": 4096},
        headers=isolated_api.headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["storage"] == "object"
    assert isinstance(body["upload_url"], str) and body["upload_url"]
    assert body["object_key"] and book_id in body["object_key"]


# ---------------------------------------------------------------------------
# asset download
# ---------------------------------------------------------------------------


def test_asset_download_local_only_returns_409(isolated_api):
    """A book whose asset is local-only is not server-hosted -> 409."""
    book_id = _seed_book(isolated_api)
    # Declare local-only first.
    isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": 10, "local_only": True},
        headers=isolated_api.headers,
    )
    r = isolated_api.client.get(
        f"/api/library/books/{book_id}/asset", headers=isolated_api.headers
    )
    assert r.status_code == 409, r.text


def test_asset_download_unknown_book_returns_404(isolated_api):
    r = isolated_api.client.get(
        "/api/library/books/nope/asset", headers=isolated_api.headers
    )
    assert r.status_code == 404, r.text


def test_asset_download_requires_auth(isolated_api):
    book_id = _seed_book(isolated_api)
    r = isolated_api.client.get(f"/api/library/books/{book_id}/asset")
    assert r.status_code == 401, r.text


def test_asset_download_redirects_to_presigned_url_when_object_stored(isolated_api):
    """After an object-storage upload is registered, download issues a 307 to a
    presigned GET URL."""
    _swap_settings(
        KGSettings(
            data_dir=isolated_api.data_dir,
            jwt_secret=TEST_JWT_SECRET,
            library_bucket="kg-library-test",
        )
    )
    book_id = _seed_book(isolated_api, client_book_id="obj-dl-1")
    up = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": 4096},
        headers=isolated_api.headers,
    )
    assert up.status_code == 200, up.text
    r = isolated_api.client.get(
        f"/api/library/books/{book_id}/asset",
        headers=isolated_api.headers,
        follow_redirects=False,
    )
    assert r.status_code == 307, r.text
    assert r.headers["location"]
