from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from kg.api_models.common import VocabSource, _normalize_context


class VocabEntry(BaseModel):
    """A vocabulary entry from BooksBrowser."""

    word: str = Field(min_length=1, max_length=200)
    translation: str = Field(max_length=1000)
    context: str = Field(default="", max_length=5000)
    root_form: str | None = None  # AI-determined lemma from translate/quick
    source: VocabSource | None = None

    @field_validator("context", mode="before")
    @classmethod
    def normalize_context(cls, v: str) -> str:
        return _normalize_context(v) if isinstance(v, str) else v


class VocabAddResponse(BaseModel):
    created: int
    skipped: int
    duplicates: list[str]
    cardIds: dict[str, str]  # word -> card_id


class ArchiveWordRequest(BaseModel):
    archived: bool


class DeleteWordResponse(BaseModel):
    deleted: str
    id: str


class ArchiveWordResponse(BaseModel):
    word: str
    id: str
    archived: bool


class BatchDeleteRequest(BaseModel):
    words: list[str] = Field(min_length=1, max_length=500)


class BatchDeleteResponse(BaseModel):
    deleted: int
    deleted_words: list[str]
    not_found: list[str]


class BatchArchiveRequest(BaseModel):
    words: list[str] = Field(min_length=1, max_length=500)
    archived: bool = True


class BatchArchiveResponse(BaseModel):
    updated: int
    updated_words: list[str]
    not_found: list[str]
