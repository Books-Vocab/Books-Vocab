from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from kg.vocab_graph import graph_links_payload


@dataclass
class _FakeCard:
    id: str
    content: str
    meaning: str = "m"
    pos: str | None = None
    difficulty: float | None = None
    note: str | None = None
    examples: list[str] = None
    mode: str = "production"
    is_deleted: bool = False
    is_archived: bool = False
    inflections: list[str] | None = None

    def __post_init__(self):
        if self.examples is None:
            self.examples = []


class _FakeCardsStore:
    def __init__(self, cards):
        self._cards = list(cards)
        self.deleted = None

    def all(self, include_deleted: bool = False, notebook_id: str | None = None):
        if include_deleted:
            return list(self._cards)
        return [card for card in self._cards if not card.is_deleted]

    def all_as_dict(self, include_deleted: bool = False, notebook_id: str | None = None):
        return {card.id: card for card in self.all(include_deleted=include_deleted)}

    def page_cards(self, *, limit, after, include_deleted, notebook_id):
        cards = self.all(include_deleted=include_deleted)
        if after is not None:
            cards = [c for c in cards if (c.updated_at, c.id) > after]
        return cards[:limit]

    def get_batch(self, card_ids):
        return {c.id: c for c in self._cards if c.id in card_ids}

    def get_modified_since(self, parsed_since, notebook_id: str | None = None):
        return list(self._cards)

    def find_by_content(self, content: str, notebook_id: str | None = None):
        import unicodedata

        norm = unicodedata.normalize("NFC", content).strip().lower()
        for card in self._cards:
            if unicodedata.normalize("NFC", card.content).strip().lower() == norm and not card.is_deleted:
                return card
        return None

    def update(self, card_id, **kwargs):
        for card in self._cards:
            if card.id == card_id:
                for k, v in kwargs.items():
                    setattr(card, k, v)
                return

    def delete(self, card_id: str):
        self.deleted = card_id

    def get(self, card_id: str):
        for card in self._cards:
            if card.id == card_id:
                return card
        return None


def _card_builder(card, graph, cards_by_id):
    return {"id": card.id, "content": card.content, "graph": graph, "cards_by_id": cards_by_id}


class _FakeCards:
    def __init__(self):
        self._cards = []

    def all(self, include_deleted=False, notebook_id=None):
        return list(self._cards)

    def find_by_content(self, content, notebook_id=None):
        import unicodedata

        norm = unicodedata.normalize("NFC", content).strip().lower()
        for card in self._cards:
            if card.content.strip().lower() == norm:
                return card
        return None

    def add(self, content, meaning, **kwargs):
        from types import SimpleNamespace

        def _embed_text():
            return f"{content}: {meaning}"

        card = SimpleNamespace(id=f"id_{content}", content=content, meaning=meaning, embed_text=_embed_text)
        self._cards.append(card)
        return card

    def get(self, card_id):
        for c in self._cards:
            if c.id == card_id:
                return c
        return None


class _FakeEmbeddings:
    def has(self, card_id):
        return False

    def add(self, card_id, text):
        pass

    def add_batch(self, items):
        for card_id, text in items:
            self.add(card_id, text)

    def find_similar(self, card_id, k=3):
        return []


class _FakeGraph:
    def add_pending_judge(self, card_ids):
        pass


class _FakeArchiveGraph:
    def __init__(self):
        self.deprecated_for = []
        self.removed_candidates_for = []
        self.restored_for = []
        self.removed_blocked_for = []

    def deprecate_links_for(self, card_id, *, source="auto"):
        self.deprecated_for.append(card_id)
        return 1

    def remove_candidates_for(self, card_id):
        self.removed_candidates_for.append(card_id)
        return 0

    def remove_blocked_pairs_for(self, card_id):
        self.removed_blocked_for.append(card_id)

    def restore_links_for(self, card_id, cards_store, *, source="auto"):
        self.restored_for.append(card_id)
        return 1

    def cleanup_for_card(self, card_id, *, remove_blocked=False, source="auto"):
        self.deprecate_links_for(card_id)
        self.remove_candidates_for(card_id)
        if remove_blocked:
            self.remove_blocked_pairs_for(card_id)
        return {"deprecated": 1, "candidates_removed": 0}


class _FakeEmbeddingStore:
    """Records remove / remove_batch calls so the delete-path hook is testable
    without a real numpy store."""

    def __init__(self, ids: list[str] | None = None):
        self._ids = list(ids or [])
        self.removed: list[str] = []

    def remove(self, card_id: str) -> bool:
        if card_id in self._ids:
            self._ids.remove(card_id)
            self.removed.append(card_id)
            return True
        return False

    def remove_batch(self, card_ids: list[str]) -> int:
        n = 0
        for cid in card_ids:
            if self.remove(cid):
                n += 1
        return n


