from __future__ import annotations

from pydantic import BaseModel, Field

from ..dictionary_cards import (
    DictionaryCardNode,
    DictionaryProjectionItem,
    MaterializeLinkResult,
    SavedDictionaryCard,
)
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


class DictionaryMaterializeRequest(BaseModel):
    source_card_id: str = Field(alias="sourceCardId", min_length=1)
    notebook_id: str = Field(alias="notebookId", min_length=1, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    provider: str = Field(min_length=1)
    entry_key: str = Field(alias="entryKey", min_length=1)
    sense_key: str = Field(alias="senseKey", min_length=1)
    example_key: str = Field(alias="exampleKey", min_length=1)


class DictionarySelectionRequest(BaseModel):
    sense_key: str = Field(alias="senseKey", min_length=1)
    example_key: str = Field(alias="exampleKey", min_length=1)


class ReaderVisibilityRequest(BaseModel):
    reader_hidden: bool = Field(alias="readerHidden")


class DictionaryPromotionResponse(BaseModel):
    cardId: str
    cardRole: str
    promotionState: str
    alreadyPromoted: bool


__all__ = [
    "DictionaryCardNode",
    "DictionaryEntryResponse",
    "DictionaryMaterializeRequest",
    "DictionaryProjectionItem",
    "DictionaryPromotionResponse",
    "DictionarySearchHit",
    "DictionarySearchResponse",
    "DictionarySelectionRequest",
    "MaterializeLinkResult",
    "ReaderVisibilityRequest",
    "SavedDictionaryCard",
]
