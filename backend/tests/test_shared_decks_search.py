"""Regression coverage for the public shared-deck search contract."""

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
from kg.shared_decks.store import SharedDeck, SharedDeckStore
from kg.text_utils import normalize_nfc_lower


@pytest.fixture()
def shared_decks_api(tmp_path):
    (tmp_path / "users").mkdir()
    original_settings = app.state.kg_settings
    _swap_settings(KGSettings(data_dir=tmp_path, jwt_secret=TEST_JWT_SECRET))
    clear_store_cache()
    store = SharedDeckStore(tmp_path / "shared_decks.db")
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield SimpleNamespace(client=client, store=store)
    finally:
        client.close()
        store.close()
        clear_store_cache()
        app.state.kg_settings = original_settings


def _insert_deck(
    store: SharedDeckStore,
    deck_id: str,
    title: str,
    *,
    publisher: str | None = None,
    tags: list[str] | None = None,
) -> None:
    now = datetime(2026, 9, 13, tzinfo=UTC)
    with Session(store.engine) as session:
        session.add(
            SharedDeck(
                id=deck_id,
                title=title,
                title_nfc_lower=normalize_nfc_lower(title),
                publisher_display_name=publisher,
                tags=tags or [],
                source="official",
                visibility="official",
                status="active",
                updated_at=now,
                created_at=now,
            )
        )
        session.commit()


@pytest.mark.parametrize(
    ("query", "expected_id"),
    [("  CORE ", "deck-title"), ("  LANGUAGE ", "deck-author"), ("ACADEMIC", "deck-tag")],
)
def test_deck_search_matches_explore_title_author_and_tag_semantics(shared_decks_api, query, expected_id):
    _insert_deck(shared_decks_api.store, "deck-title", "Core Search")
    _insert_deck(shared_decks_api.store, "deck-author", "Unrelated Title", publisher="Language Lab")
    _insert_deck(shared_decks_api.store, "deck-tag", "Another Title", tags=["academic"])

    response = shared_decks_api.client.get("/api/decks", params={"q": query})

    assert response.status_code == 200, response.text
    assert [deck["deckId"] for deck in response.json()["decks"]] == [expected_id]


def test_deck_search_cursor_paginates_the_combined_match_set(shared_decks_api):
    _insert_deck(shared_decks_api.store, "deck-title", "Topic Title")
    _insert_deck(shared_decks_api.store, "deck-author", "Unrelated Title", publisher="Topic Lab")
    _insert_deck(shared_decks_api.store, "deck-tag", "Another Title", tags=["topic"])

    first = shared_decks_api.client.get("/api/decks", params={"q": "topic", "limit": 1})
    second = shared_decks_api.client.get(
        "/api/decks",
        params={"q": "topic", "limit": 1, "cursor": first.json()["nextCursor"]},
    )
    third = shared_decks_api.client.get(
        "/api/decks",
        params={"q": "topic", "limit": 1, "cursor": second.json()["nextCursor"]},
    )

    assert first.status_code == second.status_code == third.status_code == 200
    assert first.json()["nextCursor"]
    assert second.json()["nextCursor"]
    assert third.json()["nextCursor"] is None
    assert {deck["deckId"] for response in (first, second, third) for deck in response.json()["decks"]} == {
        "deck-title",
        "deck-author",
        "deck-tag",
    }


def test_deck_search_does_not_match_json_syntax_in_tags(shared_decks_api):
    _insert_deck(shared_decks_api.store, "deck-tag", "Academic", tags=["academic"])

    response = shared_decks_api.client.get("/api/decks", params={"q": "["})

    assert response.status_code == 200, response.text
    assert response.json()["decks"] == []
