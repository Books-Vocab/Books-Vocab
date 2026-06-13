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
