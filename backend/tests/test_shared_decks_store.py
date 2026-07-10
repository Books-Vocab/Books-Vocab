"""Structural contract tests for the global shared-decks store (Phase 1a).

The store lives at ``data_dir/shared_decks.db`` — OUTSIDE ``users/<uid>/`` —
because a shared deck's owner is a *column*, not a path (mirroring the
``translate_log`` cross-user precedent).

The load-bearing invariant these tests pin down: the ``shared_deck_card`` table
is a **content plane only** — it structurally cannot carry any of the 7 SRS
review columns that live on ``Card``. A publish path that snapshots into this
table therefore *cannot* leak a copier's review schedule, by construction.
"""
from __future__ import annotations

from sqlalchemy import inspect

from kg.shared_decks.store import SharedDeckStore

# The 7 spaced-review columns on ``Card`` (cards/model.py) — none may appear on
# ``shared_deck_card``. Kept as a literal so the test fails loudly if someone
# reuses ``Card`` or ``CardResponse`` as the shared-card shape.
SRS_COLUMNS = {
    "review_interval_hours",
    "next_review_at",
    "last_reviewed_at",
    "review_count",
    "lapse_count",
    "review_streak",
    "last_review_feedback",
}

CONTENT_PLANE_COLUMNS = {
    "content",
    "pos",
    "meaning",
    "examples",
    "collocations",
    "note",
    "difficulty",
    "mode",
    "root_form",
    "inflections",
    "content_guid",
}

EXPECTED_TABLES = {
    "shared_deck",
    "shared_deck_version",
    "shared_deck_card",
    "shared_deck_rating",
    "shared_deck_report",
    "shared_deck_copy_log",
}


def _columns(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_store_builds_all_six_tables(tmp_path):
    store = SharedDeckStore(tmp_path / "shared_decks.db")
    try:
        tables = set(inspect(store.engine).get_table_names())
        assert EXPECTED_TABLES <= tables, f"missing tables: {EXPECTED_TABLES - tables}"
    finally:
        store.close()


def test_shared_deck_card_has_zero_srs_columns(tmp_path):
    """Structural de-leak: the shared card table must not carry SRS state."""
    store = SharedDeckStore(tmp_path / "shared_decks.db")
    try:
        cols = _columns(store.engine, "shared_deck_card")
        leaked = SRS_COLUMNS & cols
        assert not leaked, f"SRS columns leaked into shared_deck_card: {leaked}"
        # It also must not carry the per-copy identity columns.
        assert "notebook_id" not in cols
    finally:
        store.close()


def test_shared_deck_card_carries_content_plane(tmp_path):
    store = SharedDeckStore(tmp_path / "shared_decks.db")
    try:
        cols = _columns(store.engine, "shared_deck_card")
        missing = CONTENT_PLANE_COLUMNS - cols
        assert not missing, f"content-plane columns missing: {missing}"
    finally:
        store.close()


def test_migration_is_idempotent(tmp_path):
    """Constructing the store twice against the same file must not raise."""
    path = tmp_path / "shared_decks.db"
    first = SharedDeckStore(path)
    first.close()
    second = SharedDeckStore(path)
    try:
        tables = set(inspect(second.engine).get_table_names())
        assert EXPECTED_TABLES <= tables
    finally:
        second.close()


def test_load_bearing_constraints_exist(tmp_path):
    """Concurrency correctness rests on 'a UNIQUE/PK catches IntegrityError,
    not a threading.Lock' (§6.5). The Phase 3 write path depends on these —
    assert they are actually built so a silent schema regression is caught."""
    store = SharedDeckStore(tmp_path / "shared_decks.db")
    try:
        insp = inspect(store.engine)

        def uniques(table: str) -> set[tuple[str, ...]]:
            return {tuple(u["column_names"]) for u in insp.get_unique_constraints(table)}

        def pk(table: str) -> set[str]:
            return set(insp.get_pk_constraint(table)["constrained_columns"])

        # Republish idempotency + per-deck/version card dedup.
        assert ("owner_id", "source_notebook_id") in uniques("shared_deck")
        assert ("shared_deck_id", "version", "content_guid") in uniques("shared_deck_card")
        # Composite PKs on the version pointer + junction/log tables.
        assert pk("shared_deck_version") == {"shared_deck_id", "version"}
        assert pk("shared_deck_rating") == {"shared_deck_id", "user_id"}
        assert pk("shared_deck_report") == {"shared_deck_id", "reporter_id"}
        assert pk("shared_deck_copy_log") == {"copier_id", "idempotency_key"}
    finally:
        store.close()


def test_shared_deck_index_columns_present(tmp_path):
    """The metadata plane carries the axes browse/search/moderation need."""
    store = SharedDeckStore(tmp_path / "shared_decks.db")
    try:
        cols = _columns(store.engine, "shared_deck")
        for expected in (
            "owner_id",
            "source",
            "visibility",
            "status",
            "is_deleted",
            "current_version",
            "card_count",
            "title_nfc_lower",
            "download_count",
            "rating_sum",
            "rating_count",
            "report_count",
        ):
            assert expected in cols, f"shared_deck missing column: {expected}"
    finally:
        store.close()
