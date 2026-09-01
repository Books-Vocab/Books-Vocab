from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..lexical import LexicalAttribution


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class _DictionaryPayloadModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        from_attributes=True,
        populate_by_name=True,
    )


class _DictionaryExample(_DictionaryPayloadModel):
    key: str
    text: str


class _DictionarySense(_DictionaryPayloadModel):
    key: str
    part_of_speech: str | None = None
    definition: str
    examples: list[_DictionaryExample] = Field(default_factory=list)
    translations: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    antonyms: list[str] = Field(default_factory=list)


class _DictionaryAttribution(_DictionaryPayloadModel):
    provider: str
    source_url: str
    license_name: str
    license_url: str
    attribution_text: str


class _DictionaryEntry(_DictionaryPayloadModel):
    provider: str
    dictionary_id: str
    schema_version: str
    entry_key: str
    word: str
    language: str
    pronunciations: list[str] = Field(default_factory=list)
    forms: list[str] = Field(default_factory=list)
    senses: list[_DictionarySense] = Field(default_factory=list)
    attribution: _DictionaryAttribution
    fetched_at: datetime
    truncated: bool = False


class DictionarySearchHit(BaseModel):
    provider: str
    dictionaryId: str
    entryKey: str
    word: str
    language: str
    partsOfSpeech: list[str] = Field(default_factory=list)
    hasExamples: bool
    attribution: LexicalAttribution


class DictionarySearchResponse(BaseModel):
    hits: list[DictionarySearchHit] = Field(default_factory=list)
    cacheStatus: str


class DictionaryEntryResponse(BaseModel):
    entry: _DictionaryEntry
    cacheStatus: str


__all__ = [
    "DictionaryEntryResponse",
    "DictionarySearchHit",
    "DictionarySearchResponse",
]