class _PartialFailingGraph:
    """cleanup_for_card raises for one specific card id, succeeds otherwise."""

    def __init__(self, fail_for: str):
        self._fail_for = fail_for
        self.cleaned: list[str] = []

    def cleanup_for_card(self, card_id, *, remove_blocked=False, source="auto"):
        if card_id == self._fail_for:
            raise RuntimeError(f"graph cleanup blew up for {card_id}")
        self.cleaned.append(card_id)
        return {"deprecated": 1, "candidates_removed": 0}


def test_graph_links_payload_only_returns_active_links():
    links = {
        "l1": SimpleNamespace(id="l1", from_id="c1", to_id="c2", kind=SimpleNamespace(value="contrasts_with"), confidence=0.9, reason="r1", status="active"),
        "l2": SimpleNamespace(id="l2", from_id="c2", to_id="c3", kind=SimpleNamespace(value="shares_usage"), confidence=0.7, reason="r2", status="deprecated"),
        "l3": SimpleNamespace(id="l3", from_id="c3", to_id="c4", kind=SimpleNamespace(value="contrasts_with"), confidence=0.8, reason="r3", status="hidden"),
    }
    graph = SimpleNamespace(
        all_links=lambda: links.values(),
    )

    payload = graph_links_payload(graph=graph)
    assert len(payload) == 1
    assert payload[0].id == "l1"
    assert payload[0].kind == "contrasts_with"


def test_incremental_query_does_not_load_all_cards(tmp_path):
    """Incremental sync should use get_modified_since, not all_as_dict."""
    from datetime import datetime, timedelta
    from unittest.mock import MagicMock

    from kg.vocab_crud import list_vocab_cards

    cards_store = MagicMock()
    now = datetime(2026, 3, 31, 12, 0, 0)
    modified_card = MagicMock()
    modified_card.id = "card1"
    modified_card.is_deleted = False
    modified_card.content = "test"
    modified_card.updated_at = now

    cards_store.get_modified_since.return_value = [modified_card]
    cards_store.get_batch.return_value = {}

    graph = MagicMock()
    graph.get_links_for.return_value = []

    builder = MagicMock(return_value=MagicMock())

    since = (now - timedelta(hours=1)).isoformat() + "Z"
    list_vocab_cards(since=since, cards_store=cards_store, graph=graph,
                     card_response_builder=builder, notebook_id=None)

    cards_store.get_modified_since.assert_called_once()
    cards_store.all_as_dict.assert_not_called()


def test_incremental_query_resolves_neighbour_links(tmp_path):
    """Incremental query should correctly resolve links to non-modified neighbour cards."""
    from datetime import datetime

    from sqlmodel import Session

    from kg.cards import CardStore
    from kg.cards.model import Card
    from kg.difficulty import get_tier
    from kg.graph import GraphStore, LinkKind
    from kg.vocab_crud import list_vocab_cards
    from kg.vocab_shared import card_response

    cards = CardStore(tmp_path / "cards.db")
    old_card = cards.add("apple", meaning="蘋果")
    new_card = cards.add("fruit", meaning="水果")
    since_dt = datetime(2026, 1, 1, 12, 0, 0)
    with Session(cards.engine) as session:
        session.get(Card, old_card.id).updated_at = since_dt.replace(hour=11)
        session.get(Card, new_card.id).updated_at = since_dt.replace(hour=13)
        session.commit()

    graph = GraphStore(
        tmp_path / "graph.json",
        tmp_path / "candidates.json",
        tmp_path / "blocked.json",
    )
    graph.batch_add_links([(new_card.id, old_card.id, LinkKind.SHARES_USAGE, 0.9, "fruit→apple")])

    link_kinds = list(LinkKind)
    link_labels = {k: k.value for k in LinkKind}

    def builder(card, g, cards_by_id):
        return card_response(card, graph=g, cards_by_id=cards_by_id,
                             tier_getter=get_tier, link_kinds=link_kinds, link_labels=link_labels)

    since_str = since_dt.isoformat() + "Z"
    results, _cursor = list_vocab_cards(since=since_str, cards_store=cards, graph=graph,
                                        card_response_builder=builder, notebook_id=None)

    assert len(results) == 1
    assert results[0].content == "fruit"
    assert "shares_usage" in results[0].linksByKind
    assert results[0].linksByKind["shares_usage"][0].word == "apple"
