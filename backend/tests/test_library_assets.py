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


def _set_fake_object_storage_credentials(monkeypatch) -> None:
    """Keep presign tests independent of a developer or CI AWS session."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "kg-test-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "kg-test-secret-key")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "kg-test-session-token")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


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


def test_asset_upload_object_storage_when_bucket_configured(isolated_api, monkeypatch):
    """With a bucket configured, the endpoint mints a presigned PUT target and
    records the object key on the book row."""
    _set_fake_object_storage_credentials(monkeypatch)
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
    r = isolated_api.client.get(f"/api/library/books/{book_id}/asset", headers=isolated_api.headers)
    assert r.status_code == 409, r.text


def test_asset_download_unknown_book_returns_404(isolated_api):
    r = isolated_api.client.get("/api/library/books/nope/asset", headers=isolated_api.headers)
    assert r.status_code == 404, r.text


def test_asset_download_requires_auth(isolated_api):
    book_id = _seed_book(isolated_api)
    r = isolated_api.client.get(f"/api/library/books/{book_id}/asset")
    assert r.status_code == 401, r.text


def test_asset_download_redirects_to_presigned_url_when_object_stored(isolated_api, monkeypatch):
    """After the object is actually uploaded, download issues a 307 to a
    presigned GET URL."""
    _set_fake_object_storage_credentials(monkeypatch)
    _swap_settings(
        KGSettings(
            data_dir=isolated_api.data_dir,
            jwt_secret=TEST_JWT_SECRET,
            library_bucket="kg-library-test",
        )
    )
    import kg.routers.library as library_router

    class FakeS3Client:
        def generate_presigned_url(self, operation, *, Params, ExpiresIn):
            return "https://storage.test/presigned"

        def head_object(self, *, Bucket, Key):
            return {"ContentLength": 4096}

    monkeypatch.setattr(library_router, "_library_s3_client", lambda settings: FakeS3Client())
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


# ---------------------------------------------------------------------------
# format allow-list at the request boundary (Issue #1187)
# ---------------------------------------------------------------------------

_LEGAL_FORMATS = ["epub", "pdf", "txt", "md"]
_ILLEGAL_FORMATS = ["exe", "EPUB", "docx", ""]


@pytest.mark.parametrize("fmt", _ILLEGAL_FORMATS)
def test_book_create_rejects_unsupported_format(isolated_api, fmt):
    r = isolated_api.client.post(
        "/api/library/books",
        json={"client_book_id": "bad-1", "title": "Bad", "format": fmt},
        headers=isolated_api.headers,
    )
    assert r.status_code == 422, r.text
    listing = isolated_api.client.get("/api/library/books", headers=isolated_api.headers)
    assert listing.status_code == 200, listing.text
    assert "bad-1" not in json.dumps(listing.json())


@pytest.mark.parametrize("fmt", _ILLEGAL_FORMATS)
def test_book_update_rejects_unsupported_format(isolated_api, fmt):
    book_id = _seed_book(isolated_api)
    r = isolated_api.client.patch(
        f"/api/library/books/{book_id}",
        json={"format": fmt},
        headers=isolated_api.headers,
    )
    assert r.status_code == 422, r.text
    listing = isolated_api.client.get("/api/library/books", headers=isolated_api.headers)
    assert [b["format"] for b in listing.json()] == ["epub"]


@pytest.mark.parametrize("fmt", _ILLEGAL_FORMATS)
def test_asset_upload_rejects_unsupported_format_without_metadata(isolated_api, fmt):
    book_id = _seed_book(isolated_api)
    r = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": fmt, "byte_size": 10},
        headers=isolated_api.headers,
    )
    assert r.status_code == 422, r.text
    dl = isolated_api.client.get(f"/api/library/books/{book_id}/asset", headers=isolated_api.headers)
    assert dl.status_code == 409, dl.text  # no asset metadata was recorded


@pytest.mark.parametrize("fmt", _LEGAL_FORMATS)
def test_legal_formats_succeed_on_all_three_models(isolated_api, fmt):
    created = isolated_api.client.post(
        "/api/library/books",
        json={"client_book_id": f"ok-{fmt}", "title": "Ok", "format": fmt},
        headers=isolated_api.headers,
    )
    assert created.status_code == 201, created.text
    book_id = created.json()["id"]
    patched = isolated_api.client.patch(
        f"/api/library/books/{book_id}",
        json={"format": fmt},
        headers=isolated_api.headers,
    )
    assert patched.status_code == 200, patched.text
    up = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": fmt, "byte_size": 10},
        headers=isolated_api.headers,
    )
    assert up.status_code == 200, up.text


# ---------------------------------------------------------------------------
# Upload target integrity (Issue #2525)
# ---------------------------------------------------------------------------


def _configure_bucket(api) -> None:
    _swap_settings(KGSettings(data_dir=api.data_dir, jwt_secret=TEST_JWT_SECRET, library_bucket="kg-library-test"))


def test_presigned_put_binds_declared_content_length(isolated_api, monkeypatch):
    """The presigned PUT must pin ContentLength to the declared byte_size so the
    quota check cannot be bypassed by uploading a larger body."""
    import kg.routers.library as library_router

    calls = []

    class FakeS3Client:
        def generate_presigned_url(self, operation, *, Params, ExpiresIn):
            calls.append((operation, Params))
            return "https://storage.test/presigned"

    monkeypatch.setattr(library_router, "_library_s3_client", lambda settings: FakeS3Client())
    _configure_bucket(isolated_api)
    book_id = _seed_book(isolated_api, client_book_id="cl-1")
    r = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": 4096},
        headers=isolated_api.headers,
    )
    assert r.status_code == 200, r.text
    assert calls[0][0] == "put_object"
    assert calls[0][1]["ContentLength"] == 4096


@pytest.mark.parametrize("sha", ["z" * 64, "abc", "g" * 64, " " * 64])
def test_asset_upload_rejects_non_hex_sha256(isolated_api, sha):
    book_id = _seed_book(isolated_api)
    r = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": 10, "sha256": sha},
        headers=isolated_api.headers,
    )
    assert r.status_code == 422, r.text


def test_asset_upload_accepts_hex_sha256(isolated_api):
    book_id = _seed_book(isolated_api)
    r = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": 10, "sha256": "aB" * 32},
        headers=isolated_api.headers,
    )
    assert r.status_code == 200, r.text


def test_presigned_put_url_signs_content_length_with_real_client(isolated_api, monkeypatch):
    """#2525: the real boto client must emit SigV4 so Content-Length is a signed
    header; with SigV2 query auth a larger body would still be accepted."""
    from urllib.parse import parse_qs, urlparse

    _set_fake_object_storage_credentials(monkeypatch)
    _configure_bucket(isolated_api)
    book_id = _seed_book(isolated_api, client_book_id="cl-real")
    r = isolated_api.client.post(
        f"/api/library/books/{book_id}/asset-upload",
        json={"format": "epub", "byte_size": 4096},
        headers=isolated_api.headers,
    )
    assert r.status_code == 200, r.text
    url = urlparse(r.json()["upload_url"])
    query = parse_qs(url.query)
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert "content-length" in query["X-Amz-SignedHeaders"][0].split(";")
    assert url.netloc.startswith("kg-library-test.s3.") and url.netloc != "kg-library-test.s3.amazonaws.com"
