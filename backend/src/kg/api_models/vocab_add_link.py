from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .common import VocabSource, _normalize_context

OperationStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "succeeded_with_warnings",
    "failed",
    "interrupted",
]


class AddLinkOperationRequest(BaseModel):
    """Request to ensure a target card and create a manual graph link."""

    from_id: str = Field(min_length=1, max_length=64)
    target_word: str = Field(min_length=1, max_length=200)
    translation: str | None = Field(default=None, max_length=1000)
    context: str = Field(
        default="",
        max_length=5000,
        description=(
            "Source context used only to disambiguate the target; it is not "
            "persisted as the target card's standalone example."
        ),
    )
    source: VocabSource | None = None
    source_lang: str | None = Field(default=None, max_length=32)
    target_lang: str | None = Field(default=None, max_length=32)

    @field_validator("target_word", mode="before")
    @classmethod
    def normalize_target_word(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("translation", mode="before")
    @classmethod
    def normalize_translation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("context", mode="before")
    @classmethod
    def normalize_context_value(cls, value: str) -> str:
        return _normalize_context(value) if isinstance(value, str) else value


class AddLinkOperationStep(BaseModel):
    id: str
    status: Literal["waiting", "running", "retry", "done", "skipped", "warning", "error"]
    current: int = 0
    total: int = 1
    detailCode: str | None = None


class AddLinkOperationResponse(BaseModel):
    operationId: str
    notebookId: str
    status: OperationStatus
    sequence: int
    steps: list[AddLinkOperationStep]
    targetCardId: str | None = None
    linkId: str | None = None
    warnings: list[str] = Field(default_factory=list)
    errorCode: str | None = None
