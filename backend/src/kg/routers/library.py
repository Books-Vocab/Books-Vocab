from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select

from ..api_models.library import (
    BookCreateRequest,
    BookMetadataResponse,
    BookPositionRequest,
    BookUpdateRequest,
    DeleteBookResponse,
)
from ..deps import CurrentUser
from ..exceptions import BadRequestError, NotFoundError
from ..vocab_shared import _dt_to_iso

router = APIRouter(tags=["library"])


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


class LibraryStore:
    """SQLite-based library storage."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_url = f"sqlite:///{self.path.absolute()}"
        self.engine = create_engine(sqlite_url)
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
            conn.exec_driver_sql("PRAGMA busy_timeout=30000;")
        LibraryBook.metadata.create_all(self.engine, tables=[LibraryBook.__table__], checkfirst=True)

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


def _library_store(user_dir: Path) -> LibraryStore:
    return LibraryStore(user_dir / "library.db")


@router.get("/api/library/books", response_model=list[BookMetadataResponse])
def list_books(user: CurrentUser, since: str | None = None):
    store = _library_store(user["dir"])
    books = store.all(include_deleted=True)
    if since:
        # Simple since filter: compare updated_at ISO strings
        books = [b for b in books if b.updated_at and b.updated_at > since]
    return books


@router.post("/api/library/books", response_model=BookMetadataResponse, status_code=201)
def create_book(req: BookCreateRequest, user: CurrentUser):
    store = _library_store(user["dir"])
    return store.create(req)


@router.patch("/api/library/books/{book_id}", response_model=BookMetadataResponse)
def update_book(book_id: str, req: BookUpdateRequest, user: CurrentUser):
    store = _library_store(user["dir"])
    kwargs = {}
    if req.title is not None:
        kwargs["title"] = req.title
    if req.author is not None:
        kwargs["author"] = req.author
    if req.language is not None:
        kwargs["language"] = req.language
    if req.format is not None:
        kwargs["format"] = req.format
    if req.notebook_id is not None:
        kwargs["notebook_id"] = req.notebook_id
    if not kwargs:
        raise BadRequestError("No fields to update")
    book = store.update(book_id, req)
    if book is None:
        raise NotFoundError("Book", book_id)
    return store._to_response(book)


@router.put("/api/library/books/{book_id}/position", response_model=BookMetadataResponse)
def put_position(book_id: str, req: BookPositionRequest, user: CurrentUser):
    store = _library_store(user["dir"])
    book = store.update_position(book_id, req)
    if book is None:
        raise NotFoundError("Book", book_id)
    return store._to_response(book)


@router.delete("/api/library/books/{book_id}", response_model=DeleteBookResponse)
def delete_book(book_id: str, user: CurrentUser):
    """Soft-delete a library book (set ``is_deleted``).

    Idempotent: a second delete of an already-deleted book still returns 200.
    Unknown ids raise 404.
    """
    store = _library_store(user["dir"])
    result = store.soft_delete(book_id)
    if result is None:
        raise NotFoundError("Book", book_id)
    return DeleteBookResponse(deleted=book_id)
