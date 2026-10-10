"""SQLite-backed :class:`LibraryStore` — per-user book metadata mirror.

Extracted out of ``routers/library.py`` so the store can live in the shared
LRU cache (one engine per user, not a fresh engine per request). The
``LibraryBook`` SQLModel ``table=True`` definition lives here as the *single*
source of truth — a duplicate same-named ``table=True`` class elsewhere would
trip SQLModel's metadata registry with ``InvalidRequestError``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import update
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, select

from ..api_models.library import (
    BookCreateRequest,
    BookMetadataResponse,
    BookPositionRequest,
    BookUpdateRequest,
)
from ..sqlite_utils import make_sqlite_engine
from ..vocab_shared import _dt_to_iso


def _parse_utc_instant(value: str) -> datetime:
    """Parse an ISO timestamp as an absolute UTC instant."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class LibraryBook(SQLModel, table=True):
    """Per-user book metadata (no raw file storage)."""

    id: str = SQLField(default_factory=lambda: uuid.uuid4().hex[:12], primary_key=True)
    client_book_id: str | None = SQLField(default=None, index=True)
    title: str
    author: str | None = SQLField(default=None)
    language: str | None = SQLField(default=None)
    format: str | None = SQLField(default=None)
    notebook_id: str | None = SQLField(default=None)
    is_deleted: bool = SQLField(default=False)
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    # Reading position (LWW)
    locator: str | None = SQLField(default=None)
    progression: float | None = SQLField(default=None)
    position_updated_at: str | None = SQLField(default=None)
    # Asset storage (Architecture PR #7): where the raw book file lives.
    # asset_storage in {None (unknown), "local", "object"}.
    asset_storage: str | None = SQLField(default=None)
    asset_object_key: str | None = SQLField(default=None)
    asset_byte_size: int | None = SQLField(default=None)
    asset_sha256: str | None = SQLField(default=None)


class LibraryPendingObjectDelete(SQLModel, table=True):
    """Object key no longer referenced by a book row (tombstoned or superseded).

    Recorded in the same transaction that drops the reference. The request path
    then deletes the object best-effort and clears the entry on success; keys
    whose delete failed stay here to be retried on the next library write and
    to be reclaimed by account erasure.
    """

    object_key: str = SQLField(primary_key=True)
    book_id: str = SQLField(index=True)
    recorded_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


