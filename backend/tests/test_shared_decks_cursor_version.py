"""Regression coverage for immutable shared-deck card cursor versions."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from conftest import TEST_JWT_SECRET, _swap_settings
from kg.api import app
from kg.settings import KGSettings
from kg.shared_decks.cursor import decode_cursor
from kg.shared_decks.store import SharedDeck, SharedDeckCard, SharedDeckStore, SharedDeckVersion


def _seed_deck(store: SharedDeckStore) -> None:
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    with Session(store.engine) as session:
        session.add(
            SharedDeck(
                id="deck-x",
                title="Deck X",
                title_nfc_lower="deck x",
                source="official",
                visibility="official",
                status="active",
                current_version=1,
                card_count=2,
                updated_at=now,
                created_at=now,
            )
        )
        session.add(SharedDeckVersion(shared_deck_id="deck-x", version=1, content_hash="v1"))
        session.add_all(
            [
                SharedDeckCard(
                    id="old-1",
                    shared_deck_id="deck-x",
                    version=1,
                    content_guid="g-old-1",
                    content="old-1",
                    meaning="old-1",
                ),
                SharedDeckCard(
                    id="old-2",
                    shared_deck_id="deck-x",
                    version=1,
                    content_guid="g-old-2",
                    content="old-2",
                    meaning="old-2",
                ),
            ]
        )
        session.commit()


def _publish_v2(store: SharedDeckStore) -> None:
    now = datetime(2026, 8, 21, 12, 1, tzinfo=UTC)
    with Session(store.engine) as session:
        deck = session.get(SharedDeck, "deck-x")
        assert deck is not None
        deck.current_version = 2
        deck.card_count = 1
        deck.updated_at = now
        session.add(deck)
        session.add(SharedDeckVersion(shared_deck_id="deck-x", version=2, content_hash="v2"))
        session.add(
            SharedDeckCard(
                id="new-0",
                shared_deck_id="deck-x",
                version=2,
                content_guid="g-new-0",
                content="new-0",
                meaning="new-0",
            )
        )
        session.commit()


@pytest.fixture()
def api(tmp_path):
    (tmp_path / "users").mkdir()
    _swap_settings(KGSettings(data_dir=tmp_path, jwt_secret=TEST_JWT_SECRET))
    store = SharedDeckStore(tmp_path / "shared_decks.db")
    _seed_deck(store)
    client = TestClient(app, raise_server_exceptions=False)
    yield SimpleNamespace(client=client, store=store)
    client.close()
    assert client.is_closed
    store.close()


def test_cards_cursor_rejects_cursor_from_previous_deck_version(api):
    first = api.client.get("/api/decks/deck-x/cards?limit=1")
    assert first.status_code == 200, first.text
    cursor = first.json()["nextCursor"]
    assert cursor
    decoded = decode_cursor(cursor, TEST_JWT_SECRET)

    _publish_v2(api.store)

    stale = api.client.get(f"/api/decks/deck-x/cards?limit=1&cursor={cursor}")
    assert stale.status_code == 400, stale.text
    assert decoded == {"d": "deck-x", "id": "old-1", "k": "cards", "v": 1}

    current = api.client.get("/api/decks/deck-x/cards?limit=1")
    assert current.status_code == 200, current.text
    assert [card["content"] for card in current.json()["cards"]] == ["new-0"]
