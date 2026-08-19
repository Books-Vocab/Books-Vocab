from __future__ import annotations

import pytest

from kg.vocab_crud import batch_archive_vocab_words, batch_delete_vocab_words
from test_vocab_service import _FakeArchiveGraph, _FakeCard, _FakeCardsStore


class TestBatchDeleteVocabWords:
    def test_deletes_multiple_words(self):
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="hello"),
            _FakeCard(id="c2", content="world"),
            _FakeCard(id="c3", content="keep"),
        ])
        result = batch_delete_vocab_words(["hello", "world"], cards_store=cards)
        assert result["deleted"] == 2
        assert set(result["deleted_words"]) == {"hello", "world"}
        assert result["not_found"] == []

    def test_partial_not_found(self):
        cards = _FakeCardsStore([_FakeCard(id="c1", content="hello")])
        result = batch_delete_vocab_words(["hello", "missing"], cards_store=cards)
        assert result["deleted"] == 1
        assert result["deleted_words"] == ["hello"]
        assert result["not_found"] == ["missing"]

    def test_empty_list_raises(self):
        cards = _FakeCardsStore([])
        from kg.exceptions import ValidationError

        with pytest.raises(ValidationError):
            batch_delete_vocab_words([], cards_store=cards)

    def test_with_graph(self):
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="hello"),
            _FakeCard(id="c2", content="world"),
        ])
        graph = _FakeArchiveGraph()
        result = batch_delete_vocab_words(["hello", "world"], cards_store=cards, graph=graph)
        assert result["deleted"] == 2
        assert set(graph.deprecated_for) == {"c1", "c2"}

    def test_duplicate_request_word_only_deletes_once(self, tmp_path):
        from kg.cards import CardStore

        cards = CardStore(tmp_path / "cards.db")
        card = cards.add("hello", meaning="m", notebook_id="default")
        graph = _FakeArchiveGraph()

        result = batch_delete_vocab_words(
            ["hello", "hello"], cards_store=cards, graph=graph,
        )

        assert result["deleted"] == 1
        assert result["deleted_words"] == ["hello"]
        assert result["not_found"] == []
        assert graph.deprecated_for == [card.id]

    def test_canonical_duplicate_variants_all_converge_but_delete_once(self, tmp_path):
        from kg.cards import CardStore

        cards = CardStore(tmp_path / "cards.db")
        card = cards.add("hello", meaning="m", notebook_id="default")
        graph = _FakeArchiveGraph()

        result = batch_delete_vocab_words(
            ["Hello.", "hello"], cards_store=cards, graph=graph,
        )

        assert result["deleted"] == 2
        assert result["deleted_words"] == ["Hello.", "hello"]
        assert result["not_found"] == []
        assert graph.deprecated_for == [card.id]


class TestBatchArchiveVocabWords:
    def test_archives_multiple_words(self):
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="hello"),
            _FakeCard(id="c2", content="world"),
        ])
        result = batch_archive_vocab_words(["hello", "world"], archived=True, cards_store=cards)
        assert result["updated"] == 2
        assert result["not_found"] == []

    def test_unarchive_multiple(self):
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="hello", is_archived=True),
            _FakeCard(id="c2", content="world", is_archived=True),
        ])
        graph = _FakeArchiveGraph()
        result = batch_archive_vocab_words(["hello", "world"], archived=False, cards_store=cards, graph=graph)
        assert result["updated"] == 2
        assert set(graph.restored_for) == {"c1", "c2"}

    def test_duplicate_request_word_only_archives_once(self, tmp_path):
        from kg.cards import CardStore

        cards = CardStore(tmp_path / "cards.db")
        card = cards.add("hello", meaning="m", notebook_id="default")
        graph = _FakeArchiveGraph()

        result = batch_archive_vocab_words(
            ["hello", "hello"], archived=True, cards_store=cards, graph=graph,
        )

        assert result["updated"] == 1
        assert result["updated_words"] == ["hello"]
        assert result["not_found"] == []
        assert graph.deprecated_for == [card.id]
        assert cards.get(card.id).is_archived is True

    def test_canonical_duplicate_variants_all_converge_but_archive_once(self, tmp_path):
        from kg.cards import CardStore

        cards = CardStore(tmp_path / "cards.db")
        card = cards.add("hello", meaning="m", notebook_id="default")
        graph = _FakeArchiveGraph()

        result = batch_archive_vocab_words(
            ["Hello.", "hello"], archived=True, cards_store=cards, graph=graph,
        )

        assert result["updated"] == 2
        assert result["updated_words"] == ["Hello.", "hello"]
        assert result["not_found"] == []
        assert graph.deprecated_for == [card.id]
        assert cards.get(card.id).is_archived is True

    def test_partial_not_found(self):
        cards = _FakeCardsStore([_FakeCard(id="c1", content="hello")])
        result = batch_archive_vocab_words(["hello", "missing"], archived=True, cards_store=cards)
        assert result["updated"] == 1
        assert result["not_found"] == ["missing"]

    def test_empty_list_raises(self):
        cards = _FakeCardsStore([])
        from kg.exceptions import ValidationError

        with pytest.raises(ValidationError):
            batch_archive_vocab_words([], archived=True, cards_store=cards)


class TestBatchDeleteNotebookIsolation:
    def test_same_word_in_other_notebook_untouched(self, tmp_path):
        from kg.cards import CardStore

        cards = CardStore(tmp_path / "cards.db")
        nb_a = cards.add("hello", meaning="m", notebook_id="nb_a")
        nb_b = cards.add("hello", meaning="m", notebook_id="nb_b")

        result = batch_delete_vocab_words(
            ["hello"], cards_store=cards, notebook_id="nb_a",
        )

        assert result["deleted"] == 1
        assert result["deleted_words"] == ["hello"]
        assert cards.get(nb_a.id).is_deleted is True
        assert cards.get(nb_b.id).is_deleted is False
