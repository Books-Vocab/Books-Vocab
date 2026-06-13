from __future__ import annotations

from pydantic import BaseModel, Field


class BookMetadataResponse(BaseModel):
    """A book in the user's library."""

    id: str
    client_book_id: str | None = None
    title: str
    author: str | None = None
    language: str | None = None
    format: str | None = None  # epub | pdf | txt | md
    notebook_id: str | None = None
    is_deleted: bool = False
    updated_at: str | None = None  # ISO8601
    # Reading position
    locator: str | None = None  # CFI / href / offset
    progression: float | None = None  # 0..1
    position_updated_at: str | None = None  # ISO8601


class BookCreateRequest(BaseModel):
    """Create a book metadata entry (idempotent via client_book_id)."""

    client_book_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    author: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, max_length=10)
    format: str | None = Field(default=None, max_length=10)


class BookUpdateRequest(BaseModel):
    """Partial update of book metadata or notebook binding."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    author: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, max_length=10)
    format: str | None = Field(default=None, max_length=10)
    notebook_id: str | None = Field(default=None, max_length=64)


class BookPositionRequest(BaseModel):
    """LWW reading position update."""

    locator: str | None = Field(default=None, max_length=500)
    progression: float | None = Field(default=None, ge=0.0, le=1.0)
    updated_at: str = Field(min_length=1, max_length=50)  # ISO8601 LWW timestamp


class DeleteBookResponse(BaseModel):
    """Result of DELETE /api/library/books/{id} (soft delete)."""

    deleted: str  # the book id that was soft-deleted


class AssetUploadRequest(BaseModel):
    """Request an object-storage upload target or declare a local-only asset.

    Architecture PR #7: book asset (EPUB/PDF/TXT/MD) upload entitlement.
    """

    format: str = Field(min_length=1, max_length=10)  # epub | pdf | txt | md
    byte_size: int = Field(ge=0)
    sha256: str | None = Field(default=None, max_length=64)
    local_only: bool = False


class AssetUploadResponse(BaseModel):
    """Upload target for a book asset.

    storage="local"  -> asset stays client-local (no server URL).
    storage="object" -> upload via presigned PUT to `upload_url` at `object_key`.
    """

    book_id: str
    storage: str  # local | object
    upload_url: str | None = None  # presigned PUT URL (object storage only)
    object_key: str | None = None  # storage key (object storage only)
    expires_in: int | None = None  # presigned URL TTL seconds (object storage only)
