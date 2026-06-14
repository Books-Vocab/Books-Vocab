"""SQLite-backed :class:`LibraryStore` — per-user book metadata mirror.

Extracted out of ``routers/library.py`` so the store can live in the shared
LRU cache (one engine per user, not a fresh engine per request). The
``LibraryBook`` SQLModel ``table=True`` definition lives here as the *single*
source of truth — a duplicate same-named ``table=True`` class elsewhere would
trip SQLModel's metadata registry with ``InvalidRequestError``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

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


class LibraryStore:
    """SQLite-based library storage."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.engine = make_sqlite_engine(path)
        LibraryBook.metadata.create_all(
            self.engine, tables=[LibraryBook.__table__], checkfirst=True
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

    def get_by_client_book_id(self, client_book_id: str) -> LibraryBook | None:
        with Session(self.engine) as session:
            stmt = select(LibraryBook).where(LibraryBook.client_book_id == client_book_id)
            return session.exec(stmt).first()

    def create(self, req: BookCreateRequest) -> BookMetadataResponse:
        with Session(self.engine) as session:
            # Idempotency: if client_book_id exists, return existing
            if req.client_book_id:
                existing = session.exec(
                    select(LibraryBook).where(LibraryBook.client_book_id == req.client_book_id)
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
            if book is None:
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
            if book is None:
                return None
            book.locator = req.locator
            book.progression = req.progression
            book.position_updated_at = req.updated_at
            book.updated_at = datetime.now(UTC)
            session.add(book)
            session.commit()
            session.refresh(book)
            return book

    def soft_delete(self, book_id: str) -> LibraryBook | None:
        """Soft-delete a book by flipping ``is_deleted`` and bumping
        ``updated_at``. Returns the book (idempotent: an already-deleted book
        still returns it), or ``None`` if the id is unknown.
        """
        with Session(self.engine) as session:
            book = session.get(LibraryBook, book_id)
            if book is None:
                return None
            if not book.is_deleted:
                book.is_deleted = True
                book.updated_at = datetime.now(UTC)
                session.add(book)
                session.commit()
                session.refresh(book)
            return book

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

        Returns the updated book, or ``None`` if the id is unknown.
        """
        with Session(self.engine) as session:
            book = session.get(LibraryBook, book_id)
            if book is None:
                return None
            book.asset_storage = storage
            book.asset_object_key = object_key
            book.asset_byte_size = byte_size
            book.asset_sha256 = sha256
            book.updated_at = datetime.now(UTC)
            session.add(book)
            session.commit()
            session.refresh(book)
            return book


__all__ = ["LibraryBook", "LibraryStore"]
