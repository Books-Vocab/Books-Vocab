"""Tests for VocabSource field on VocabEntry, Card, and CardResponse."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from kg.api_models import CardResponse, VocabEntry, VocabSource


def test_vocab_entry_accepts_source():
    """VocabEntry with source={type:'web', title, url} should parse correctly."""
    entry = VocabEntry(
        word="hello",
        translation="你好",
        source=VocabSource(type="web", title="Example Page", url="https://example.com"),
    )
    assert entry.source is not None
    assert entry.source.type == "web"
    assert entry.source.title == "Example Page"
    assert entry.source.url == "https://example.com"
    assert entry.source.chapter is None


def test_vocab_entry_source_optional():
    """VocabEntry without source should default to None."""
    entry = VocabEntry(word="hello", translation="你好")
    assert entry.source is None


def test_card_model_has_source_column():
    """CardStore.add with source JSON should persist and retrieve correctly."""
    from kg.cards import CardStore

    with TemporaryDirectory() as tmpdir:
        store = CardStore(Path(tmpdir) / "test.db")
        source_data = json.dumps({"type": "web", "title": "Test", "url": "https://test.com"})
        card = store.add(content="hello", meaning="你好", source=source_data)
        assert card.source == source_data

        retrieved = store.get(card.id)
        assert retrieved is not None
        assert retrieved.source == source_data
        parsed = json.loads(retrieved.source)
        assert parsed["type"] == "web"
        assert parsed["url"] == "https://test.com"


def test_card_response_includes_source():
    """CardResponse should accept and expose a VocabSource field."""
    src = VocabSource(type="book", title="My Book", chapter="Ch. 1")
    resp = CardResponse(
        id="abc123",
        content="hello",
        meaning="你好",
        pos=None,
        difficulty=None,
        difficultyTier=None,
        note=None,
        examples=[],
        mode="recognition",
        isDeleted=False,
        source=src,
    )
    assert resp.source is not None
    assert resp.source.type == "book"
    assert resp.source.chapter == "Ch. 1"


def test_card_response_source_none_by_default():
    """CardResponse without source should default to None."""
    resp = CardResponse(
        id="abc123",
        content="hello",
        meaning="你好",
        pos=None,
        difficulty=None,
        difficultyTier=None,
        note=None,
        examples=[],
        mode="recognition",
        isDeleted=False,
    )
    assert resp.source is None
