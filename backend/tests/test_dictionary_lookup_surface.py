"""The backend dictionary boundary is lookup-only.

Dictionary results may be searched and fetched, but they are not cards and
must not create a second persistence, sync, review, graph, or lifecycle model.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace

from kg.api_models import dictionary as dictionary_models
from kg.cards import Card, CardStore
from kg.routers.dictionary import router


def test_card_schema_has_no_dictionary_card_semantics(tmp_path):
    db = tmp_path / "cards.db"
    CardStore(db).close()

    with closing(sqlite3.connect(db)) as conn, conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(card)")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert {
        "card_role",
        "review_eligible",
        "reader_hidden",
        "promotion_state",
        "promoted_at",
    }.isdisjoint(columns)
    assert {
        "dictionary_entry",
        "dictionary_lifecycle_state",
        "dictionary_archive_link_cause",
        "dictionary_promotion_jobs",
        "lexical_operations",
    }.isdisjoint(tables)
    for attribute in (
        "card_role",
        "review_eligible",
        "reader_hidden",
        "promotion_state",
        "promoted_at",
    ):
        assert not hasattr(Card, attribute)


def test_existing_card_db_retires_dictionary_schema_without_losing_cards(tmp_path):
    db = tmp_path / "cards.db"
    store = CardStore(db)
    original = store.add("invoke", "援引", notebook_id="default")
    store.close()

    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("ALTER TABLE card ADD COLUMN card_role TEXT DEFAULT 'learning'")
        conn.execute("ALTER TABLE card ADD COLUMN review_eligible INTEGER DEFAULT 1")
        conn.execute("ALTER TABLE card ADD COLUMN reader_hidden INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE card ADD COLUMN promotion_state TEXT DEFAULT 'idle'")
        conn.execute("ALTER TABLE card ADD COLUMN promoted_at TIMESTAMP")
        for table in (
            "dictionary_entry",
            "lexical_operations",
            "dictionary_promotion_jobs",
            "dictionary_lifecycle_state",
            "dictionary_archive_link_cause",
        ):
            conn.execute(f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY)')

    reopened = CardStore(db)
    preserved = reopened.get(original.id)
    reopened.close()

    with closing(sqlite3.connect(db)) as conn, conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(card)")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert preserved is not None
    assert (preserved.content, preserved.meaning) == ("invoke", "援引")
    assert {
        "card_role",
        "review_eligible",
        "reader_hidden",
        "promotion_state",
        "promoted_at",
    }.isdisjoint(columns)
    assert {
        "dictionary_entry",
        "lexical_operations",
        "dictionary_promotion_jobs",
        "dictionary_lifecycle_state",
        "dictionary_archive_link_cause",
    }.isdisjoint(tables)


def test_dictionary_router_and_models_are_lookup_only():
    surface = {(route.path, frozenset(route.methods or set())) for route in router.routes}
    assert surface == {
        ("/api/dictionary/search", frozenset({"GET"})),
        (
            "/api/dictionary/entries/{provider}/{entry_key}",
            frozenset({"GET"}),
        ),
    }
    assert dictionary_models.__all__ == [
        "DictionaryEntryResponse",
        "DictionarySearchHit",
        "DictionarySearchResponse",
    ]


def test_dictionary_search_rejects_whitespace_only_query_before_lookup(isolated_api, monkeypatch):
    import kg.routers.dictionary as dictionary_router

    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    calls = []

    def unexpected_lookup(_settings):
        calls.append(True)
        raise AssertionError("a blank query must not enter the lookup service")

    monkeypatch.setattr(dictionary_router, "_lexical_service", unexpected_lookup)
    response = isolated_api.client.get(
        "/api/dictionary/search",
        params={"q": " \t\n"},
        headers=isolated_api.headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "q"
    assert calls == []