class LibraryStore:
    """SQLite-based library storage."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.engine = make_sqlite_engine(path)
        LibraryBook.metadata.create_all(
            self.engine,
            tables=[LibraryBook.__table__, LibraryPendingObjectDelete.__table__],
            checkfirst=True,
        )

    def close(self) -> None:
        """Dispose the SQLAlchemy engine and release connections.

        Required for LRU eviction: ``service_factories._close_store`` only
        disposes stores exposing ``close()``; without it the cached engine and
        its pooled connections leak when the store is evicted.
        """
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None

    def _to_response(self, book: LibraryBook) -> BookMetadataResponse:
        return BookMetadataResponse(
            id=book.id,
            client_book_id=book.client_book_id,
            title=book.title,
            author=book.author,
            language=book.language,
            format=book.format,
            notebook_id=book.notebook_id,
            is_deleted=book.is_deleted,
            updated_at=_dt_to_iso(book.updated_at),
            locator=book.locator,
            progression=book.progression,
            position_updated_at=book.position_updated_at,
        )

    def all(self, include_deleted: bool = False) -> list[BookMetadataResponse]:
        with Session(self.engine) as session:
            stmt = select(LibraryBook)
            if not include_deleted:
                stmt = stmt.where(LibraryBook.is_deleted == False)  # noqa: E712
            results = session.exec(stmt).all()
            return [self._to_response(r) for r in results]

    def get(self, book_id: str) -> LibraryBook | None:
        with Session(self.engine) as session:
            return session.get(LibraryBook, book_id)

    def create(self, req: BookCreateRequest) -> BookMetadataResponse:
        with Session(self.engine) as session:
            # Serialize the idempotency check with the insert across workers.
            # SQLite's default deferred transaction lets concurrent callers all
            # observe the same missing client_book_id before either commits.
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            # Idempotency: return the live row for client_book_id; tombstones never match, so a reused id gets a fresh row
            if req.client_book_id:
                existing = session.exec(
                    select(LibraryBook).where(
                        LibraryBook.client_book_id == req.client_book_id,
                        LibraryBook.is_deleted == False,  # noqa: E712
                    )
                ).first()
                if existing:
                    return self._to_response(existing)
            now = datetime.now(UTC)
            book = LibraryBook(
                id=uuid.uuid4().hex[:12],
                client_book_id=req.client_book_id,
                title=req.title,
                author=req.author,
                language=req.language,
                format=req.format,
                updated_at=now,
                created_at=now,
            )
            session.add(book)
            session.commit()
            session.refresh(book)
            return self._to_response(book)

    def update(self, book_id: str, req: BookUpdateRequest) -> LibraryBook | None:
        with Session(self.engine) as session:
            book = session.get(LibraryBook, book_id)
            if book is None or book.is_deleted:
                return None
            if req.title is not None:
                book.title = req.title
            if req.author is not None:
                book.author = req.author
            if req.language is not None:
                book.language = req.language
            if req.format is not None:
                book.format = req.format
            if req.notebook_id is not None:
                book.notebook_id = req.notebook_id
            book.updated_at = datetime.now(UTC)
            session.add(book)
            session.commit()
            session.refresh(book)
            return book

    def update_position(self, book_id: str, req: BookPositionRequest) -> LibraryBook | None:
        with Session(self.engine) as session:
            book = session.get(LibraryBook, book_id)
            if book is None or book.is_deleted:
                return None
            incoming_updated_at = _parse_utc_instant(req.updated_at)
            while True:
                expected_position_updated_at = book.position_updated_at
                current_updated_at = (
                    None if expected_position_updated_at is None else _parse_utc_instant(expected_position_updated_at)
                )
                if current_updated_at is not None and incoming_updated_at <= current_updated_at:
                    return book

                # End the read transaction before the compare-and-swap write so
                # a concurrent writer can commit without this session holding a
                # stale SQLite snapshot.
                session.rollback()
                stmt = (
                    update(LibraryBook)
                    .where(LibraryBook.id == book_id)
                    .where(LibraryBook.is_deleted == False)  # noqa: E712
                    .where(
                        LibraryBook.position_updated_at.is_(None)
                        if expected_position_updated_at is None
                        else LibraryBook.position_updated_at == expected_position_updated_at
                    )
                    .values(
                        locator=req.locator,
                        progression=req.progression,
                        position_updated_at=req.updated_at,
                        updated_at=datetime.now(UTC),
                    )
                )
                result = session.exec(stmt)
                session.commit()
                if result.rowcount:
                    return session.get(LibraryBook, book_id)

                # Another writer won the CAS. Reload its position and compare
                # again rather than allowing request arrival order to win.
                session.rollback()
                book = session.get(LibraryBook, book_id)
                if book is None or book.is_deleted:
                    return None

    def soft_delete(self, book_id: str) -> LibraryBook | None:
        """Soft-delete a book by flipping ``is_deleted`` and bumping
        ``updated_at``. Returns the book (idempotent: an already-deleted book
        still returns it), or ``None`` if the id is unknown.
        """
        with Session(self.engine) as session:
            _lock_book(session, book_id)
            book = session.get(LibraryBook, book_id)
            if book is None:
                return None
            if not book.is_deleted:
                book.is_deleted = True
                book.updated_at = datetime.now(UTC)
                session.add(book)
                if book.asset_storage == "object" and book.asset_object_key:
                    _record_pending_delete(session, book.id, book.asset_object_key)
            session.commit()
            session.refresh(book)
            return book

    def pending_object_keys(self) -> list[str]:
        """Object keys recorded for reclamation, in key order."""
        with Session(self.engine) as session:
            return list(
                session.exec(
                    select(LibraryPendingObjectDelete.object_key).order_by(LibraryPendingObjectDelete.object_key)
                ).all()
            )

    def reclaim_pending_object(self, object_key: str, delete: Callable[[str], None]) -> bool:
        """Delete ``object_key`` via ``delete`` unless a live book references it.

        Keys are deterministic per (user, book, format), so a key recorded as
        superseded can be re-adopted (epub -> local -> epub). The re-check and the
        delete therefore run inside one write transaction: the first statement
        takes SQLite's write lock, so a concurrent ``set_asset`` waits until the
        entry is resolved. Returns True if the object was deleted; False if the
        entry was absent or stale (a live reference exists, so it is only dropped
        from the ledger). If ``delete`` raises, nothing changes and the entry
        stays pending.

        Accepted gap: a presigned PUT that lands after this delete (client slow
        to upload) leaves an object no row references and no ledger entry tracks.
        Closing it needs a bucket lifecycle rule, which is production config and
        out of scope here.
        """
        with Session(self.engine) as session:
            pending = session.get(LibraryPendingObjectDelete, object_key)
            if pending is None:
                return False
            # Touching the row acquires the write lock before the re-check.
            pending.recorded_at = datetime.now(UTC)
            session.add(pending)
            session.flush()
            live = session.exec(
                select(LibraryBook.id).where(
                    LibraryBook.asset_storage == "object",
                    LibraryBook.asset_object_key == object_key,
                    LibraryBook.is_deleted == False,  # noqa: E712
                )
            ).first()
            deleted = False
            if live is None:
                delete(object_key)
                deleted = True
            session.delete(pending)
            session.commit()
            return deleted

    def set_asset(
        self,
        book_id: str,
        *,
        storage: str,
        object_key: str | None,
        byte_size: int | None,
        sha256: str | None,
    ) -> LibraryBook | None:
        """Record where a book's raw asset lives (local-only or object key).

        A previous object key that the row stops referencing is recorded in the
        pending-delete ledger in the same transaction; a key the row starts
        referencing is removed from it.

        Returns the updated book, or ``None`` if the id is unknown.
        """
        with Session(self.engine) as session:
            # Take the write lock before reading the previous key: two racing
            # changes (A->B, A->C) must serialize, otherwise both read A and B
            # is never recorded for reclamation.
            _lock_book(session, book_id)
            book = session.get(LibraryBook, book_id)
            if book is None:
                return None
            previous_key = book.asset_object_key if book.asset_storage == "object" else None
            if previous_key and previous_key != object_key:
                _record_pending_delete(session, book.id, previous_key)
            if object_key:
                _forget_pending_delete(session, object_key)
            book.asset_storage = storage
            book.asset_object_key = object_key
            book.asset_byte_size = byte_size
            book.asset_sha256 = sha256
            book.updated_at = datetime.now(UTC)
            session.add(book)
            session.commit()
            session.refresh(book)
            return book


def _lock_book(session: Session, book_id: str) -> None:
    """No-op write that acquires SQLite's write lock before a read-modify-write."""
    session.exec(update(LibraryBook).where(LibraryBook.id == book_id).values(id=book_id))


def _record_pending_delete(session: Session, book_id: str, object_key: str) -> None:
    if session.get(LibraryPendingObjectDelete, object_key) is None:
        session.add(LibraryPendingObjectDelete(object_key=object_key, book_id=book_id))


def _forget_pending_delete(session: Session, object_key: str) -> None:
    pending = session.get(LibraryPendingObjectDelete, object_key)
    if pending is not None:
        session.delete(pending)


__all__ = ["LibraryBook", "LibraryPendingObjectDelete", "LibraryStore"]
