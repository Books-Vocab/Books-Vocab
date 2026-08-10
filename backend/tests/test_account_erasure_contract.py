"""Contract tests for account erasure of object-backed library assets."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlmodel import Session

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
            {
                uid: (self.data_dir / "users" / uid).exists()
                for uid in ("canonical", "linked1")
            }
        )
        if Key in self.missing:
            raise _NoSuchKey(Key)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("object storage unavailable")
        return {}


def _seed_library_asset(data_dir: Path, uid: str, key: str) -> None:
    user_dir = data_dir / "users" / uid
    user_dir.mkdir(parents=True, exist_ok=True)
    store = LibraryStore(user_dir / "library.db")
    try:
        with Session(store.engine) as session:
            session.add(
                LibraryBook(
                    id=f"book-{uid}",
                    title=f"Book for {uid}",
                    asset_storage="object",
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
