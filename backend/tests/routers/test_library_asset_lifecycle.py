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


@pytest.mark.parametrize(
    "library_bucket",
    [None, "kg-library-test"],
    ids=["local", "configured-bucket"],
)
@pytest.mark.parametrize(
    "byte_size",
    [10, 5 * 1024 * 1024 * 1024],
    ids=["within-quota", "over-quota"],
)
def test_deleted_book_asset_upload_is_rejected_before_side_effects(
    isolated_api, monkeypatch, library_bucket, byte_size
):
    """A tombstoned book cannot enter either asset-upload path."""
    _swap_settings(
        KGSettings(
            data_dir=isolated_api.data_dir,
            jwt_secret=TEST_JWT_SECRET,
            library_bucket=library_bucket,
        )
    )

    presign_calls = []

    class FakeS3Client:
        def generate_presigned_url(self, operation, *, Params, ExpiresIn):
            presign_calls.append((operation, Params, ExpiresIn))
            return "https://storage.test/presigned"

    monkeypatch.setattr(library_router, "_library_s3_client", lambda settings: FakeS3Client())

    book_id = _seed_book(isolated_api)
    deleted = isolated_api.client.delete(f"/api/library/books/{book_id}", headers=isolated_api.headers)
    assert deleted.status_code == 200, deleted.text

    store = library_router._library_store(isolated_api.data_dir / "users" / isolated_api.user_id)
    before = store.get(book_id)
    assert before is not None and before.is_deleted
    before_asset = (
        before.asset_storage,
        before.asset_object_key,
        before.asset_byte_size,
        before.asset_sha256,
        before.updated_at,
    )

    response = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": byte_size},
        headers=isolated_api.headers,
    )

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "NotFoundError"
    assert presign_calls == []

    after = store.get(book_id)
    assert after is not None
    assert (
        after.asset_storage,
        after.asset_object_key,
        after.asset_byte_size,
        after.asset_sha256,
        after.updated_at,
    ) == before_asset


# ---------------------------------------------------------------------------
# Upload confirmation + object cleanup (Issues #2527, #2528)
# ---------------------------------------------------------------------------


class _MissingObject(Exception):
    response = {"Error": {"Code": "404"}}


class _RecordingS3:
    def __init__(self, existing=None, delete_error=None):
        self.existing = dict.fromkeys(existing or (), 10)
        self.deleted = []
        self.delete_error = delete_error

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        return "https://storage.test/presigned"

    def head_object(self, *, Bucket, Key):
        if Key not in self.existing:
            raise _MissingObject()
        return {"ContentLength": self.existing[Key]}

    def delete_object(self, *, Bucket, Key):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append(Key)


def _bucket_api(api, monkeypatch, s3):
    _swap_settings(KGSettings(data_dir=api.data_dir, jwt_secret=TEST_JWT_SECRET, library_bucket="kg-library-test"))
    # The request path passes fast=True; the fake client ignores it.
    monkeypatch.setattr(library_router, "_library_s3_client", lambda settings, *, fast=False: s3)


def _request_upload(api, book_id, fmt="epub", **extra):
    return api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": fmt, "byte_size": 10, **extra},
        headers=api.headers,
    )


def _download(api, book_id):
    return api.client.get(f"/api/library/books/{book_id}/asset", headers=api.headers, follow_redirects=False)


def test_download_before_bytes_uploaded_is_conflict(isolated_api, monkeypatch):
    """#2527: minting an upload URL must not make the asset downloadable."""
    s3 = _RecordingS3()
    _bucket_api(isolated_api, monkeypatch, s3)
    book_id = _seed_book(isolated_api)
    key = _request_upload(isolated_api, book_id).json()["object_key"]

    assert _download(isolated_api, book_id).status_code == 409
    s3.existing[key] = 10
    assert _download(isolated_api, book_id).status_code == 307


