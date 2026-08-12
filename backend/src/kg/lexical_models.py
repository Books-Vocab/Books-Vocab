"""Provider-neutral lexical value objects and dependency protocols."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class LexicalAttribution(BaseModel):
    provider: str
    source_url: str
    license_name: str
    license_url: str
    attribution_text: str


class LexicalExample(BaseModel):
    key: str
    text: str


class LexicalSense(BaseModel):
    key: str
    part_of_speech: str | None = None
    definition: str
    examples: list[LexicalExample] = Field(default_factory=list)
    translations: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    antonyms: list[str] = Field(default_factory=list)


class LexicalEntry(BaseModel):
    provider: str
    dictionary_id: str
    schema_version: str
    entry_key: str
    word: str
    language: str
    pronunciations: list[str] = Field(default_factory=list)
    forms: list[str] = Field(default_factory=list)
    senses: list[LexicalSense] = Field(default_factory=list)
    attribution: LexicalAttribution
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    truncated: bool = False


class LexicalProviderCapabilities(BaseModel):
    exact_lookup: bool
    autocomplete: bool
    translations: bool
    pronunciation: bool
    cache_policy: Literal["persistent", "memory_only", "none"]


class LexicalProvider(Protocol):
    provider_id: str
    dictionary_id: str
    schema_version: str
    capabilities: LexicalProviderCapabilities

    def search(
        self, query: str, *, source_language: str, target_language: str
    ) -> LexicalEntry | None: ...

    def get_entry(
        self, entry_key: str, *, target_language: str = "zh-Hant"
    ) -> LexicalEntry | None: ...
