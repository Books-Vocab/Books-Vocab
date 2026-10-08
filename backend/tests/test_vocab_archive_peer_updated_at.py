"""Archive / unarchive / delete must bump ``updated_at`` on linked peer cards.

A peer's ``linksByKind`` hides links to archived or deleted cards, so the peer's
wire representation changes when this card changes state. The vocab incremental
pull is keyed by ``(updated_at, id)``; without a bump, another device never
re-fetches the peer and keeps a stale ``linksByKind``.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime

import pytest

from kg.cards import CardStore
from kg.graph import GraphStore, LinkKind
from kg.vocab_crud import (
    archive_vocab_word,
    batch_archive_vocab_words,
    batch_delete_vocab_words,
    delete_vocab_word,
)


@pytest.fixture()
def env(tmp_path):
    graph = GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
    )
    with closing(CardStore(path=tmp_path / "cards.db")) as cards:
        a = cards.add(content="alpha", meaning="a")
        b = cards.add(content="beta", meaning="b")
        c = cards.add(content="gamma", meaning="c")  # unlinked bystander
        graph.add_link(a.id, b.id, LinkKind.CONTRASTS_WITH, 0.9, "r")
        yield cards, graph, a, b, c


def _updated(cards: CardStore, card_id: str) -> datetime:
    card = cards.get(card_id)
    assert card is not None
    return card.updated_at


def test_archive_bumps_linked_peer_only(env):
    cards, graph, a, b, c = env
    b0, c0 = _updated(cards, b.id), _updated(cards, c.id)

    archive_vocab_word("alpha", archived=True, cards_store=cards, graph=graph)

    assert _updated(cards, b.id) > b0
    assert _updated(cards, c.id) == c0


def test_unarchive_bumps_linked_peer(env):
    cards, graph, a, b, _ = env
    archive_vocab_word("alpha", archived=True, cards_store=cards, graph=graph)
    b1 = _updated(cards, b.id)

    archive_vocab_word("alpha", archived=False, cards_store=cards, graph=graph)

    assert _updated(cards, b.id) > b1


def test_delete_bumps_linked_peer(env):
    cards, graph, a, b, _ = env
    b0 = _updated(cards, b.id)

    delete_vocab_word("alpha", cards_store=cards, graph=graph)

    assert _updated(cards, b.id) > b0


def test_batch_archive_and_unarchive_bump_linked_peer(env):
    cards, graph, a, b, _ = env
    b0 = _updated(cards, b.id)
    batch_archive_vocab_words(["alpha"], archived=True, cards_store=cards, graph=graph)
    b1 = _updated(cards, b.id)
    assert b1 > b0

    batch_archive_vocab_words(["alpha"], archived=False, cards_store=cards, graph=graph)

    assert _updated(cards, b.id) > b1


def test_batch_delete_bumps_linked_peer(env):
    cards, graph, a, b, _ = env
    b0 = _updated(cards, b.id)

    batch_delete_vocab_words(["alpha"], cards_store=cards, graph=graph)

    assert _updated(cards, b.id) > b0


def test_peer_reappears_in_incremental_pull(env):
    cards, graph, a, b, _ = env
    since = _updated(cards, b.id)

    archive_vocab_word("alpha", archived=True, cards_store=cards, graph=graph)

    modified_ids = {card.id for card in cards.get_modified_since(since)}
    assert b.id in modified_ids
