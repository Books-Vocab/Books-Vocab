from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from kg.vocab_service import (
    MAX_BATCH_SIZE,
    MAX_WORD_LENGTH,
    _normalize_word,
    add_vocab_entries,
    archive_vocab_word,
    batch_archive_vocab_words,
    batch_delete_vocab_words,
    delete_vocab_word,
    graph_links_payload,
    list_vocab_cards,
    lookup_vocab_word,
    move_vocab_words,
)


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

    def all_limited(self, limit: int = 5000, include_deleted: bool = False, notebook_id: str | None = None):
        cards = self.all(include_deleted=include_deleted)
        return cards[:limit]

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

    from kg.exceptions import BadRequestError
    with pytest.raises(BadRequestError) as exc_info:
        list_vocab_cards(since="not-a-date", cards_store=cards, graph=object(), card_response_builder=_card_builder)

    assert exc_info.value.status_code == 400


def test_graph_links_payload_only_returns_active_links():
    links = {
        "l1": SimpleNamespace(id="l1", from_id="c1", to_id="c2", kind=SimpleNamespace(value="contrasts_with"), confidence=0.9, reason="r1", status="active"),
        "l2": SimpleNamespace(id="l2", from_id="c2", to_id="c3", kind=SimpleNamespace(value="shares_usage"), confidence=0.7, reason="r2", status="deprecated"),
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
    def add_candidate(self, *args, **kwargs):
        pass

    def batch_add_candidates(self, items):
        return 0


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
    result = lookup_vocab_word(decomposed, cards_store=cards, graph=object(), card_response_builder=_card_builder)
    assert result["id"] == "c1"


# ---------------------------------------------------------------------------
# archive_vocab_word 整合圖譜操作
# ---------------------------------------------------------------------------

class _FakeArchiveGraph:
    def __init__(self):
        self.deprecated_for = []
        self.removed_candidates_for = []
        self.restored_for = []

    def deprecate_links_for(self, card_id):
        self.deprecated_for.append(card_id)
        return 1

    def remove_candidates_for(self, card_id):
        self.removed_candidates_for.append(card_id)
        return 0

    def restore_links_for(self, card_id, cards_store):
        self.restored_for.append(card_id)
        return 1


class TestArchiveVocabWord:
    def test_archive_deprecates_graph_links(self):
        card = _FakeCard(id="c1", content="hello")
        cards = _FakeCardsStore([card])
        graph = _FakeArchiveGraph()
        result = archive_vocab_word("hello", archived=True, cards_store=cards, graph=graph)
        assert result["archived"] is True
        assert graph.deprecated_for == ["c1"]
        assert graph.removed_candidates_for == ["c1"]

    def test_unarchive_restores_graph_links(self):
        card = _FakeCard(id="c1", content="hello")
        cards = _FakeCardsStore([card])
        graph = _FakeArchiveGraph()
        result = archive_vocab_word("hello", archived=False, cards_store=cards, graph=graph)
        assert result["archived"] is False
        assert graph.restored_for == ["c1"]

    def test_archive_without_graph_still_works(self):
        card = _FakeCard(id="c1", content="hello")
        cards = _FakeCardsStore([card])
        result = archive_vocab_word("hello", archived=True, cards_store=cards)
        assert result["archived"] is True


# ---------------------------------------------------------------------------
# delete_vocab_word rollback on graph failure
# ---------------------------------------------------------------------------

def test_delete_rolls_back_on_graph_failure(tmp_path):
    """If graph operations fail, card deletion must be rolled back."""
    from kg.cards import CardStore
    from kg.vocab_service import delete_vocab_word
    import pytest

    cards_store = CardStore(tmp_path / "cards.db")
    card = cards_store.add("testword", meaning="test meaning", notebook_id="default")
    card_id = card.id

    class _FailingGraph:
        def deprecate_links_for(self, cid):
            raise RuntimeError("graph write failed")
        def remove_candidates_for(self, cid):
            pass

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


class _FakeMoveCardsStore:
    """Fake store for move_vocab_words that supports all() and move_cards()."""
    def __init__(self, cards):
        self._cards = list(cards)
        self.moved = None

    def all(self, include_deleted=False, notebook_id=None):
        return [c for c in self._cards if not c.is_deleted]

    def move_cards(self, words, from_notebook_id, to_notebook_id):
        self.moved = (words, from_notebook_id, to_notebook_id)
        return len(words)

    def find_by_content(self, content, notebook_id=None):
        raise AssertionError("find_by_content should not be called")


class TestMoveVocabWordsNoNPlusOne:
    """move_vocab_words should not call find_by_content in a loop."""

    def test_no_find_by_content_calls(self):
        from test_move_cards import _FakeGraphStore
        cards = _FakeMoveCardsStore([
            _FakeCard(id="c1", content="apple"),
            _FakeCard(id="c2", content="book"),
        ])
        src_graph = _FakeGraphStore()
        call_count = 0
        original_find = cards.find_by_content
        def counting_find(*a, **kw):
            nonlocal call_count
            call_count += 1
            return original_find(*a, **kw)
        cards.find_by_content = counting_find
        move_vocab_words(
            words=["apple", "book"],
            from_notebook_id="nb1",
            to_notebook_id="nb2",
            cards_store=cards,
            source_graph=src_graph,
        )
        assert call_count == 0, f"find_by_content called {call_count} times, expected 0"
