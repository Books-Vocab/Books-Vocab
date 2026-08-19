from __future__ import annotations

from types import SimpleNamespace

import pytest

from kg.vocab_crud import (
    archive_vocab_word,
    batch_archive_vocab_words,
    batch_delete_vocab_words,
    delete_vocab_word,
    lookup_vocab_word,
)
from kg.vocab_shared import _normalize_word
from test_vocab_service import (
    _card_builder,
    _FakeArchiveGraph,
    _FakeCard,
    _FakeCardsStore,
    _FakeEmbeddingStore,
    _PartialFailingGraph,
)


def test_normalize_word_nfc():
    import unicodedata

    precomposed = unicodedata.normalize("NFC", "café")
    decomposed = unicodedata.normalize("NFD", "café")
    assert _normalize_word(precomposed) == _normalize_word(decomposed)


def test_lookup_vocab_word_unicode_normalized():
    import unicodedata

    precomposed = unicodedata.normalize("NFC", "café")
    decomposed = unicodedata.normalize("NFD", "café")
    cards = _FakeCardsStore([_FakeCard(id="c1", content=precomposed)])
    result = lookup_vocab_word(decomposed, cards_store=cards, graph=SimpleNamespace(get_links_for=lambda card_id: []), card_response_builder=_card_builder)
    assert result["id"] == "c1"


class TestArchiveVocabWord:
    def test_archive_rolls_back_on_graph_failure(self):
        """If graph.cleanup_for_card raises, the card's is_archived must roll
        back to its original value and the error re-raises (mirrors
        delete_vocab_word's rollback-then-reraise contract)."""
        card = _FakeCard(id="c1", content="hello", is_archived=False)
        cards = _FakeCardsStore([card])

        class _FailingGraph(_FakeArchiveGraph):
            def cleanup_for_card(self, card_id, *, remove_blocked=False, source="auto"):
                raise RuntimeError("graph write failed")

        with pytest.raises(RuntimeError):
            archive_vocab_word("hello", archived=True, cards_store=cards, graph=_FailingGraph())

        assert card.is_archived is False, "is_archived not rolled back after graph failure"

    def test_unarchive_rolls_back_on_graph_failure(self):
        """Unarchive path: restore_links_for failure rolls is_archived back to
        True (original) and re-raises."""
        card = _FakeCard(id="c1", content="hello", is_archived=True)
        cards = _FakeCardsStore([card])

        class _FailingGraph(_FakeArchiveGraph):
            def restore_links_for(self, card_id, cards_store, *, source="auto"):
                raise RuntimeError("graph restore failed")

        with pytest.raises(RuntimeError):
            archive_vocab_word("hello", archived=False, cards_store=cards, graph=_FailingGraph())

        assert card.is_archived is True, "is_archived not rolled back after graph failure"


def test_delete_rolls_back_on_graph_failure(tmp_path):
    """If graph operations fail, card deletion must be rolled back."""
    from kg.cards import CardStore

    cards_store = CardStore(tmp_path / "cards.db")
    card = cards_store.add("testword", meaning="test meaning", notebook_id="default")
    card_id = card.id

    class _FailingGraph:
        def deprecate_links_for(self, cid, *, source="auto"):
            raise RuntimeError("graph write failed")

        def remove_candidates_for(self, cid):
            pass

        def cleanup_for_card(self, cid, *, remove_blocked=False, source="auto"):
            self.deprecate_links_for(cid)
            self.remove_candidates_for(cid)

    with pytest.raises(RuntimeError):
        delete_vocab_word("testword", cards_store=cards_store, graph=_FailingGraph())

    restored = cards_store.get(card_id)
    assert not restored.is_deleted


class TestBatchDeleteVocabWords:
    def test_graph_failure_routes_to_failed_not_not_found(self):
        """When graph cleanup raises, the card is restored (still exists on the
        server) and the word must go to the `failed` bucket, NOT `not_found`.
        `not_found` retains its pure meaning: lookup miss only. iOS treats
        `not_found` as 'server no longer has it -> converge/remove locally', so a
        graph-failed (still-existing) word must never appear there."""
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="hello"),
            _FakeCard(id="c2", content="world"),
            _FakeCard(id="c3", content="foo"),
        ])

        class _FailSecondGraph(_FakeArchiveGraph):
            def cleanup_for_card(self, card_id, *, remove_blocked=False, source="auto"):
                if card_id == "c2":
                    raise RuntimeError("graph boom")
                return super().cleanup_for_card(card_id, remove_blocked=remove_blocked)

        graph = _FailSecondGraph()
        result = batch_delete_vocab_words(
            ["hello", "world", "missing", "foo"], cards_store=cards, graph=graph
        )

        assert result["deleted"] == 2
        assert set(result["deleted_words"]) == {"hello", "foo"}
        assert result["failed"] == ["world"]
        assert result["not_found"] == ["missing"]


