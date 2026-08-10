"""External asset cleanup performed before destructive account erasure."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from fastapi import HTTPException
from sqlmodel import Session, select

from .library.store import LibraryBook
from .sqlite_utils import make_sqlite_engine


class ObjectStorageClient(Protocol):
    def delete_object(self, *, Bucket: str, Key: str) -> object:  # noqa: N803
        ...


def _asset_object_keys(data_dir: Path, user_ids: Iterable[str]) -> tuple[str, ...]:
    """Read the durable object-key ledger without requiring user metadata."""
    keys: list[str] = []
    for uid in dict.fromkeys(user_ids):
        library_db = data_dir / "users" / uid / "library.db"
        if not library_db.is_file():
            continue
        engine = make_sqlite_engine(library_db)
        try:
            with Session(engine) as session:
                books = session.exec(select(LibraryBook)).all()
                keys.extend(book.asset_object_key for book in books if book.asset_object_key)
        finally:
            engine.dispose()
    return tuple(dict.fromkeys(keys))


def _is_missing_object(exc: Exception, client: ObjectStorageClient) -> bool:
    exception_namespace = getattr(client, "exceptions", None)
    no_such_key = getattr(exception_namespace, "NoSuchKey", None)
    if no_such_key is not None:
        try:
            if isinstance(exc, no_such_key):
                return True
        except TypeError:
            pass

    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error")
    code = error.get("Code") if isinstance(error, dict) else None
    return str(code) in {"NoSuchKey", "NotFound", "404"}


def delete_account_assets(
    data_dir: Path,
    user_ids: Iterable[str],
    *,
    library_bucket: str | None,
    library_s3_client: ObjectStorageClient | None,
) -> tuple[str, ...]:
    """Delete all recorded remote assets, preserving retryability on failure.

    No local state is modified here. A missing object is already in the desired
    state and therefore succeeds, making the operation safe to re-enter.
    """
    if not library_bucket:
        return ()
    if library_s3_client is None:
        raise HTTPException(status_code=503, detail="Library object storage is unavailable")

    keys = _asset_object_keys(data_dir, user_ids)
    for key in keys:
        try:
            library_s3_client.delete_object(Bucket=library_bucket, Key=key)
        except Exception as exc:
            if _is_missing_object(exc, library_s3_client):
                continue
            raise HTTPException(status_code=502, detail="Failed to delete library asset") from exc
    return keys


__all__ = ["ObjectStorageClient", "delete_account_assets"]
