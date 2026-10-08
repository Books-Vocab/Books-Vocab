"""Global GET /api/vocab must not do per-card ``cards_store.get`` lookups (#2245)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kg.vocab_crud import list_vocab_cards
from kg.vocab_handlers._shared import _CardNotebookGraph


def _card(card_id: str, notebook_id: str | None, *, deleted: bool = False):
    return SimpleNamespace(id=card_id, notebook_id=notebook_id, is_deleted=deleted)


class _SpyCards:
    def __init__(self, cards):
        self.by_id = {c.id: c for c in cards}
        self.get_calls: list[str] = []
        self.batch_calls: list[set[str]] = []

    def get(self, card_id):
        self.get_calls.append(card_id)
        return self.by_id.get(card_id)

    def get_batch(self, ids):
        self.batch_calls.append(set(ids))
        return {i: self.by_id[i] for i in ids if i in self.by_id}

    def page_cards(self, **_kw):
        return list(self.by_id.values())


class _Graph:
    def __init__(self, notebook_id, links):
        self.notebook_id = notebook_id
        self.links = links

    def get_links_for(self, card_id):
        return tuple(self.links.get(card_id, ()))


def _link(a, b):
    return SimpleNamespace(from_id=a, to_id=b)


def _factory(per_notebook):
    def make(_user_dir, *, notebook_id):
        return _Graph(notebook_id, per_notebook.get(notebook_id, {}))

    return make


def test_seed_routes_without_cards_get():
    cards = [_card("a", "nb1"), _card("b", "nb2"), _card("c", None)]
    spy = _SpyCards(cards)
    per_nb = {"nb1": {"a": [_link("a", "x")]}, "nb2": {"b": [_link("b", "y")]}, "default": {"c": [_link("c", "z")]}}
    graph = _CardNotebookGraph(spy, Path("."), _factory(per_nb))
    graph.seed(cards)
    assert [l.to_id for l in graph.get_links_for("a")] == ["x"]
    assert [l.to_id for l in graph.get_links_for("b")] == ["y"]
    assert [l.to_id for l in graph.get_links_for("c")] == ["z"]
    assert spy.get_calls == []


def test_unseeded_falls_back_once_and_caches_missing_returns_empty():
    spy = _SpyCards([_card("a", "nb1")])
    graph = _CardNotebookGraph(spy, Path("."), _factory({"nb1": {"a": [_link("a", "x")]}}))
    assert len(graph.get_links_for("a")) == 1
    assert len(graph.get_links_for("a")) == 1
    assert spy.get_calls == ["a"]
    assert graph.get_links_for("missing") == ()


@pytest.mark.parametrize("n", [5, 50])
def test_list_vocab_cards_global_no_per_card_get(n):
    cards, links = [], {"nb1": {}, "nb2": {}}
    for i in range(n):
        nb = "nb1" if i % 2 == 0 else "nb2"
        cards.append(_card(f"c{i}", nb))
        links[nb][f"c{i}"] = [_link(f"c{i}", f"c{(i + 1) % n}")]
    spy = _SpyCards(cards)
    graph = _CardNotebookGraph(spy, Path("."), _factory(links))
    seen = {}

    def builder(card, g, by_id):
        seen[card.id] = [(l.from_id, l.to_id) for l in g.get_links_for(card.id)]
        return card.id

    responses, _ = list_vocab_cards(since=None, cards_store=spy, graph=graph, card_response_builder=builder)
    assert len(responses) == n
    assert spy.get_calls == []
    assert len(spy.batch_calls) <= 1
    assert seen["c0"] == [("c0", "c1")]
