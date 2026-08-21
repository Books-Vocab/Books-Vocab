from datetime import UTC, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from conftest import _swap_settings
from kg.api import app
from kg.settings import KGSettings
from kg.shared_decks.store import SharedDeck, SharedDeckStore


def _insert(store: SharedDeckStore, deck_id: str, updated_at: datetime) -> None:
    with Session(store.engine) as session:
        session.add(
            SharedDeck(
                id=deck_id,
                title=deck_id,
                title_nfc_lower=deck_id,
                source="official",
                visibility="official",
                status="active",
                updated_at=updated_at,
                created_at=updated_at,
            )
        )
        session.commit()


def test_recency_cursor_orders_updated_at_by_utc_instant(tmp_path):
    store = SharedDeckStore(tmp_path / "shared-decks.db")
    try:
        # The offsets are intentionally different: the first two instants are
        # 10:00Z and 09:00Z despite their textual representations.
        plus_nine = timezone(timedelta(hours=9))
        _insert(store, "newest", datetime(2026, 8, 21, 19, 0, tzinfo=plus_nine))
        _insert(store, "middle", datetime(2026, 8, 21, 10, 0, tzinfo=UTC))
        _insert(store, "oldest", datetime(2026, 8, 21, 9, 0, tzinfo=UTC))

        page_one = store.browse(limit=1)
        assert [deck.id for deck in page_one] == ["newest"]
        page_two = store.browse(
            limit=2,
            after=(page_one[-1].updated_at, page_one[-1].id),
        )
        assert [deck.id for deck in page_two] == ["middle", "oldest"]
    finally:
        store.close()


def test_recency_cursor_does_not_skip_offset_timestamps(tmp_path):
    (tmp_path / "users").mkdir()
    _swap_settings(KGSettings(data_dir=tmp_path, jwt_secret="test-secret-key-for-ci-at-least-32-bytes"))
    store = SharedDeckStore(tmp_path / "shared_decks.db")
    client = TestClient(app, raise_server_exceptions=False)
    try:
        plus_nine = timezone(timedelta(hours=9))
        _insert(store, "latest", datetime(2026, 8, 21, 19, 0, tzinfo=plus_nine))
        _insert(store, "middle", datetime(2026, 8, 21, 10, 0, tzinfo=UTC))
        _insert(store, "oldest", datetime(2026, 8, 21, 9, 0, tzinfo=UTC))

        first = client.get("/api/decks?limit=1")
        assert first.status_code == 200, first.text
        second = client.get(f"/api/decks?limit=2&cursor={first.json()['nextCursor']}")
        assert second.status_code == 200, second.text
        assert [deck["deckId"] for deck in first.json()["decks"] + second.json()["decks"]] == [
            "latest", "middle", "oldest"
        ]
    finally:
        client.close()
        store.close()


def test_recency_cursor_compares_raw_offset_values_by_utc_instant(tmp_path):
    store = SharedDeckStore(tmp_path / "shared-decks.db")
    try:
        _insert(store, "latest", datetime(2026, 8, 21, 11, 0, tzinfo=UTC))
        _insert(store, "middle", datetime(2026, 8, 21, 9, 0, tzinfo=UTC))
        _insert(store, "oldest", datetime(2026, 8, 21, 8, 0, tzinfo=UTC))
        with store.engine.begin() as connection:
            connection.execute(
                text("UPDATE shared_deck SET updated_at = :value WHERE id = :id"),
                [{"id": "latest", "value": "2026-08-21 20:00:00+09:00"},
                 {"id": "middle", "value": "2026-08-21 10:00:00+00:00"},
                 {"id": "oldest", "value": "2026-08-21 08:00:00+00:00"}],
            )
        # The store must expose the same UTC-instant ordering used by the API
        # cursor boundary; a raw ORM datetime is not the wire representation.
        page = store.browse(limit=3)
        assert [deck.id for deck in page] == ["latest", "middle", "oldest"]
    finally:
        store.close()
