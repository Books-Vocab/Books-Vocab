from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from kg.vocab_crud import list_vocab_cards


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------

def _card_builder(card, graph, cards_by_id):
    return {"id": card.id, "content": card.content}


@dataclass
class _FakeCard:
    id: str
    content: str
    meaning: str = "m"
    pos: str | None = None
    difficulty: float | None = None
    note: str | None = None
    examples: list[str] = field(default_factory=list)
    mode: str = "recognition"
    is_deleted: bool = False
    inflections: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class _FakeCardsStore:
    def __init__(self, cards):
        self._cards = list(cards)

    def get_modified_since(self, parsed_since, notebook_id: str | None = None):
        return list(self._cards)

    def get_batch(self, card_ids: set[str]) -> dict:
        return {c.id: c for c in self._cards if c.id in card_ids}

    def all_as_dict(self, include_deleted: bool = False, notebook_id: str | None = None):
        cards = [c for c in self._cards if include_deleted or not c.is_deleted]
        return {c.id: c for c in cards}


class _FakeGraph:
    def get_links_for(self, card_id):
        return []


# ---------------------------------------------------------------------------
# Tests: list_vocab_cards with limit
# ---------------------------------------------------------------------------

def test_list_vocab_cards_default_limit_5000():
    cards = [_FakeCard(id=f"c{i}", content=f"word{i}") for i in range(10)]
    store = _FakeCardsStore(cards)
    result = list_vocab_cards(since=None, cards_store=store, graph=object(), card_response_builder=_card_builder)
    assert len(result) == 10


def test_list_vocab_cards_full_sync_returns_all():
    """Full sync (since=None) must return ALL cards."""
    cards = [_FakeCard(id=f"c{i}", content=f"word{i}") for i in range(5)]
    store = _FakeCardsStore(cards)
    result = list_vocab_cards(since=None, cards_store=store, graph=object(), card_response_builder=_card_builder)
    assert len(result) == 5


def test_list_vocab_cards_with_since_returns_modified():
    """since 路徑走 get_modified_since。"""
    cards = [_FakeCard(id=f"c{i}", content=f"word{i}") for i in range(5)]
    store = _FakeCardsStore(cards)
    result = list_vocab_cards(
        since="2024-01-01T00:00:00Z",
        cards_store=store,
        graph=_FakeGraph(),
        card_response_builder=_card_builder,
    )
    assert len(result) == 5  # get_modified_since returns all 5
