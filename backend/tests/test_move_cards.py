from __future__ import annotations
import pytest
from kg.cards import CardStore
from kg.vocab_service import move_vocab_words

@pytest.fixture
def store(tmp_path):
    return CardStore(tmp_path / "cards.db")

def test_move_cards_basic(store):
    c1 = store.add("apple", "蘋果", notebook_id="nb1")
    c2 = store.add("book", "書", notebook_id="nb1")
    store.add("cat", "貓", notebook_id="nb1")
    moved = store.move_cards(["apple", "book"], from_notebook_id="nb1", to_notebook_id="nb2")
    assert moved == 2
    updated = store.find_by_content("apple", notebook_id="nb2")
    assert updated is not None
    assert updated.notebook_id == "nb2"
    cat = store.find_by_content("cat", notebook_id="nb1")
    assert cat is not None

def test_move_cards_skips_deleted(store):
    c1 = store.add("apple", "蘋果", notebook_id="nb1")
    store.delete(c1.id)
    moved = store.move_cards(["apple"], from_notebook_id="nb1", to_notebook_id="nb2")
    assert moved == 0

def test_move_cards_word_not_found(store):
    store.add("apple", "蘋果", notebook_id="nb1")
    moved = store.move_cards(["nonexistent"], from_notebook_id="nb1", to_notebook_id="nb2")
    assert moved == 0

def test_move_cards_empty_list(store):
    moved = store.move_cards([], from_notebook_id="nb1", to_notebook_id="nb2")
    assert moved == 0


class _FakeCardsStore:
    def __init__(self):
        self.moved = None
        self._cards = {}
    def move_cards(self, words, from_notebook_id, to_notebook_id):
        self.moved = (words, from_notebook_id, to_notebook_id)
        return len(words)
    def find_by_content(self, word, notebook_id=None):
        from types import SimpleNamespace
        return self._cards.get(word, SimpleNamespace(id=f"id_{word}"))


class _FakeGraphStore:
    def __init__(self):
        self.deprecated = []
        self.removed = []
    def deprecate_links_for(self, card_id):
        self.deprecated.append(card_id)
        return 1
    def remove_candidates_for(self, card_id):
        self.removed.append(card_id)
        return 0


def test_move_vocab_words_service():
    cards = _FakeCardsStore()
    src_graph = _FakeGraphStore()
    result = move_vocab_words(
        words=["apple", "book"],
        from_notebook_id="nb1",
        to_notebook_id="nb2",
        cards_store=cards,
        source_graph=src_graph,
        target_graph=None,
    )
    assert result == {"moved": 2}
    assert cards.moved == (["apple", "book"], "nb1", "nb2")


def test_move_vocab_words_empty():
    from fastapi import HTTPException
    cards = _FakeCardsStore()
    with pytest.raises(HTTPException) as exc_info:
        move_vocab_words(
            words=[],
            from_notebook_id="nb1",
            to_notebook_id="nb2",
            cards_store=cards,
            source_graph=None,
        )
    assert exc_info.value.status_code == 422
