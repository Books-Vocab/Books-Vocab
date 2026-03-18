from __future__ import annotations
import pytest
from kg.cards import CardStore

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
