from __future__ import annotations

from types import SimpleNamespace

import pytest

from kg.vocab_crud import archive_vocab_word, delete_vocab_word, list_vocab_cards, lookup_vocab_word
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