class TestBatchArchiveVocabWords:
    def test_archive_rolls_back_on_graph_failure(self):
        """If graph.cleanup_for_card raises for one card, that card's is_archived
        is rolled back to its original value, the word goes to `failed` (the card
        still exists on the server), the rest succeed, and the function does not
        raise. `not_found` must stay empty here (no lookup miss)."""
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="hello"),
            _FakeCard(id="c2", content="world"),
            _FakeCard(id="c3", content="foo"),
        ])

        class _FailSecondGraph(_FakeArchiveGraph):
            def cleanup_for_card(self, card_id, *, remove_blocked=False, source="auto"):
                if card_id == "c2":
                    raise RuntimeError("graph boom")
                return super().cleanup_for_card(card_id, remove_blocked=remove_blocked)

        graph = _FailSecondGraph()
        result = batch_archive_vocab_words(
            ["hello", "world", "foo"], archived=True, cards_store=cards, graph=graph
        )

        assert result["updated"] == 2
        assert set(result["updated_words"]) == {"hello", "foo"}
        assert result["failed"] == ["world"]
        assert result["not_found"] == []
        assert cards.get("c1").is_archived is True
        assert cards.get("c2").is_archived is False
        assert cards.get("c3").is_archived is True

    def test_unarchive_rolls_back_on_graph_failure(self):
        """Unarchive path: restore_links_for failure rolls is_archived back to
        its original True value."""
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="hello", is_archived=True),
            _FakeCard(id="c2", content="world", is_archived=True),
        ])

        class _FailRestoreGraph(_FakeArchiveGraph):
            def restore_links_for(self, card_id, cards_store, *, source="auto"):
                if card_id == "c2":
                    raise RuntimeError("restore boom")
                return super().restore_links_for(card_id, cards_store)

        graph = _FailRestoreGraph()
        result = batch_archive_vocab_words(
            ["hello", "world"], archived=False, cards_store=cards, graph=graph
        )

        assert result["updated"] == 1
        assert result["updated_words"] == ["hello"]
        assert result["failed"] == ["world"]
        assert result["not_found"] == []
        assert cards.get("c1").is_archived is False
        assert cards.get("c2").is_archived is True


class TestBatchDeleteCaseInsensitive:
    """batch_delete_vocab_words must match words case-insensitively."""

    def test_case_insensitive_match(self):
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="Hello"),
            _FakeCard(id="c2", content="WORLD"),
        ])
        result = batch_delete_vocab_words(["hello", "world"], cards_store=cards)
        assert result["deleted"] == 2
        assert set(result["deleted_words"]) == {"hello", "world"}
        assert result["not_found"] == []

    def test_nfc_normalization(self):
        import unicodedata

        nfc = unicodedata.normalize("NFC", "café")
        nfd = unicodedata.normalize("NFD", "café")
        cards = _FakeCardsStore([_FakeCard(id="c1", content=nfd)])
        result = batch_delete_vocab_words([nfc], cards_store=cards)
        assert result["deleted"] == 1

    def test_matches_cleaned_storage_content(self, tmp_path):
        from kg.cards import CardStore

        cards = CardStore(tmp_path / "cards.db")
        card = cards.add("chateau", meaning="莊園", notebook_id="default")

        result = batch_delete_vocab_words(["chateau,"], cards_store=cards)

        assert result["deleted"] == 1
        assert result["deleted_words"] == ["chateau,"]
        assert result["not_found"] == []
        assert cards.get(card.id).is_deleted is True

    def test_no_find_by_content_calls(self):
        """After N+1 fix, batch_delete should use all() not find_by_content."""
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="hello"),
            _FakeCard(id="c2", content="world"),
        ])
        call_count = 0
        original_find = cards.find_by_content

        def counting_find(*a, **kw):
            nonlocal call_count
            call_count += 1
            return original_find(*a, **kw)

        cards.find_by_content = counting_find
        batch_delete_vocab_words(["hello", "world"], cards_store=cards)
        assert call_count == 0, f"find_by_content called {call_count} times, expected 0"


class TestBatchArchiveCaseInsensitive:
    """batch_archive_vocab_words must match words case-insensitively."""

    def test_case_insensitive_match(self):
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="Hello"),
            _FakeCard(id="c2", content="WORLD"),
        ])
        result = batch_archive_vocab_words(["hello", "world"], archived=True, cards_store=cards)
        assert result["updated"] == 2
        assert result["not_found"] == []

    def test_nfc_normalization(self):
        import unicodedata

        nfc = unicodedata.normalize("NFC", "café")
        nfd = unicodedata.normalize("NFD", "café")
        cards = _FakeCardsStore([_FakeCard(id="c1", content=nfd)])
        result = batch_archive_vocab_words([nfc], archived=True, cards_store=cards)
        assert result["updated"] == 1

    def test_matches_cleaned_storage_content(self, tmp_path):
        from kg.cards import CardStore

        cards = CardStore(tmp_path / "cards.db")
        card = cards.add("chateau", meaning="莊園", notebook_id="default")

        result = batch_archive_vocab_words(["chateau,"], archived=True, cards_store=cards)

        assert result["updated"] == 1
        assert result["updated_words"] == ["chateau,"]
        assert result["not_found"] == []
        assert cards.get(card.id).is_archived is True

    def test_no_find_by_content_calls(self):
        """After N+1 fix, batch_archive should use all() not find_by_content."""
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="hello"),
            _FakeCard(id="c2", content="world"),
        ])
        call_count = 0
        original_find = cards.find_by_content

        def counting_find(*a, **kw):
            nonlocal call_count
            call_count += 1
            return original_find(*a, **kw)

        cards.find_by_content = counting_find
        batch_archive_vocab_words(["hello", "world"], archived=True, cards_store=cards)
        assert call_count == 0, f"find_by_content called {call_count} times, expected 0"


