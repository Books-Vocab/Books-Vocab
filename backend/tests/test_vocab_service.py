from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from kg.vocab_crud import (
    archive_vocab_word,
    batch_archive_vocab_words,
    batch_delete_vocab_words,
    delete_vocab_word,
    list_vocab_cards,
    lookup_vocab_word,
)
from kg.vocab_graph import graph_links_payload
from kg.vocab_intake import add_vocab_entries
from kg.vocab_shared import MAX_BATCH_SIZE, MAX_WORD_LENGTH, _normalize_word


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


def test_list_lookup_and_delete_vocab_helpers():
    cards = _FakeCardsStore([_FakeCard(id="c1", content="evoke"), _FakeCard(id="c2", content="lucid")])
    graph = SimpleNamespace(get_links_for=lambda card_id: [])

    listed = list_vocab_cards(since=None, cards_store=cards, graph=graph, card_response_builder=_card_builder)
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


# ---------------------------------------------------------------------------
# Task 1: 批次大小限制
# ---------------------------------------------------------------------------

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


def test_add_vocab_entries_rejects_oversized_batch():
    from kg.api_models import VocabEntry
    entries = [VocabEntry(word=f"word{i}", translation="t", context="c") for i in range(MAX_BATCH_SIZE + 1)]
    from kg.exceptions import ValidationError
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


# ---------------------------------------------------------------------------
# Task 2: Word 長度驗證
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 4: Unicode 正規化
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# archive_vocab_word 整合圖譜操作
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# delete_vocab_word rollback on graph failure
# ---------------------------------------------------------------------------

def test_delete_rolls_back_on_graph_failure(tmp_path):
    """If graph operations fail, card deletion must be rolled back."""
    import pytest

    from kg.cards import CardStore
    from kg.vocab_crud import delete_vocab_word

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

    # Card should NOT be deleted since graph failed
    restored = cards_store.get(card_id)
    assert not restored.is_deleted


# ---------------------------------------------------------------------------
# batch_delete_vocab_words
# ---------------------------------------------------------------------------

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
        # graph-failed word -> failed (restored, still exists), not not_found
        assert result["failed"] == ["world"]
        # not_found is pure lookup-miss only
        assert result["not_found"] == ["missing"]


# ---------------------------------------------------------------------------
# batch_archive_vocab_words
# ---------------------------------------------------------------------------

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
        # c2 rolled back to original (False); the rest archived.
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
        # c2 rolled back to original archived state (True).
        assert cards.get("c2").is_archived is True

    def test_empty_list_raises(self):
        cards = _FakeCardsStore([])
        from kg.exceptions import ValidationError
        with pytest.raises(ValidationError):
            batch_archive_vocab_words([], archived=True, cards_store=cards)


# ---------------------------------------------------------------------------
# N+1 fix: batch operations use bulk lookup instead of per-word find_by_content
# ---------------------------------------------------------------------------

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
        # café in NFC vs NFD
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


# ---------------------------------------------------------------------------
# Bug A: deleting a card must also evict its embedding vector
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Task 2 (incremental query): 增量查詢優化
# ---------------------------------------------------------------------------

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
    results = list_vocab_cards(since=since_str, cards_store=cards, graph=graph,
                               card_response_builder=builder, notebook_id=None)

    assert len(results) == 1
    assert results[0].content == "fruit"
    assert "shares_usage" in results[0].linksByKind
    assert results[0].linksByKind["shares_usage"][0].word == "apple"


# ---------------------------------------------------------------------------
# batch_delete_vocab_words graph-failure rollback branch (vocab_crud.py:156-165)
# ---------------------------------------------------------------------------
# Uses a real CardStore so soft-delete / restore / notebook_id all behave
# authentically — the lightweight _FakeCardsStore cannot model restore().


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


class TestBatchDeleteGraphFailureBranch:
    def test_second_card_graph_failure_rolls_back_only_that_card(self, tmp_path):
        """When cleanup_for_card raises on the 2nd word, that word lands in
        `failed` (NOT not_found — the card was restored and still exists), its
        card is restored (not soft-deleted), and remove_batch receives only the
        successfully-deleted id. See #720."""
        from kg.cards import CardStore

        cards = CardStore(tmp_path / "cards.db")
        c1 = cards.add("hello", meaning="m", notebook_id="default")
        c2 = cards.add("world", meaning="m", notebook_id="default")

        graph = _PartialFailingGraph(fail_for=c2.id)
        emb = _FakeEmbeddingStore(ids=[c1.id, c2.id])

        result = batch_delete_vocab_words(
            ["hello", "world"], cards_store=cards, graph=graph, embeddings=emb,
        )

        # "world" failed graph cleanup → reported as failed (still exists),
        # not not_found
        assert result["deleted"] == 1
        assert result["deleted_words"] == ["hello"]
        assert result["failed"] == ["world"]
        assert result["not_found"] == []

        # c1 soft-deleted, c2 restored to active
        assert cards.get(c1.id).is_deleted is True
        assert cards.get(c2.id).is_deleted is False

        # embeddings evicted only for the committed-deleted card
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
        # nothing committed → remove_batch never evicts (guarded by deleted_ids)
        assert emb.removed == []


# ---------------------------------------------------------------------------
# Cross-notebook CardStore isolation: batch_delete scoped by notebook_id must
# not touch a same-named card living in another notebook.
# ---------------------------------------------------------------------------


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
        # only nb_a's card is gone; nb_b's identically-named card survives
        assert cards.get(nb_a.id).is_deleted is True
        assert cards.get(nb_b.id).is_deleted is False
