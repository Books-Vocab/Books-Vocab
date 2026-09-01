"""Regression coverage for explicit empty shared-deck cursors."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from conftest import TEST_JWT_SECRET, _swap_settings
from kg.api import app
from kg.service_factories import clear_store_cache
from kg.settings import KGSettings
from kg.shared_decks.store import SharedDeck, SharedDeckCard, SharedDeckStore, SharedDeckVersion
from kg.text_utils import normalize_nfc_lower


@pytest.fixture()
def shared_decks_api(tmp_path):
    (tmp_path / "users").mkdir()
    original_settings = app.state.kg_settings
    _swap_settings(KGSettings(data_dir=tmp_path, jwt_secret=TEST_JWT_SECRET))
    clear_store_cache()
    store = SharedDeckStore(tmp_path / "shared_decks.db")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(store.engine) as session:
        session.add(
            SharedDeck(
                id="deck-a",
                title="A",
                title_nfc_lower=normalize_nfc_lower("A"),
                source="official",
                visibility="official",
                status="active",
                current_version=1,
                card_count=1,
                updated_at=now,
                created_at=now,
            )
        )
        session.add(SharedDeckVersion(shared_deck_id="deck-a", version=1, content_hash="h"))
        session.add(
            SharedDeckCard(
                id="deck-a-c0",
                shared_deck_id="deck-a",
                version=1,
                content_guid="g",
                content="word",
                meaning="meaning",
                mode="recognition",
            )
        )
        session.commit()

    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield SimpleNamespace(client=client)
    finally:
        client.close()
        store.close()
        clear_store_cache()
        app.state.kg_settings = original_settings


@pytest.mark.parametrize(
    "path",
    ["/api/decks", "/api/decks/deck-a/cards"],
)
def test_explicit_empty_cursor_is_rejected(shared_decks_api, path):
    response = shared_decks_api.client.get(path, params={"cursor": ""})

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Invalid cursor"