class TestDeleteEvictsEmbedding:
    def test_delete_vocab_word_removes_embedding(self):
        cards = _FakeCardsStore([_FakeCard(id="c1", content="evoke")])
        graph = _FakeArchiveGraph()
        emb = _FakeEmbeddingStore(ids=["c1"])
        delete_vocab_word(
            "evoke", cards_store=cards, graph=graph, embeddings=emb,
        )
        assert emb.removed == ["c1"]

    def test_delete_vocab_word_without_embeddings_still_works(self):
        """embeddings stays optional — old call sites must not break."""
        cards = _FakeCardsStore([_FakeCard(id="c1", content="evoke")])
        result = delete_vocab_word("evoke", cards_store=cards)
        assert (result.deleted, result.id) == ("evoke", "c1")

    def test_delete_rollback_does_not_evict_embedding(self, tmp_path):
        """If graph cleanup fails and the card is restored, the vector must
        NOT be evicted — otherwise a restored card loses its embedding."""
        from kg.cards import CardStore

        cards_store = CardStore(tmp_path / "cards.db")
        card = cards_store.add("testword", meaning="m", notebook_id="default")
        emb = _FakeEmbeddingStore(ids=[card.id])

        class _FailingGraph:
            def cleanup_for_card(self, cid, *, remove_blocked=False, source="auto"):
                raise RuntimeError("graph write failed")

        with pytest.raises(RuntimeError):
            delete_vocab_word(
                "testword", cards_store=cards_store,
                graph=_FailingGraph(), embeddings=emb,
            )
        assert emb.removed == [], "embedding evicted despite rollback"
        assert not cards_store.get(card.id).is_deleted

    def test_batch_delete_removes_embeddings(self):
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="hello"),
            _FakeCard(id="c2", content="world"),
            _FakeCard(id="c3", content="keep"),
        ])
        graph = _FakeArchiveGraph()
        emb = _FakeEmbeddingStore(ids=["c1", "c2", "c3"])
        batch_delete_vocab_words(
            ["hello", "world"], cards_store=cards, graph=graph, embeddings=emb,
        )
        assert set(emb.removed) == {"c1", "c2"}
        assert "c3" not in emb.removed

    def test_batch_delete_without_embeddings_still_works(self):
        cards = _FakeCardsStore([
            _FakeCard(id="c1", content="hello"),
            _FakeCard(id="c2", content="world"),
        ])
        result = batch_delete_vocab_words(["hello", "world"], cards_store=cards)
        assert result["deleted"] == 2


class TestBatchDeleteGraphFailureBranch:
    def test_second_card_graph_failure_rolls_back_only_that_card(self, tmp_path):
        """When cleanup_for_card raises on the 2nd word, that word lands in
        `failed` (NOT not_found — the card was restored and still exists), its
        card is restored, and remove_batch receives only the successful id."""
        from kg.cards import CardStore

        cards = CardStore(tmp_path / "cards.db")
        c1 = cards.add("hello", meaning="m", notebook_id="default")
        c2 = cards.add("world", meaning="m", notebook_id="default")

        graph = _PartialFailingGraph(fail_for=c2.id)
        emb = _FakeEmbeddingStore(ids=[c1.id, c2.id])

        result = batch_delete_vocab_words(
            ["hello", "world"], cards_store=cards, graph=graph, embeddings=emb,
        )

        assert result["deleted"] == 1
        assert result["deleted_words"] == ["hello"]
        assert result["failed"] == ["world"]
        assert result["not_found"] == []
        assert cards.get(c1.id).is_deleted is True
        assert cards.get(c2.id).is_deleted is False
        assert emb.removed == [c1.id]

    def test_all_cards_fail_graph_yields_empty_delete(self, tmp_path):
        from kg.cards import CardStore

        cards = CardStore(tmp_path / "cards.db")
        c1 = cards.add("hello", meaning="m", notebook_id="default")

        graph = _PartialFailingGraph(fail_for=c1.id)
        emb = _FakeEmbeddingStore(ids=[c1.id])

        result = batch_delete_vocab_words(
            ["hello"], cards_store=cards, graph=graph, embeddings=emb,
        )
        assert result["deleted"] == 0
        assert result["failed"] == ["hello"]
        assert result["not_found"] == []
        assert cards.get(c1.id).is_deleted is False
        assert emb.removed == []
