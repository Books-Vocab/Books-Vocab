"""Public shared-decks (Explore) router, mounted at ``/api/decks``.

Phase 1b: guest-browsable list / detail / cards over official decks. These GETs
are intentionally **public with no auth dependency** — browse returns only
public+official decks (identical for everyone), so an absent *or expired*
bearer is simply ignored. This is the §7 "tolerate expired bearer → guest"
contract: opening Explore with a stale token must never trip a 401 →
session-invalidation logout. When a later phase needs per-user context here
(e.g. an "already copied" badge), add a *lenient* optional-auth dependency that
degrades an expired token to guest — NOT the strict ``OptionalCurrentUser``,
which fails loud on expiry.

Write paths (copy/publish/rate/report) arrive in later phases.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request

from ..api_models.decks import (
    DeckCard,
    DeckCardsResponse,
    DeckDetailResponse,
    DeckListResponse,
    DeckSummary,
)
from ..deps import _shared_deck_store
from ..exceptions import BadRequestError, NotFoundError
from ..shared_decks.cursor import decode_cursor, encode_cursor
from ..shared_decks.store import SharedDeck, SharedDeckCard
from ..vocab_shared import _dt_to_iso

router = APIRouter(tags=["shared-decks"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 50
_MAX_CARD_LIMIT = 100
_SAMPLE_CARDS = 12
_SORTS = {"recency", "alpha"}


def _summary(deck: SharedDeck) -> DeckSummary:
    return DeckSummary(
        deckId=deck.id,
        title=deck.title,
        color=deck.color,
        coverPattern=deck.cover_pattern,
        authorLabel=deck.publisher_display_name,
        isOfficial=deck.source == "official",
        cardCount=deck.card_count,
        downloadCount=deck.download_count,
        ratingAvg=(deck.rating_sum / deck.rating_count) if deck.rating_count else None,
        ratingCount=deck.rating_count,
        languagePair=deck.language_pair,
        category=deck.category,
        tags=deck.tags or [],
        updatedAt=_dt_to_iso(deck.updated_at),
    )


def _card(c: SharedDeckCard) -> DeckCard:
    return DeckCard(
        id=c.id,
        content=c.content,
        pos=c.pos,
        meaning=c.meaning,
        examples=c.examples or [],
        collocations=c.collocations or [],
        note=c.note,
        difficulty=c.difficulty,
        mode=c.mode,
        rootForm=c.root_form,
        inflections=c.inflections or [],
    )


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _deck_after(payload: dict, sort: str) -> tuple[object, str]:
    """Rebuild the keyset boundary from a decoded list cursor, sort-typed."""
    if payload.get("s") != sort:
        raise BadRequestError("Cursor sort mismatch")
    raw, deck_id = payload.get("v"), payload.get("id")
    if not isinstance(deck_id, str) or raw is None:
        raise BadRequestError("Invalid cursor")
    if sort == "recency":
        try:
            return datetime.fromisoformat(str(raw)), deck_id
        except ValueError as exc:
            raise BadRequestError("Invalid cursor") from exc
    return str(raw), deck_id


def _deck_cursor(deck: SharedDeck, sort: str, secret: str) -> str | None:
    value = deck.updated_at.isoformat() if sort == "recency" else deck.title_nfc_lower
    return encode_cursor({"s": sort, "v": value, "id": deck.id}, secret)


@router.get("/api/decks", response_model=DeckListResponse)
def list_decks(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    languagePair: str | None = None,
    official: bool | None = None,
    sort: str = "recency",
    cursor: str | None = None,
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
):
    if sort not in _SORTS:
        raise BadRequestError(f"sort must be one of {sorted(_SORTS)}")
    settings = request.app.state.kg_settings
    store = _shared_deck_store(settings)
    after = None
    if cursor:
        after = _deck_after(decode_cursor(cursor, settings.jwt_secret), sort)
    limit = _clamp(limit, 1, _MAX_LIMIT)
    rows = store.browse(
        limit=limit + 1, sort=sort, after=after, q=q,
        category=category, language_pair=languagePair, official=official,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _deck_cursor(rows[-1], sort, settings.jwt_secret) if has_more and rows else None
    return DeckListResponse(decks=[_summary(d) for d in rows], nextCursor=next_cursor)


@router.get("/api/decks/{deck_id}", response_model=DeckDetailResponse)
def get_deck(request: Request, deck_id: str):
    settings = request.app.state.kg_settings
    store = _shared_deck_store(settings)
    deck = store.get(deck_id)
    if deck is None:
        raise NotFoundError("Deck not found")
    cards = store.page_cards(
        deck.id, version=deck.current_version, limit=_SAMPLE_CARDS + 1
    )
    has_more = len(cards) > _SAMPLE_CARDS
    cards = cards[:_SAMPLE_CARDS]
    cards_cursor = (
        encode_cursor({"k": "cards", "id": cards[-1].id}, settings.jwt_secret)
        if has_more and cards else None
    )
    return DeckDetailResponse(
        **_summary(deck).model_dump(),
        sampleCards=[_card(c) for c in cards],
        cardsCursor=cards_cursor,
    )


@router.get("/api/decks/{deck_id}/cards", response_model=DeckCardsResponse)
def get_deck_cards(
    request: Request,
    deck_id: str,
    cursor: str | None = None,
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_CARD_LIMIT),
):
    settings = request.app.state.kg_settings
    store = _shared_deck_store(settings)
    deck = store.get(deck_id)
    if deck is None:
        raise NotFoundError("Deck not found")
    after = None
    if cursor:
        payload = decode_cursor(cursor, settings.jwt_secret)
        after = payload.get("id")
        if not isinstance(after, str):
            raise BadRequestError("Invalid cursor")
    limit = _clamp(limit, 1, _MAX_CARD_LIMIT)
    cards = store.page_cards(
        deck.id, version=deck.current_version, limit=limit + 1, after=after
    )
    has_more = len(cards) > limit
    cards = cards[:limit]
    next_cursor = (
        encode_cursor({"k": "cards", "id": cards[-1].id}, settings.jwt_secret)
        if has_more and cards else None
    )
    return DeckCardsResponse(cards=[_card(c) for c in cards], nextCursor=next_cursor)
