from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from kg.vocab_crud import list_vocab_cards

# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------

def _card_builder(card, graph, cards_by_id):
    return {"id": card.id, "content": card.content, "cards_by_id": cards_by_id}


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

    def page_cards(self, *, limit, after, include_deleted, notebook_id):
        cards = sorted(
            (c for c in self._cards if include_deleted or not c.is_deleted),
            key=lambda c: (c.updated_at, c.id),
        )
        if notebook_id is not None:
            cards = [c for c in cards if getattr(c, "notebook_id", "default") == notebook_id]
        if after is not None:
            cards = [c for c in cards if (c.updated_at, c.id) > after]
        return cards[:limit]


class _FakeGraph:
    def __init__(self, links=None):
        # links: dict[card_id] -> list of neighbour ids (undirected)
        self._links = links or {}

    def get_links_for(self, card_id):
        out = []
        for other in self._links.get(card_id, []):
            out.append(_FakeLink(card_id, other))
        return out


@dataclass
class _FakeLink:
    from_id: str
    to_id: str


# ---------------------------------------------------------------------------
# Tests: list_vocab_cards full sync now returns (cards, next_cursor)
# ---------------------------------------------------------------------------

def test_list_vocab_cards_full_sync_returns_all():
    """Full sync (since=None) with a large enough limit returns ALL cards."""
    cards = [_FakeCard(id=f"c{i}", content=f"word{i}",
                       updated_at=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(seconds=i)) for i in range(5)]
    store = _FakeCardsStore(cards)
    result, cursor = list_vocab_cards(
        since=None, cards_store=store, graph=_FakeGraph(), card_response_builder=_card_builder,
        limit=1000,
    )
    assert len(result) == 5
    assert cursor is None  # drained


def test_list_vocab_cards_with_since_returns_modified():
    """since 路徑走 get_modified_since。"""
    cards = [_FakeCard(id=f"c{i}", content=f"word{i}") for i in range(5)]
    store = _FakeCardsStore(cards)
    result, _cursor = list_vocab_cards(
        since="2024-01-01T00:00:00Z",
        cards_store=store,
        graph=_FakeGraph(),
        card_response_builder=_card_builder,
    )
    assert len(result) == 5  # get_modified_since returns all 5


# ---------------------------------------------------------------------------
# E2: cursor pagination + neighbour resolution
# ---------------------------------------------------------------------------

def test_paged_returns_cursor():
    """A bounded full-sync page returns a next_cursor when more rows remain."""
    base = datetime(2024, 1, 1, tzinfo=UTC)
    cards = [_FakeCard(id=f"c{i:02d}", content=f"w{i}",
                       updated_at=base + timedelta(seconds=i)) for i in range(5)]
    store = _FakeCardsStore(cards)

    page1, cursor1 = list_vocab_cards(
        since=None, cards_store=store, graph=_FakeGraph(),
        card_response_builder=_card_builder, limit=2,
    )
    assert [c["id"] for c in page1] == ["c00", "c01"]
    assert cursor1 == (cards[1].updated_at, "c01")

    page2, cursor2 = list_vocab_cards(
        since=None, cards_store=store, graph=_FakeGraph(),
        card_response_builder=_card_builder, limit=2, after=cursor1,
    )
    assert [c["id"] for c in page2] == ["c02", "c03"]

    page3, cursor3 = list_vocab_cards(
        since=None, cards_store=store, graph=_FakeGraph(),
        card_response_builder=_card_builder, limit=2, after=cursor2,
    )
    assert [c["id"] for c in page3] == ["c04"]
    assert cursor3 is None  # last page, fewer than limit -> drained


def test_neighbours_resolved_on_page():
    """A card's graph neighbour on a *different* page is still fetched into
    cards_by_id so its link is not dropped (the build_links_by_kind input must
    include cross-page neighbours)."""
    base = datetime(2024, 1, 1, tzinfo=UTC)
    a = _FakeCard(id="a", content="apple", updated_at=base)
    b = _FakeCard(id="b", content="banana", updated_at=base + timedelta(seconds=10))
    store = _FakeCardsStore([a, b])
    # a links to b, but b lands on a later page.
    graph = _FakeGraph({"a": ["b"], "b": ["a"]})

    page1, _cursor = list_vocab_cards(
        since=None, cards_store=store, graph=graph,
        card_response_builder=_card_builder, limit=1,
    )
    assert [c["id"] for c in page1] == ["a"]
    # neighbour b resolved into cards_by_id even though it's not on this page
    assert "b" in page1[0]["cards_by_id"]


def test_since_with_cursor():
    """since branch also honours limit + after for consistency."""
    base = datetime(2024, 1, 1, tzinfo=UTC)
    cards = [_FakeCard(id=f"c{i:02d}", content=f"w{i}",
                       updated_at=base + timedelta(seconds=i)) for i in range(4)]

    class _SinceStore(_FakeCardsStore):
        def get_modified_since(self, parsed_since, notebook_id: str | None = None):
            return sorted(self._cards, key=lambda c: (c.updated_at, c.id))

    store = _SinceStore(cards)
    page1, cursor1 = list_vocab_cards(
        since="2023-01-01T00:00:00Z", cards_store=store, graph=_FakeGraph(),
        card_response_builder=_card_builder, limit=2,
    )
    assert [c["id"] for c in page1] == ["c00", "c01"]
    assert cursor1 == (cards[1].updated_at, "c01")

    page2, _cursor2 = list_vocab_cards(
        since="2023-01-01T00:00:00Z", cards_store=store, graph=_FakeGraph(),
        card_response_builder=_card_builder, limit=2, after=cursor1,
    )
    assert [c["id"] for c in page2] == ["c02", "c03"]
