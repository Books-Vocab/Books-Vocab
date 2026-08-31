"""Regression tests for request-scoped vocabulary pagination cursors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from kg.exceptions import BadRequestError
from kg.vocab_crud import encode_cursor
from kg.vocab_handlers.crud import list_vocab_response


@dataclass
class _Card:
    id: str
    content: str
    updated_at: datetime
    notebook_id: str
    is_deleted: bool = False
    is_archived: bool = False


class _Cards:
    def __init__(self, cards: list[_Card]) -> None:
        self.cards = cards

    def page_cards(self, *, limit, after, include_deleted, notebook_id):
        cards = [card for card in self.cards if notebook_id is None or card.notebook_id == notebook_id]
        if after is not None:
            cards = [card for card in cards if (card.updated_at, card.id) > (after[0], after[1])]
        return sorted(cards, key=lambda card: (card.updated_at, card.id))[:limit]

    def get_modified_since(self, since, *, notebook_id=None):
        return [
            card
            for card in sorted(self.cards, key=lambda card: (card.updated_at, card.id))
            if (notebook_id is None or card.notebook_id == notebook_id) and card.updated_at > since
        ]

    def get_batch(self, card_ids):
        return {card.id: card for card in self.cards if card.id in card_ids}


class _Graph:
    @staticmethod
    def get_links_for(card_id):
        return []


def _builder(card, graph, cards_by_id):
    return {"id": card.id, "content": card.content}


def _list(store, *, notebook_id, since=None, cursor=None, limit=1):
    return list_vocab_response(
        since=since,
        user={"dir": "/tmp/test-user"},
        card_store_factory=lambda _user_dir: store,
        graph_store_factory=lambda _user_dir, notebook_id="default": _Graph(),
        card_response_builder=_builder,
        notebook_id=notebook_id,
        limit=limit,
        cursor=cursor,
    )


def test_cursor_from_one_notebook_is_rejected_for_another():
    now = datetime(2026, 8, 31, 12)
    store = _Cards(
        [
            _Card("a1", "alpha", now, "notebook-a"),
            _Card("b1", "bravo", now + timedelta(seconds=1), "notebook-b"),
        ]
    )

    first, cursor = _list(store, notebook_id="notebook-a")
    assert [card["id"] for card in first] == ["a1"]
    assert cursor

    with pytest.raises(BadRequestError, match="scope") as exc_info:
        _list(store, notebook_id="notebook-b", cursor=cursor)
    assert exc_info.value.status_code == 400


def test_same_scope_cursor_pages_without_gaps_or_duplicates():
    now = datetime(2026, 8, 31, 12)
    store = _Cards([_Card(f"a{i}", f"word-{i}", now + timedelta(seconds=i), "notebook-a") for i in range(4)])

    seen: list[str] = []
    cursor = None
    while True:
        page, cursor = _list(store, notebook_id="notebook-a", cursor=cursor)
        seen.extend(card["id"] for card in page)
        if cursor is None:
            break

    assert seen == ["a0", "a1", "a2", "a3"]
    assert len(seen) == len(set(seen))


def test_cursor_from_one_since_scope_is_rejected_for_another():
    now = datetime(2026, 8, 31, 12)
    store = _Cards(
        [
            _Card("a1", "alpha", now + timedelta(seconds=1), "notebook-a"),
            _Card("a2", "alpine", now + timedelta(seconds=2), "notebook-a"),
        ]
    )
    since = "2026-08-31T11:00:00Z"

    first, cursor = _list(store, notebook_id="notebook-a", since=since)
    assert [card["id"] for card in first] == ["a1"]
    assert cursor

    with pytest.raises(BadRequestError, match="scope") as exc_info:
        _list(store, notebook_id="notebook-a", since="2026-08-31T10:00:00Z", cursor=cursor)
    assert exc_info.value.status_code == 400


def test_legacy_unscoped_cursor_is_rejected():
    now = datetime(2026, 8, 31, 12)
    store = _Cards([_Card("a1", "alpha", now, "notebook-a")])
    legacy_cursor = encode_cursor((now, "a1"))

    with pytest.raises(BadRequestError, match="scope") as exc_info:
        _list(store, notebook_id="notebook-a", cursor=legacy_cursor)
    assert exc_info.value.status_code == 400
