from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from kg.vocab_service import delete_vocab_word, graph_links_payload, list_vocab_cards, lookup_vocab_word


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
    inflections: list[str] | None = None

    def __post_init__(self):
        if self.examples is None:
            self.examples = []


class _FakeCardsStore:
    def __init__(self, cards):
        self._cards = list(cards)
        self.deleted = None

    def all(self, include_deleted: bool = False):
        if include_deleted:
            return list(self._cards)
        return [card for card in self._cards if not card.is_deleted]

    def get_modified_since(self, parsed_since):
        return list(self._cards)

    def delete(self, card_id: str):
        self.deleted = card_id


def _card_builder(card, graph, cards_by_id):
    return {"id": card.id, "content": card.content, "graph": graph, "cards_by_id": cards_by_id}


def test_list_lookup_and_delete_vocab_helpers():
    cards = _FakeCardsStore([_FakeCard(id="c1", content="evoke"), _FakeCard(id="c2", content="lucid")])
    graph = object()

    listed = list_vocab_cards(since=None, cards_store=cards, graph=graph, card_response_builder=_card_builder)
    assert [item["content"] for item in listed] == ["evoke", "lucid"]

    looked_up = lookup_vocab_word("Evoke", cards_store=cards, graph=graph, card_response_builder=_card_builder)
    assert looked_up["id"] == "c1"

    deleted = delete_vocab_word("lucid", cards_store=cards)
    assert deleted == {"deleted": "lucid", "id": "c2"}
    assert cards.deleted == "c2"


def test_list_vocab_rejects_bad_since():
    cards = _FakeCardsStore([_FakeCard(id="c1", content="evoke")])

    with pytest.raises(HTTPException) as exc_info:
        list_vocab_cards(since="not-a-date", cards_store=cards, graph=object(), card_response_builder=_card_builder)

    assert exc_info.value.status_code == 400


def test_graph_links_payload_only_returns_active_links():
    graph = SimpleNamespace(
        _links={
            "l1": SimpleNamespace(id="l1", from_id="c1", to_id="c2", kind=SimpleNamespace(value="confusable"), confidence=0.9, reason="r1", status="active"),
            "l2": SimpleNamespace(id="l2", from_id="c2", to_id="c3", kind=SimpleNamespace(value="shares_usage"), confidence=0.7, reason="r2", status="deprecated"),
        }
    )

    payload = graph_links_payload(graph=graph)
    assert len(payload) == 1
    assert payload[0].id == "l1"
    assert payload[0].kind == "confusable"
