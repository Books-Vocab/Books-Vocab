from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select

from ..api_models.library import (
    AssetUploadRequest,
    AssetUploadResponse,
    BookCreateRequest,
    BookMetadataResponse,
    BookPositionRequest,
    BookUpdateRequest,
    DeleteBookResponse,
)
from ..deps import CurrentUser
from ..exceptions import BadRequestError, ConflictError, NotFoundError
from ..settings import KGSettings
from ..vocab_shared import _dt_to_iso

# Presigned URL TTL (seconds) for asset upload/download targets.
_ASSET_URL_TTL = 3600

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


# ---------------------------------------------------------------------------
# Book asset storage (Architecture PR #7)
# ---------------------------------------------------------------------------


def _settings(request: Request) -> KGSettings:
    return request.app.state.kg_settings


def _library_s3_client(settings: KGSettings):
    import boto3

    return boto3.client(
        "s3",
        region_name=settings.library_bucket_region,
        endpoint_url=settings.library_bucket_endpoint_url,
    )


def _asset_object_key(user_id: str, book_id: str, fmt: str) -> str:
    safe_fmt = "".join(c for c in fmt.lower() if c.isalnum()) or "bin"
    return f"library/{user_id}/{book_id}/asset.{safe_fmt}"


@router.post(
    "/api/library/books/{book_id}/asset-upload",
    response_model=AssetUploadResponse,
)
def request_asset_upload(
    book_id: str,
    req: AssetUploadRequest,
    user: CurrentUser,
    request: Request,
):
    """Request an object-storage upload target or declare a local-only asset.

    When no ``library_bucket`` is configured (dev / privacy-default) or the
    client declares ``local_only``, the asset stays client-side and no upload
    URL is minted. Otherwise a presigned PUT URL is returned and the resulting
    object key is recorded on the book row for later download.
    """
    settings = _settings(request)
    store = _library_store(user["dir"])
    book = store.get(book_id)
    if book is None:
        raise NotFoundError("Book", book_id)

    # Quota policy: reject obviously oversize assets before minting a target.
    if req.byte_size > settings.library_asset_max_bytes:
        raise BadRequestError(
            f"asset too large ({req.byte_size} bytes); "
            f"max {settings.library_asset_max_bytes}"
        )

    local_only = req.local_only or not settings.library_bucket
    if local_only:
        store.set_asset(
            book_id,
            storage="local",
            object_key=None,
            byte_size=req.byte_size,
            sha256=req.sha256,
        )
        return AssetUploadResponse(book_id=book_id, storage="local")

    object_key = _asset_object_key(user["id"], book_id, req.format)
    client = _library_s3_client(settings)
    upload_url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.library_bucket, "Key": object_key},
        ExpiresIn=_ASSET_URL_TTL,
    )
    store.set_asset(
        book_id,
        storage="object",
        object_key=object_key,
        byte_size=req.byte_size,
        sha256=req.sha256,
    )
    return AssetUploadResponse(
        book_id=book_id,
        storage="object",
        upload_url=upload_url,
        object_key=object_key,
        expires_in=_ASSET_URL_TTL,
    )


@router.get("/api/library/books/{book_id}/asset")
def download_asset(book_id: str, user: CurrentUser, request: Request):
    """Redirect to an authorized object-storage URL for the book asset.

    404 unknown book; 409 when the asset is local-only (not server-hosted) or
    has never been registered.
    """
    settings = _settings(request)
    store = _library_store(user["dir"])
    book = store.get(book_id)
    if book is None:
        raise NotFoundError("Book", book_id)

    if book.asset_storage != "object" or not book.asset_object_key:
        raise ConflictError("Book asset is not server-hosted (local-only)")

    client = _library_s3_client(settings)
    download_url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.library_bucket, "Key": book.asset_object_key},
        ExpiresIn=_ASSET_URL_TTL,
    )
    return RedirectResponse(url=download_url, status_code=307)
