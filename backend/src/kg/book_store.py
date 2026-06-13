"""Per-user book (library) storage and CRUD.

Mirrors NotebookStore: one SQLite file per user (``books.db``) under the
user's data dir, WAL journaling, soft-delete via ``is_deleted``. Books are the
server-side mirror of the iOS bookshelf / podcast-series library; this store
backs the library routes the web client stands in for.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select

logger = logging.getLogger(__name__)


class Book(SQLModel, table=True):
    """A library book (server mirror of the iOS bookshelf entry)."""

    id: str = SQLField(default_factory=lambda: uuid.uuid4().hex[:12], primary_key=True)
    title: str
    author: str | None = None
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    is_deleted: bool = SQLField(default=False)


class BookStore:
    """SQLite-based per-user book storage."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_url = f"sqlite:///{self.path.absolute()}"
        self.engine = create_engine(sqlite_url)
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
            conn.exec_driver_sql("PRAGMA busy_timeout=30000;")
        Book.metadata.create_all(self.engine, tables=[Book.__table__], checkfirst=True)

    def add(
        self,
        *,
        title: str,
        author: str | None = None,
        book_id: str | None = None,
    ) -> Book:
        book = Book(title=title, author=author)
        if book_id is not None:
            book.id = book_id
        with Session(self.engine) as session:
            session.add(book)
            session.commit()
            session.refresh(book)
        return book

    def get(self, book_id: str) -> Book | None:
        with Session(self.engine) as session:
            return session.get(Book, book_id)

    def all(self, include_deleted: bool = False) -> list[Book]:
        with Session(self.engine) as session:
            statement = select(Book)
            if not include_deleted:
                statement = statement.where(Book.is_deleted.is_(False))
            statement = statement.order_by(Book.created_at)
            return list(session.exec(statement).all())

    def soft_delete(self, book_id: str) -> bool | None:
        """Soft-delete a book (set ``is_deleted``). Returns True if newly
        deleted, None if already deleted (idempotent success), False if the
        book id is unknown. Mirrors NotebookStore.delete's tri-state contract.
        """
        with Session(self.engine) as session:
            book = session.get(Book, book_id)
            if book is None:
                return False
            if book.is_deleted:
                return None
            book.is_deleted = True
            book.updated_at = datetime.now(UTC)
            session.add(book)
            session.commit()
            return True

    def close(self) -> None:
        """Dispose the SQLAlchemy engine and release connections."""
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None
