"""Phase 1b-i: guest-browsable /api/decks (list / detail / cards).

Contract nailed here:
* guest (no bearer) can list + preview official decks;
* only discoverable decks surface (is_deleted=0, status=active, visibility in
  public/official) — a private/community deck must never appear;
* the badge (`isOfficial`) is driven by the server-set `source`, never client
  input;
* `DeckCard` is a content-plane subset with ZERO of the 7 SRS columns (a leak
  would be a security/privacy regression);
* pagination uses an opaque signed cursor; a tampered cursor is a 400.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from conftest import TEST_JWT_SECRET, _swap_settings
from kg.api import app
from kg.settings import KGSettings
from kg.shared_decks.store import (
    SharedDeck,
    SharedDeckCard,
    SharedDeckStore,
    SharedDeckVersion,
)
from kg.text_utils import normalize_nfc_lower

# The 7 SRS columns that must never appear in a DeckCard payload.
_SRS_KEYS = {
    "reviewIntervalHours", "review_interval_hours",
    "nextReviewAt", "next_review_at",
    "lastReviewedAt", "last_reviewed_at",
    "reviewCount", "review_count",
    "lapseCount", "lapse_count",
    "reviewStreak", "review_streak",
    "lastReviewFeedback", "last_review_feedback",
}


def _insert_deck(
    store, deck_id, title, *, source="official", visibility="official",
    status="active", is_deleted=False, cards=None, updated_at=None, version=1,
):
    cards = cards or []
    now = updated_at or datetime.now(UTC)
    with Session(store.engine) as s:
        s.add(SharedDeck(
            id=deck_id, owner_id=None, title=title,
            title_nfc_lower=normalize_nfc_lower(title),
            source=source, visibility=visibility, status=status,
            is_deleted=is_deleted, current_version=version,
            card_count=len(cards), category="language", language_pair="en-zh",
            updated_at=now, created_at=now,
        ))
        s.add(SharedDeckVersion(shared_deck_id=deck_id, version=version, content_hash="h"))
        for i, (content, meaning) in enumerate(cards):
            s.add(SharedDeckCard(
                id=f"{deck_id}-c{i:03d}", shared_deck_id=deck_id, version=version,
                content_guid=f"g-{deck_id}-{i}", content=content, meaning=meaning,
                mode="recognition",
            ))
        s.commit()


@pytest.fixture()
def api(tmp_path):
    (tmp_path / "users").mkdir()
    _swap_settings(KGSettings(data_dir=tmp_path, jwt_secret=TEST_JWT_SECRET))
    store = SharedDeckStore(tmp_path / "shared_decks.db")
    yield SimpleNamespace(
        client=TestClient(app, raise_server_exceptions=False),
        store=store,
        data_dir=tmp_path,
    )
    store.close()


def test_guest_lists_official_decks(api):
    _insert_deck(api.store, "deck_official", "Core 2000",
                 cards=[("apple", "蘋果"), ("book", "書")])
    r = api.client.get("/api/decks")  # NO auth header
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [d["deckId"] for d in body["decks"]]
    assert "deck_official" in ids
    deck = next(d for d in body["decks"] if d["deckId"] == "deck_official")
    assert deck["isOfficial"] is True
    assert deck["cardCount"] == 2


def test_private_and_community_decks_are_hidden(api):
    _insert_deck(api.store, "deck_pub", "Public", cards=[("a", "1")])
    _insert_deck(api.store, "deck_priv", "Private", visibility="private", cards=[("b", "2")])
    _insert_deck(api.store, "deck_removed", "Removed", status="removed", cards=[("c", "3")])
    _insert_deck(api.store, "deck_del", "Deleted", is_deleted=True, cards=[("d", "4")])
    ids = [d["deckId"] for d in api.client.get("/api/decks").json()["decks"]]
    assert ids == ["deck_pub"]


def test_deck_detail_returns_sample_cards_without_srs(api):
    _insert_deck(api.store, "deck_x", "Sampler",
                 cards=[("meticulous", "一絲不苟的"), ("plain", "平凡")])
    r = api.client.get("/api/decks/deck_x")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deckId"] == "deck_x"
    assert body["cardCount"] == 2
    assert len(body["sampleCards"]) >= 1
    card = body["sampleCards"][0]
    assert card["content"]
    assert "meaning" in card
    assert _SRS_KEYS.isdisjoint(card.keys()), f"SRS leaked: {_SRS_KEYS & card.keys()}"


def test_cards_endpoint_paginates_over_immutable_id(api):
    cards = [(f"w{i:03d}", f"m{i}") for i in range(5)]
    _insert_deck(api.store, "deck_big", "Big", cards=cards)
    r1 = api.client.get("/api/decks/deck_big/cards?limit=2")
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert len(b1["cards"]) == 2
    assert b1["nextCursor"]
    r2 = api.client.get(f"/api/decks/deck_big/cards?limit=2&cursor={b1['nextCursor']}")
    b2 = r2.json()
    seen = {c["content"] for c in b1["cards"]} | {c["content"] for c in b2["cards"]}
    assert len(seen) == 4  # no overlap across pages


def test_unknown_deck_is_404(api):
    assert api.client.get("/api/decks/nope").status_code == 404
    assert api.client.get("/api/decks/nope/cards").status_code == 404


def test_tampered_cursor_is_400(api):
    _insert_deck(api.store, "deck_c", "C", cards=[("a", "1")])
    assert api.client.get("/api/decks?cursor=garbage.sig").status_code == 400


def test_list_cursor_pages_decks_without_overlap(api):
    base = datetime.now(UTC)
    for i in range(4):
        _insert_deck(api.store, f"deck_{i}", f"Deck {i}",
                     cards=[("a", "1")], updated_at=base - timedelta(minutes=i))
    r1 = api.client.get("/api/decks?limit=2")
    b1 = r1.json()
    assert len(b1["decks"]) == 2
    assert b1["nextCursor"]
    r2 = api.client.get(f"/api/decks?limit=2&cursor={b1['nextCursor']}")
    b2 = r2.json()
    seen = {d["deckId"] for d in b1["decks"]} | {d["deckId"] for d in b2["decks"]}
    assert len(seen) == 4
