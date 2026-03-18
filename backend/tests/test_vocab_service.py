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
    delete_vocab_word,
    graph_links_payload,
    list_vocab_cards,
    lookup_vocab_word,
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

    with pytest.raises(HTTPException) as exc_info:
        list_vocab_cards(since="not-a-date", cards_store=cards, graph=object(), card_response_builder=_card_builder)

    assert exc_info.value.status_code == 400


def test_graph_links_payload_only_returns_active_links():
    graph = SimpleNamespace(
        _links={
            "l1": SimpleNamespace(id="l1", from_id="c1", to_id="c2", kind=SimpleNamespace(value="contrasts_with"), confidence=0.9, reason="r1", status="active"),
            "l2": SimpleNamespace(id="l2", from_id="c2", to_id="c3", kind=SimpleNamespace(value="shares_usage"), confidence=0.7, reason="r2", status="deprecated"),
        }
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

    def find_similar(self, card_id, k=3):
        return []


class _FakeGraph:
    def add_candidate(self, *args, **kwargs):
        pass


def test_add_vocab_entries_rejects_oversized_batch():
    from kg.api_models import VocabEntry
    entries = [VocabEntry(word=f"word{i}", translation="t", context="c") for i in range(MAX_BATCH_SIZE + 1)]
    with pytest.raises(HTTPException) as exc_info:
        add_vocab_entries(
            entries,
            user={"id": "u1"},
            cards=_FakeCards(),
            embeddings=_FakeEmbeddings(),
            graph=_FakeGraph(),
            logger=SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None),
        )
    assert exc_info.value.status_code == 422
    assert "500" in exc_info.value.detail


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
    with pytest.raises(HTTPException) as exc_info:
        lookup_vocab_word(long_word, cards_store=cards, graph=object(), card_response_builder=_card_builder)
    assert exc_info.value.status_code == 422


def test_delete_vocab_word_rejects_too_long():
    cards = _FakeCardsStore([_FakeCard(id="c1", content="evoke")])
    long_word = "a" * (MAX_WORD_LENGTH + 1)
    with pytest.raises(HTTPException) as exc_info:
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
