"""Wire models for the public shared-decks (Explore) API — camelCase,
purpose-built.

``DeckCard`` is deliberately NOT ``CardResponse``: it is a hand-written subset
of the content plane that omits, at the type layer, all 7 SRS review columns.
A shared card physically cannot carry a copier's review schedule, so no route
under ``/api/decks`` may reuse ``CardResponse``. A contract test asserts the
zero-SRS property.
"""
from __future__ import annotations

from pydantic import BaseModel


class DeckCard(BaseModel):
    """Content-plane card — ZERO SRS columns (structural de-leak)."""

    id: str
    content: str
    pos: str | None = None
    meaning: str
    examples: list[str] = []
    collocations: list[str] = []
    note: str | None = None
    difficulty: float | None = None
    mode: str = "recognition"
    rootForm: str | None = None
    inflections: list[str] = []


class DeckSummary(BaseModel):
    deckId: str
    title: str
    color: str | None = None
    coverPattern: str | None = None
    authorLabel: str | None = None
    isOfficial: bool = False
    cardCount: int = 0
    downloadCount: int = 0
    ratingAvg: float | None = None
    ratingCount: int = 0
    languagePair: str | None = None
    category: str | None = None
    tags: list[str] = []
    updatedAt: str | None = None


class DeckListResponse(BaseModel):
    decks: list[DeckSummary] = []
    nextCursor: str | None = None


class DeckDetailResponse(DeckSummary):
    """Detail = summary + a bounded first page of cards (never an unbounded
    array); the client pages the rest via ``GET /api/decks/{id}/cards``."""

    sampleCards: list[DeckCard] = []
    cardsCursor: str | None = None


class DeckCardsResponse(BaseModel):
    cards: list[DeckCard] = []
    nextCursor: str | None = None


__all__ = [
    "DeckCard",
    "DeckSummary",
    "DeckListResponse",
    "DeckDetailResponse",
    "DeckCardsResponse",
]
