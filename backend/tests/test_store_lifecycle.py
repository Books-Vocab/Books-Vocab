"""Tests for store lifecycle (open/close)."""
import pytest
from pathlib import Path
from kg.cards import CardStore
from kg.notebook import NotebookStore
from kg.daily_stats import DailyReviewStatsStore


def test_card_store_close_disposes_engine(tmp_path: Path):
    store = CardStore(tmp_path / "cards.db")
    store.add("hello", "你好")
    store.close()
    assert store.engine is None


def test_card_store_double_close_is_safe(tmp_path: Path):
    store = CardStore(tmp_path / "cards.db")
    store.close()
    store.close()  # should not raise


def test_notebook_store_close(tmp_path: Path):
    store = NotebookStore(tmp_path / "notebooks.db")
    store.close()
    assert store.engine is None


def test_daily_stats_store_close(tmp_path: Path):
    store = DailyReviewStatsStore(tmp_path / "stats.db")
    store.close()
    assert store.engine is None
