from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kg.vocab_crud import archive_vocab_word, delete_vocab_word, list_vocab_cards, lookup_vocab_word
from kg.vocab_handlers._shared import _CardNotebookGraph
from kg.vocab_intake import add_vocab_entries
from kg.vocab_shared import MAX_BATCH_SIZE, MAX_WORD_LENGTH
from test_vocab_service import (
    _card_builder,
    _FakeArchiveGraph,
    _FakeCard,
    _FakeCards,
    _FakeCardsStore,
    _FakeEmbeddings,
    _FakeGraph,
)


def test_list_lookup_and_delete_vocab_helpers():
    cards = _FakeCardsStore([_FakeCard(id="c1", content="evoke"), _FakeCard(id="c2", content="lucid")])
    graph = SimpleNamespace(get_links_for=lambda card_id: [])

    listed, _cursor = list_vocab_cards(since=None, cards_store=cards, graph=graph, card_response_builder=_card_builder)
    assert [item["content"] for item in listed] == ["evoke", "lucid"]

    looked_up = lookup_vocab_word("Evoke", cards_store=cards, graph=graph, card_response_builder=_card_builder)
    assert looked_up["id"] == "c1"

    deleted = delete_vocab_word("lucid", cards_store=cards)
    assert (deleted.deleted, deleted.id) == ("lucid", "c2")
    assert cards.deleted == "c2"


def test_list_vocab_rejects_bad_since():
    cards = _FakeCardsStore([_FakeCard(id="c1", content="evoke")])

    from kg.exceptions import BadRequestError

    with pytest.raises(BadRequestError) as exc_info:
        list_vocab_cards(since="not-a-date", cards_store=cards, graph=object(), card_response_builder=_card_builder)

    assert exc_info.value.status_code == 400


def test_add_vocab_entries_rejects_oversized_batch():
    from kg.api_models import VocabEntry
    from kg.exceptions import ValidationError

    entries = [VocabEntry(word=f"word{i}", translation="t", context="c") for i in range(MAX_BATCH_SIZE + 1)]
    with pytest.raises(ValidationError) as exc_info:
        add_vocab_entries(
            entries,
            user={"id": "u1"},
            cards=_FakeCards(),
            embeddings=_FakeEmbeddings(),
            graph=_FakeGraph(),
            logger=SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None),
        )
    assert exc_info.value.status_code == 422
    assert "500" in str(exc_info.value)


def test_add_vocab_entries_accepts_boundary_batch():
    from kg.api_models import VocabEntry

    entries = [VocabEntry(word=f"word{i}", translation="t", context="c") for i in range(MAX_BATCH_SIZE)]
    result = add_vocab_entries(
        entries,
        user={"id": "u1"},
        cards=_FakeCards(),
        embeddings=_FakeEmbeddings(),
        graph=_FakeGraph(),
        logger=SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None),
    )
    assert result.created == MAX_BATCH_SIZE


def test_lookup_vocab_word_rejects_too_long():
    cards = _FakeCardsStore([_FakeCard(id="c1", content="evoke")])
    long_word = "a" * (MAX_WORD_LENGTH + 1)

    from kg.exceptions import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        lookup_vocab_word(long_word, cards_store=cards, graph=object(), card_response_builder=_card_builder)
    assert exc_info.value.status_code == 422


def test_delete_vocab_word_rejects_too_long():
    cards = _FakeCardsStore([_FakeCard(id="c1", content="evoke")])
    long_word = "a" * (MAX_WORD_LENGTH + 1)

    from kg.exceptions import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        delete_vocab_word(long_word, cards_store=cards)
    assert exc_info.value.status_code == 422


class TestArchiveVocabWord:
    def test_archive_deprecates_graph_links(self):
        card = _FakeCard(id="c1", content="hello")
        cards = _FakeCardsStore([card])
        graph = _FakeArchiveGraph()
        result = archive_vocab_word("hello", archived=True, cards_store=cards, graph=graph)
        assert result.archived is True
        assert graph.deprecated_for == ["c1"]
        assert graph.removed_candidates_for == ["c1"]

    def test_unarchive_restores_graph_links(self):
        card = _FakeCard(id="c1", content="hello")
        cards = _FakeCardsStore([card])
        graph = _FakeArchiveGraph()
        result = archive_vocab_word("hello", archived=False, cards_store=cards, graph=graph)
        assert result.archived is False
        assert graph.restored_for == ["c1"]

    def test_archive_without_graph_still_works(self):
        card = _FakeCard(id="c1", content="hello")
        cards = _FakeCardsStore([card])
        result = archive_vocab_word("hello", archived=True, cards_store=cards)
        assert result.archived is True


# --- global list N+1 (#2245) ---
def _gl_card(card_id: str, notebook_id: str | None, *, deleted: bool = False):
    return SimpleNamespace(id=card_id, notebook_id=notebook_id, is_deleted=deleted)


class _GlSpyCards:
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


class _GlGraph:
    def __init__(self, notebook_id, links):
        self.notebook_id = notebook_id
        self.links = links

    def get_links_for(self, card_id):
        return tuple(self.links.get(card_id, ()))


def _gl_link(a, b):
    return SimpleNamespace(from_id=a, to_id=b)


def _gl_factory(per_notebook):
    def make(_user_dir, *, notebook_id):
        return _GlGraph(notebook_id, per_notebook.get(notebook_id, {}))

    return make


def test_seed_routes_without_cards_get():
    cards = [_gl_card("a", "nb1"), _gl_card("b", "nb2"), _gl_card("c", None)]
    spy = _GlSpyCards(cards)
    per_nb = {
        "nb1": {"a": [_gl_link("a", "x")]},
        "nb2": {"b": [_gl_link("b", "y")]},
        "default": {"c": [_gl_link("c", "z")]},
    }
    graph = _CardNotebookGraph(spy, Path("."), _gl_factory(per_nb))
    graph.seed(cards)
    assert [lk.to_id for lk in graph.get_links_for("a")] == ["x"]
    assert [lk.to_id for lk in graph.get_links_for("b")] == ["y"]
    assert [lk.to_id for lk in graph.get_links_for("c")] == ["z"]
    assert spy.get_calls == []


def test_unseeded_falls_back_once_and_caches_missing_returns_empty():
    spy = _GlSpyCards([_gl_card("a", "nb1")])
    graph = _CardNotebookGraph(spy, Path("."), _gl_factory({"nb1": {"a": [_gl_link("a", "x")]}}))
    assert len(graph.get_links_for("a")) == 1
    assert len(graph.get_links_for("a")) == 1
    assert spy.get_calls == ["a"]
    assert graph.get_links_for("missing") == ()


@pytest.mark.parametrize("n", [5, 50])
def test_list_vocab_cards_global_no_per_card_get(n):
    cards, links = [], {"nb1": {}, "nb2": {}}
    for i in range(n):
        nb = "nb1" if i % 2 == 0 else "nb2"
        cards.append(_gl_card(f"c{i}", nb))
        links[nb][f"c{i}"] = [_gl_link(f"c{i}", f"c{(i + 1) % n}")]
    spy = _GlSpyCards(cards)
    graph = _CardNotebookGraph(spy, Path("."), _gl_factory(links))
    seen = {}

    def builder(card, g, by_id):
        seen[card.id] = [(lk.from_id, lk.to_id) for lk in g.get_links_for(card.id)]
        return card.id

    responses, _ = list_vocab_cards(since=None, cards_store=spy, graph=graph, card_response_builder=builder)
    assert len(responses) == n
    assert spy.get_calls == []
    assert len(spy.batch_calls) <= 1
    assert seen["c0"] == [("c0", "c1")]
