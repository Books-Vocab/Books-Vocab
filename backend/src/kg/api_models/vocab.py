from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from kg.api_models.common import VocabSource, _normalize_context

MAX_BATCH_WORD_LENGTH = 200


class VocabEntry(BaseModel):
    """A vocabulary entry from BooksAndVocab."""

    word: str = Field(min_length=1, max_length=200)
    translation: str = Field(min_length=1, max_length=1000)
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
    duplicates: list[str]  # client 送出的『原始』word（未清洗），供 iOS 配對出列
    cardIds: dict[str, str]  # 原始 submitted word -> card_id（非清洗後 word；見 vocab_intake）


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

    @field_validator("words")
    @classmethod
    def validate_words(cls, words: list[str]) -> list[str]:
        _validate_batch_words(words)
        return words


class BatchDeleteResponse(BaseModel):
    deleted: int
    deleted_words: list[str]
    not_found: list[str]
    # Words whose graph cleanup failed: the card was restored and still exists
    # on the server. Clients must retry these, NOT converge them locally. See
    # #720 / docs/reference/sync_lifecycle.md. Defaulted so older payloads parse.
    failed: list[str] = Field(default_factory=list)


class BatchArchiveRequest(BaseModel):
    words: list[str] = Field(min_length=1, max_length=500)
    archived: bool = True

    @field_validator("words")
    @classmethod
    def validate_words(cls, words: list[str]) -> list[str]:
        _validate_batch_words(words)
        return words


class BatchArchiveResponse(BaseModel):
    updated: int
    updated_words: list[str]
    not_found: list[str]
    # Words whose graph cleanup/restore failed: the archive state was rolled
    # back and the card still exists on the server. Clients must retry these,
    # NOT converge them. See #720 / docs/reference/sync_lifecycle.md.
    failed: list[str] = Field(default_factory=list)


def _validate_batch_words(words: list[str]) -> None:
    for word in words:
        if not word.strip():
            raise ValueError("word must be non-empty")
        if len(word) > MAX_BATCH_WORD_LENGTH:
            raise ValueError(f"word too long (max {MAX_BATCH_WORD_LENGTH})")
