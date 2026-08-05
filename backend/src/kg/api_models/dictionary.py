from __future__ import annotations

from pydantic import BaseModel, Field

from ..lexical import LexicalAttribution, LexicalEntry


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
    entry: LexicalEntry
    cacheStatus: str
