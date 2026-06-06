"""Tests for store lifecycle (open/close)."""
from pathlib import Path

from kg.cards import CardStore
from kg.notebook import NotebookStore
from kg.review_events import ReviewEventStore


def test_card_store_close_disposes_engine(tmp_path: Path):
    store = CardStore(tmp_path / "cards.db")
    store.add("hello", "你好")
    store.close()
    assert store.engine is None


def test_card_store_double_close_is_safe(tmp_path: Path):
    store = CardStore(tmp_path / "cards.db")
    store.close()
    store.close()  # should not raise
    assert store.engine is None


def test_notebook_store_close(tmp_path: Path):
    store = NotebookStore(tmp_path / "notebooks.db")
    store.close()
    assert store.engine is None


def test_review_event_store_close(tmp_path: Path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    store.close()
    assert store.engine is None