def test_delete_book_removes_stored_object(isolated_api, monkeypatch):
    """#2528: soft-deleting a book deletes its S3 object."""
    s3 = _RecordingS3(existing=())
    _bucket_api(isolated_api, monkeypatch, s3)
    book_id = _seed_book(isolated_api)
    key = _request_upload(isolated_api, book_id).json()["object_key"]

    assert isolated_api.client.delete(f"/api/library/books/{book_id}", headers=isolated_api.headers).status_code == 200
    assert s3.deleted == [key]


def test_delete_book_succeeds_when_object_delete_fails(isolated_api, monkeypatch):
    """Object cleanup is best effort; the key stays recorded for account erasure."""
    s3 = _RecordingS3(delete_error=RuntimeError("s3 down"))
    _bucket_api(isolated_api, monkeypatch, s3)
    book_id = _seed_book(isolated_api)
    key = _request_upload(isolated_api, book_id).json()["object_key"]

    assert isolated_api.client.delete(f"/api/library/books/{book_id}", headers=isolated_api.headers).status_code == 200
    store = library_router._library_store(isolated_api.data_dir / "users" / isolated_api.user_id)
    assert store.get(book_id).asset_object_key == key


class _AlreadyGone(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


def test_delete_book_clears_ledger_when_object_is_already_gone(isolated_api, monkeypatch):
    """An object already missing is the desired end state (same as account erasure):
    the ledger entry must be cleared, not left to be retried forever."""
    s3 = _RecordingS3(delete_error=_AlreadyGone())
    _bucket_api(isolated_api, monkeypatch, s3)
    book_id = _seed_book(isolated_api)
    _request_upload(isolated_api, book_id)

    assert isolated_api.client.delete(f"/api/library/books/{book_id}", headers=isolated_api.headers).status_code == 200
    store = library_router._library_store(isolated_api.data_dir / "users" / isolated_api.user_id)
    assert store.pending_object_keys() == []


def test_reupload_with_new_format_deletes_prior_object(isolated_api, monkeypatch):
    """#2528: replacing the asset must not orphan the previous object key."""
    s3 = _RecordingS3()
    _bucket_api(isolated_api, monkeypatch, s3)
    book_id = _seed_book(isolated_api)
    old = _request_upload(isolated_api, book_id, "epub").json()["object_key"]
    new = _request_upload(isolated_api, book_id, "pdf").json()["object_key"]

    assert old != new
    assert s3.deleted == [old]


def test_reupload_same_key_keeps_object(isolated_api, monkeypatch):
    s3 = _RecordingS3()
    _bucket_api(isolated_api, monkeypatch, s3)
    book_id = _seed_book(isolated_api)
    _request_upload(isolated_api, book_id, "epub")
    _request_upload(isolated_api, book_id, "epub")
    assert s3.deleted == []


def test_switching_to_local_only_deletes_prior_object(isolated_api, monkeypatch):
    s3 = _RecordingS3()
    _bucket_api(isolated_api, monkeypatch, s3)
    book_id = _seed_book(isolated_api)
    old = _request_upload(isolated_api, book_id).json()["object_key"]
    assert _request_upload(isolated_api, book_id, local_only=True).json()["storage"] == "local"
    assert s3.deleted == [old]


def test_failed_same_key_reupload_with_different_size_is_conflict(isolated_api, monkeypatch):
    """#2527: stale bytes under a reused key must not be served against new metadata."""
    s3 = _RecordingS3()
    _bucket_api(isolated_api, monkeypatch, s3)
    book_id = _seed_book(isolated_api)
    key = _request_upload(isolated_api, book_id).json()["object_key"]
    s3.existing[key] = 10
    assert _download(isolated_api, book_id).status_code == 307

    # Re-upload declares a different size but the new bytes never land.
    assert _request_upload(isolated_api, book_id, byte_size=99).status_code == 200
    assert _download(isolated_api, book_id).status_code == 409
