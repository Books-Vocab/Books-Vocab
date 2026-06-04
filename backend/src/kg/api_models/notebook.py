from __future__ import annotations

from typing import Final

from pydantic import BaseModel, Field, field_validator


class NotebookResponse(BaseModel):
    id: str
    name: str
    color: str | None = None
    coverPattern: str | None = None
    sortOrder: int = 0
    isDefault: bool = False
    isDeleted: bool = False
    cardCount: int = 0
    updatedAt: str | None = None


VALID_COVER_PATTERNS: Final[frozenset[str]] = frozenset({"dots", "lines", "grid", "waves", "circles", "noise"})


def _validate_cover_pattern(v: str | None) -> str | None:
    if v is not None and v != "" and v not in VALID_COVER_PATTERNS:
        raise ValueError(f"cover_pattern must be one of {VALID_COVER_PATTERNS} or empty string to clear")
    return v


class NotebookCreateRequest(BaseModel):
    name: str = Field(max_length=100)
    color: str | None = Field(default=None, max_length=20, pattern=r"^#[0-9a-fA-F]{6}$")
    cover_pattern: str | None = Field(default=None, max_length=30)

    _validate_cover_pattern = field_validator("cover_pattern")(staticmethod(_validate_cover_pattern))


class NotebookUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, max_length=20, pattern=r"^#[0-9a-fA-F]{6}$")
    sort_order: int | None = None
    cover_pattern: str | None = Field(default=None, max_length=30)

    _validate_cover_pattern = field_validator("cover_pattern")(staticmethod(_validate_cover_pattern))
