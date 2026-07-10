"""Phase 1a-iii: provenance columns on Card/Notebook + world-export ↔ seed
omit-if-null symmetry (ops_state_plane §1.1 roundtrip contract).

A copied card/notebook records where it came from
(``Card.source_shared_card_guid`` / ``Notebook.source_shared_deck_id`` +
``source_version``). These are inert in v1 — Phase 2 copy sets them. The
load-bearing constraint: adding them must NOT break the world-export ↔ seed
byte-equal roundtrip for specs predating shared decks (committed specs carry no
provenance key). A spec that DOES carry notebook provenance must round-trip
losslessly (field symmetry, §1.1).
"""
from __future__ import annotations

import json
import sqlite3

from ops_helpers import run_ops_cli as _cli
from ops_helpers import run_ops_edit as _edit
from sqlalchemy import inspect

from kg.api_models.notebook import NotebookResponse
from kg.cards import CardStore
from kg.notebook import NotebookStore
from kg.ops_world_export import _card_entry, _notebook_entry

_NB_BASE_KEYS = {"name", "color", "cover_pattern", "sort_order", "is_default"}
_CARD_BASE_KEYS = {
    "content", "pos", "meaning", "examples", "collocations", "note",
    "difficulty", "mode", "root_form", "inflections", "notebook",
    "is_archived", "review",
}


def _cols(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


# ── column presence (fresh create_all) ─────────────────────────────


def test_card_has_provenance_column(tmp_path):
    store = CardStore(tmp_path / "cards.db")
    try:
        assert "source_shared_card_guid" in _cols(store.engine, "card")
    finally:
        store.close()


def test_notebook_has_provenance_columns(tmp_path):
    store = NotebookStore(tmp_path / "notebooks.db")
    try:
        cols = _cols(store.engine, "notebook")
        assert {"source_shared_deck_id", "source_version"} <= cols
    finally:
        store.close()


# ── migration path (legacy DB missing the columns) ─────────────────


def test_notebook_migration_adds_provenance_to_legacy_db(tmp_path):
    path = tmp_path / "notebooks.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE notebook (id TEXT PRIMARY KEY, name TEXT, color TEXT, "
        "sort_order INTEGER, is_default INTEGER, created_at TIMESTAMP, "
        "updated_at TIMESTAMP, is_deleted INTEGER)"
    )
    conn.commit()
    conn.close()
    store = NotebookStore(path)  # __init__ runs _migrate_columns
    try:
        cols = _cols(store.engine, "notebook")
        assert {"source_shared_deck_id", "source_version"} <= cols
    finally:
        store.close()


def test_card_migration_adds_provenance_to_legacy_db(tmp_path):
    path = tmp_path / "cards.db"
    conn = sqlite3.connect(path)
    # Legacy card table lacking the provenance column (but carrying the columns
    # init_schema's index creation touches: content / notebook_id / is_deleted /
    # updated_at).
    conn.execute(
        "CREATE TABLE card (id TEXT PRIMARY KEY, content TEXT, meaning TEXT, "
        "notebook_id TEXT, is_deleted INTEGER, created_at TIMESTAMP, "
        "updated_at TIMESTAMP)"
    )
    conn.commit()
    conn.close()
    store = CardStore(path)  # init_schema runs _migrate_review_columns
    try:
        assert "source_shared_card_guid" in _cols(store.engine, "card")
    finally:
        store.close()


# ── wire model ─────────────────────────────────────────────────────


def test_notebook_response_has_provenance_fields():
    r = NotebookResponse(id="x", name="n")
    assert r.sourceSharedDeckId is None
    assert r.sourceVersion is None
    r2 = NotebookResponse(id="x", name="n", sourceSharedDeckId="d1", sourceVersion=2)
    assert r2.sourceSharedDeckId == "d1"
    assert r2.sourceVersion == 2


# ── export omit-if-null (unit, both directions) ────────────────────


def test_notebook_entry_omits_null_provenance():
    row = {
        "name": "A", "color": None, "cover_pattern": None,
        "sort_order": 0, "is_default": False,
        "source_shared_deck_id": None, "source_version": None,
    }
    assert set(_notebook_entry(row)) == _NB_BASE_KEYS


def test_notebook_entry_emits_set_provenance():
    row = {
        "name": "A", "color": None, "cover_pattern": None,
        "sort_order": 0, "is_default": False,
        "source_shared_deck_id": "deck_abc", "source_version": 3,
    }
    entry = _notebook_entry(row)
    assert entry["source_shared_deck_id"] == "deck_abc"
    assert entry["source_version"] == 3
    assert set(entry) == _NB_BASE_KEYS | {"source_shared_deck_id", "source_version"}


def test_card_entry_omits_null_provenance():
    # A card that was created organically (no shared-deck origin) carries a NULL
    # guid; export must omit the key entirely so specs predating shared decks
    # round-trip byte-equal (§1.1). Symmetric with _notebook_entry.
    row = {"content": "x", "meaning": "y", "mode": "recognition",
           "source_shared_card_guid": None}
    entry = _card_entry(row, "NB")
    assert "source_shared_card_guid" not in entry
    assert set(entry) == _CARD_BASE_KEYS


