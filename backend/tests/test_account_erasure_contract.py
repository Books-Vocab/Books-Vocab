"""Contract tests for account erasure of object-backed library assets."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from kg import podcast_progress
from kg.account_erasure import delete_account_assets
from kg.library.store import LibraryBook, LibraryStore
from kg.user_handlers import delete_user_account_response
from kg.user_store import collect_account_ids_for_deletion


class _NoSuchKey(Exception):
    pass


class _FakeObjectClient:
    class exceptions:
        NoSuchKey = _NoSuchKey

    def __init__(self, *, missing: set[str] | None = None, failures: int = 0, data_dir: Path):
        self.missing = missing or set()
        self.failures = failures
        self.data_dir = data_dir
        self.calls: list[str] = []
        self.directory_states: list[dict[str, bool]] = []

    def delete_object(self, *, Bucket: str, Key: str):  # noqa: N803
        self.calls.append(Key)
        self.directory_states.append(
            {uid: (self.data_dir / "users" / uid).exists() for uid in ("canonical", "linked1")}
        )
        if Key in self.missing:
            raise _NoSuchKey(Key)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("object storage unavailable")
        return {}


def _seed_library_asset(
    data_dir: Path,
    uid: str,
    key: str,
    *,
    asset_storage: str | None = "object",
) -> None:
    user_dir = data_dir / "users" / uid
    user_dir.mkdir(parents=True, exist_ok=True)
    store = LibraryStore(user_dir / "library.db")
    try:
        with Session(store.engine) as session:
            session.add(
                LibraryBook(
                    id=f"book-{uid}",
                    title=f"Book for {uid}",
                    asset_storage=asset_storage,
                    asset_object_key=key,
                )
            )
            session.commit()
    finally:
        store.close()


def _call_delete(
    tmp_path: Path,
    users_data: dict,
    client: object | None,
    *,
    bucket: str | None = "library-test",
    user_id: str = "linked1",
):
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps(users_data))

    def load_users():
        return json.loads(users_file.read_text())

    def save_users(updated):
        users_file.write_text(json.dumps(updated))

    return delete_user_account_response(
        {"id": user_id},
        users_lock_file=tmp_path / "users.json.lock",
        load_users=load_users,
        save_users=save_users,
        collect_account_ids_for_deletion=collect_account_ids_for_deletion,
        data_dir=tmp_path,
        logger=MagicMock(),
        library_bucket=bucket,
        library_s3_client=client,
    )


def _linked_users() -> dict:
    return {
        "canonical": {"linked_ids": ["linked1"], "config": {}},
        "linked1": {"_linked_to": "canonical", "config": {}},
    }


def test_delete_account_removes_global_podcast_progress_for_canonical_and_linked_users(isolated_api):
    canonical_id = isolated_api.user_id
    linked_id = "linked_progress_user"
    other_id = "other_user"

    users = json.loads(isolated_api.users_file.read_text())
    users[canonical_id]["linked_ids"] = [linked_id]
    users[linked_id] = {"_linked_to": canonical_id, "config": {}}
    isolated_api.users_file.write_text(json.dumps(users))

    # The fixture's cache was not necessarily populated, but make the test
    # independent of that implementation detail before the HTTP request.
    from kg.api import app

    app.state.user_store.invalidate()

    for user_id, series_id in (
        (canonical_id, "canonical-series"),
        (linked_id, "linked-series"),
        (other_id, "other-series"),
    ):
        podcast_progress.upsert(
            user_id=user_id,
            series_id=series_id,
            ep_num=1,
            position_sec=10.0,
            duration_sec=100.0,
            updated_at="2026-09-01T00:00:00+00:00",
        )

    deleted = isolated_api.client.delete("/api/user/account", headers=isolated_api.headers)

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_user_id"] == canonical_id
    assert deleted.json()["linked_ids"] == [linked_id]

    with sqlite3.connect(isolated_api.data_dir / "podcast_progress.db") as conn:
        rows = conn.execute(
            "SELECT user_id, COUNT(*) FROM podcast_progress GROUP BY user_id ORDER BY user_id"
        ).fetchall()

    assert rows == [(other_id, 1)]

    # Preserve the existing account-deletion auth semantics on re-entry.
    retry = isolated_api.client.delete("/api/user/account", headers=isolated_api.headers)
    assert retry.status_code == 401


def test_delete_for_users_is_idempotent_and_user_scoped(tmp_path):
    podcast_progress.set_data_dir(tmp_path)

    for user_id in ("deleted", "other"):
        podcast_progress.upsert(
            user_id=user_id,
            series_id=f"{user_id}-series",
            ep_num=1,
            position_sec=10.0,
            duration_sec=100.0,
            updated_at="2026-09-01T00:00:00+00:00",
        )

    assert podcast_progress.delete_for_users(["deleted", "deleted"]) == 1
    assert podcast_progress.delete_for_users(["deleted"]) == 0
    assert podcast_progress.list_for_user(user_id="deleted") == []
    assert [item["series_id"] for item in podcast_progress.list_for_user(user_id="other")] == ["other-series"]


def test_all_primary_and_linked_object_keys_are_deleted_before_local_data(tmp_path):
    _seed_library_asset(tmp_path, "canonical", "library/canonical/book/asset.epub")
    _seed_library_asset(tmp_path, "linked1", "library/linked1/book/asset.epub")
    client = _FakeObjectClient(data_dir=tmp_path)

    response = _call_delete(tmp_path, _linked_users(), client)

    assert response.deleted_user_id == "canonical"
    assert set(client.calls) == {
        "library/canonical/book/asset.epub",
        "library/linked1/book/asset.epub",
    }
    assert all(all(states.values()) for states in client.directory_states)
    assert not (tmp_path / "users" / "canonical").exists()
    assert not (tmp_path / "users" / "linked1").exists()


def test_nosuchkey_is_idempotent_and_reentrant(tmp_path):
    _seed_library_asset(tmp_path, "canonical", "library/canonical/book/asset.epub")
    client = _FakeObjectClient(
        missing={"library/canonical/book/asset.epub"},
        data_dir=tmp_path,
    )

    delete_account_assets(
        tmp_path,
        ["canonical"],
        library_bucket="library-test",
        library_s3_client=client,
    )
    delete_account_assets(
        tmp_path,
        ["canonical"],
        library_bucket="library-test",
        library_s3_client=client,
    )

    assert client.calls == [
        "library/canonical/book/asset.epub",
        "library/canonical/book/asset.epub",
    ]


def test_remote_failure_preserves_identity_and_directory_then_retry_converges(tmp_path):
    _seed_library_asset(tmp_path, "canonical", "library/canonical/book/asset.epub")
    client = _FakeObjectClient(failures=1, data_dir=tmp_path)
    users_data = {"canonical": {"linked_ids": [], "config": {}}}

    with pytest.raises(HTTPException) as exc_info:
        _call_delete(tmp_path, users_data, client, user_id="canonical")
    assert exc_info.value.status_code >= 500
    assert json.loads((tmp_path / "users.json").read_text()) == users_data
    assert (tmp_path / "users" / "canonical").exists()

    # The same request is safe to retry after the transient remote failure.
    _call_delete(tmp_path, users_data, client, user_id="canonical")
    saved = json.loads((tmp_path / "users.json").read_text())
    assert "canonical" not in saved
    assert not (tmp_path / "users" / "canonical").exists()


def test_unconfigured_bucket_does_not_call_remote_client(tmp_path):
    _seed_library_asset(tmp_path, "canonical", "library/canonical/book/asset.epub")
    client = _FakeObjectClient(data_dir=tmp_path)
    users_data = {"canonical": {"linked_ids": [], "config": {}}}

    _call_delete(tmp_path, users_data, client, bucket=None, user_id="canonical")

    assert client.calls == []
    assert not (tmp_path / "users" / "canonical").exists()


def test_local_or_unknown_asset_keys_are_not_deleted_remotely(tmp_path):
    _seed_library_asset(
        tmp_path,
        "local-user",
        "stale/local/key",
        asset_storage="local",
    )
    _seed_library_asset(
        tmp_path,
        "unknown-user",
        "stale/unknown/key",
        asset_storage=None,
    )
    client = _FakeObjectClient(data_dir=tmp_path)

    keys = delete_account_assets(
        tmp_path,
        ["local-user", "unknown-user"],
        library_bucket="library-test",
        library_s3_client=client,
    )

    assert keys == ()
    assert client.calls == []
