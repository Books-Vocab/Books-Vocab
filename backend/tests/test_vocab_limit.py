from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from kg.cards import CardStore
from kg.vocab_service import list_vocab_cards


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

    def all_limited(self, limit: int = 5000, include_deleted: bool = False):
        cards = [c for c in self._cards if include_deleted or not c.is_deleted]
        return cards[:limit]

    def get_modified_since(self, parsed_since):
        return list(self._cards)

    def all_as_dict(self, include_deleted: bool = False):
        cards = [c for c in self._cards if include_deleted or not c.is_deleted]
        return {c.id: c for c in cards}


# ---------------------------------------------------------------------------
# Tests: list_vocab_cards with limit
# ---------------------------------------------------------------------------

def test_list_vocab_cards_default_limit_5000():
    cards = [_FakeCard(id=f"c{i}", content=f"word{i}") for i in range(10)]
    store = _FakeCardsStore(cards)
    result = list_vocab_cards(since=None, cards_store=store, graph=object(), card_response_builder=_card_builder)
    assert len(result) == 10


def test_list_vocab_cards_limit_2_returns_only_2():
    cards = [_FakeCard(id=f"c{i}", content=f"word{i}") for i in range(5)]
    store = _FakeCardsStore(cards)
    result = list_vocab_cards(since=None, limit=2, cards_store=store, graph=object(), card_response_builder=_card_builder)
    assert len(result) == 2


def test_list_vocab_cards_with_since_ignores_limit():
    """since 路徑走 get_modified_since，limit 不影響。"""
    cards = [_FakeCard(id=f"c{i}", content=f"word{i}") for i in range(5)]
    store = _FakeCardsStore(cards)
    result = list_vocab_cards(
        since="2024-01-01T00:00:00Z",
        limit=1,
        cards_store=store,
        graph=object(),
        card_response_builder=_card_builder,
    )
    assert len(result) == 5  # get_modified_since returns all 5


# ---------------------------------------------------------------------------
# Tests: CardStore.all_limited with real SQLite
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path):
    return CardStore(path=tmp_path / "cards.db")


def test_all_limited_respects_limit(store):
    for i in range(10):
        store.add(content=f"word{i}", meaning="m")
    result = store.all_limited(limit=3)
    assert len(result) == 3


def test_all_limited_default_limit_allows_all_under_5000(store):
    for i in range(20):
        store.add(content=f"word{i}", meaning="m")
    result = store.all_limited()
    assert len(result) == 20


def test_all_limited_excludes_deleted_by_default(store):
    c1 = store.add(content="evoke", meaning="bring to mind")
    store.add(content="lucid", meaning="clear")
    store.delete(c1.id)
    result = store.all_limited()
    ids = [c.id for c in result]
    assert c1.id not in ids
    assert len(result) == 1


def test_all_limited_orders_by_updated_at_desc(store):
    c1 = store.add(content="alpha", meaning="first")
    c2 = store.add(content="beta", meaning="second")
    # update alpha so it has a newer updated_at
    store.update(c1.id, meaning="first updated")
    result = store.all_limited()
    assert result[0].content == "alpha"
    assert result[1].content == "beta"