def test_card_entry_emits_set_provenance():
    row = {"content": "x", "meaning": "y", "mode": "recognition",
           "source_shared_card_guid": "card-guid-123"}
    entry = _card_entry(row, "NB")
    assert entry["source_shared_card_guid"] == "card-guid-123"
    assert set(entry) == _CARD_BASE_KEYS | {"source_shared_card_guid"}


# ── seed ↔ export symmetry (integration, real CLI) ─────────────────

_PROVENANCE_SPEC = {
    "notebooks": [
        {"name": "Copied Deck", "is_default": False,
         "source_shared_deck_id": "deck_xyz", "source_version": 2},
        {"name": "Plain", "is_default": True},
    ],
    "cards": [
        {"content": "meticulous", "meaning": "一絲不苟的", "notebook": "Copied Deck"},
    ],
}


def _seed(dd, uid, spec, *extra):
    p = dd / "spec.json"
    p.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return _edit(str(dd), "seed", uid, str(p), *extra)


def test_seed_export_notebook_provenance_roundtrips(tmp_path):
    """seed(spec with provenance) → export must carry the provenance back, and
    a second seed→export into a fresh sandbox must be byte-equal (§1.1)."""
    assert _edit(str(tmp_path), "user-create", "u1", "--commit", "--json").returncode == 0
    assert _seed(tmp_path, "u1", _PROVENANCE_SPEC, "--commit", "--json").returncode == 0

    r = _cli(str(tmp_path), "world-export", "u1")
    assert r.returncode == 0, r.stderr
    exported = json.loads(r.stdout)
    copied = next(n for n in exported["notebooks"] if n["name"] == "Copied Deck")
    assert copied["source_shared_deck_id"] == "deck_xyz"
    assert copied["source_version"] == 2
    # The default notebook has no provenance → keys stay minimal (omit-if-null).
    plain = next(n for n in exported["notebooks"] if n["name"] == "Plain")
    assert set(plain) == _NB_BASE_KEYS

    # Replay into a fresh sandbox and re-export → byte-equal payload.
    assert _edit(str(tmp_path), "user-create", "u2", "--commit", "--json").returncode == 0
    p2 = tmp_path / "reexport.json"
    p2.write_text(json.dumps(exported, ensure_ascii=False), encoding="utf-8")
    assert _edit(str(tmp_path), "seed", "u2", str(p2), "--commit", "--json").returncode == 0
    r2 = _cli(str(tmp_path), "world-export", "u2")
    assert r2.returncode == 0, r2.stderr
    assert json.loads(r2.stdout)["notebooks"] == exported["notebooks"]


_CARD_PROVENANCE_SPEC = {
    "notebooks": [
        {"name": "Copied Deck", "is_default": False},
    ],
    "cards": [
        # A card stamped with shared-card provenance (Phase 2 copy sets this).
        {"content": "meticulous", "meaning": "一絲不苟的", "notebook": "Copied Deck",
         "source_shared_card_guid": "card-guid-abc"},
        # An organically-created card in the same notebook: no provenance key.
        {"content": "plain", "meaning": "平凡的", "notebook": "Copied Deck"},
    ],
}


def test_seed_export_card_provenance_roundtrips(tmp_path):
    """A card carrying source_shared_card_guid must round-trip losslessly, while
    a sibling without it stays omit-if-null — the symmetry that keeps the copy
    path's stamped provenance survivable through world-export → seed (§1.1)."""
    assert _edit(str(tmp_path), "user-create", "u1", "--commit", "--json").returncode == 0
    assert _seed(tmp_path, "u1", _CARD_PROVENANCE_SPEC, "--commit", "--json").returncode == 0

    r = _cli(str(tmp_path), "world-export", "u1")
    assert r.returncode == 0, r.stderr
    exported = json.loads(r.stdout)
    stamped = next(c for c in exported["cards"] if c["content"] == "meticulous")
    assert stamped["source_shared_card_guid"] == "card-guid-abc"
    plain = next(c for c in exported["cards"] if c["content"] == "plain")
    assert "source_shared_card_guid" not in plain

    # Replay into a fresh sandbox and re-export → byte-equal cards payload.
    assert _edit(str(tmp_path), "user-create", "u2", "--commit", "--json").returncode == 0
    p2 = tmp_path / "reexport-cards.json"
    p2.write_text(json.dumps(exported, ensure_ascii=False), encoding="utf-8")
    assert _edit(str(tmp_path), "seed", "u2", str(p2), "--commit", "--json").returncode == 0
    r2 = _cli(str(tmp_path), "world-export", "u2")
    assert r2.returncode == 0, r2.stderr
    assert json.loads(r2.stdout)["cards"] == exported["cards"]
