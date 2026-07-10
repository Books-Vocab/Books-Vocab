"""Phase 2 — POST /api/decks/{id}/copy: server-side clone of an official deck
into the copier's private Notebook.

The load-bearing guardrails (all asserted here):

* fresh SRS + fresh id + provenance stamp, zero review_events (SRS isolation).
* strictly-monotonic (distinct) updated_at — §4.4 timestamp-tie pagination skip.
* mid-copy crash leaves NO half-product (materialization barrier + compensation).
* two copies of one deck → two uniquely-named notebooks → world-export still
  succeeds (duplicate-name trap).
* same idempotency_key retry → same notebook, no duplicate, no double download.
* copied count == source snapshot (fail-loud on NOCASE/NFC collapse).
* download_count atomic increment.
"""
from __future__ import annotations

import json

import pytest

from kg.cards import CardStore
from kg.exceptions import ConflictError, NotFoundError
from kg.notebook import NotebookStore
from kg.shared_decks.copy import copy_shared_deck
from kg.shared_decks.store import SharedDeckStore
from ops_helpers import run_ops_cli as _cli

_DECK_CARDS = [
    {"content": "meticulous", "pos": "adj.", "meaning": "一絲不苟的",
     "examples": ["Her **meticulous** notes."], "collocations": ["meticulous planning"],
     "note": "teacher note", "difficulty": 4.5, "mode": "recognition",
     "root_form": None, "inflections": []},
    {"content": "wince", "pos": "v.", "meaning": "畏縮", "mode": "recognition"},
    {"content": "ubiquitous", "pos": "adj.", "meaning": "無所不在的", "mode": "recognition"},
]


def _publish_deck(shared_store, *, deck_id="deck_a", title="Official Starter",
                  cards=None):
    return shared_store.publish_official(
        deck_id=deck_id, title=title, cards=cards if cards is not None else _DECK_CARDS,
        color="#112233", cover_pattern="waves", language_pair="en-zh",
        category="language", publisher_display_name="KG Team",
    )


def _stores(tmp_path, uid="u1"):
    user_dir = tmp_path / "users" / uid
    user_dir.mkdir(parents=True)
    shared_store = SharedDeckStore(tmp_path / "shared_decks.db")
    card_store = CardStore(user_dir / "cards.db")
    notebook_store = NotebookStore(user_dir / "notebooks.db")
    return user_dir, shared_store, card_store, notebook_store


def _copy(shared_store, card_store, notebook_store, user_dir, *, deck_id="deck_a",
          copier_id="u1", key="k1", notebook_name=None, on_card=None):
    return copy_shared_deck(
        shared_store=shared_store, card_store=card_store,
        notebook_store=notebook_store, user_dir=user_dir,
        deck_id=deck_id, copier_id=copier_id, idempotency_key=key,
        notebook_name=notebook_name, _on_card=on_card,
    )


# ── 1. fresh SRS + fresh id + provenance + zero review_events ───────


def test_copy_yields_fresh_srs_fresh_ids_and_provenance(tmp_path):
    user_dir, shared, cards, nbs = _stores(tmp_path)
    _publish_deck(shared)
    src = shared.all_cards("deck_a", version=1)
    src_guids = {c.content: c.content_guid for c in src}

    outcome = _copy(shared, cards, nbs, user_dir)

    nb = nbs.get(outcome.notebook_id)
    assert nb is not None and not nb.is_deleted
    assert nb.is_default is False
    assert nb.source_shared_deck_id == "deck_a"
    assert nb.source_version == 1

    copied = list(cards.all(notebook_id=nb.id))
    assert len(copied) == len(src) == outcome.card_count
    src_ids = {c.id for c in src}
    for c in copied:
        # model-default SRS (fresh schedule; author's schedule cannot leak)
        assert c.review_count == 0
        assert c.lapse_count == 0
        assert c.review_streak == 0
        assert c.next_review_at is None
        assert c.last_reviewed_at is None
        assert c.review_interval_hours == 12.0
        assert c.last_review_feedback == -1
        assert c.is_deleted is False
        assert c.id not in src_ids  # freshly minted id
        assert c.source_shared_card_guid == src_guids[c.content]

    # content verbatim: note + difficulty came across (add() cannot carry these)
    meticulous = next(c for c in copied if c.content == "meticulous")
    assert meticulous.note == "teacher note"
    assert meticulous.difficulty == 4.5

    # SRS isolation: the copy path never constructs a ReviewEventStore, so no
    # review-history plane exists for the copied cards.
    assert not (user_dir / "review_events.db").exists()


# ── 2. strictly-monotonic (distinct) updated_at (§4.4) ─────────────


def test_copy_stamps_distinct_monotonic_updated_at(tmp_path):
    user_dir, shared, cards, nbs = _stores(tmp_path)
    _publish_deck(shared)
    outcome = _copy(shared, cards, nbs, user_dir)
    copied = list(cards.all(notebook_id=outcome.notebook_id))
    stamps = [c.updated_at for c in copied]
    # No two cards share an updated_at → a keyset page boundary can never land
    # mid-tie-group and silently drop the rest (§4.4).
    assert len(set(stamps)) == len(stamps)


# ── 3. mid-copy crash → no half-product (barrier + compensation) ───


def test_midcopy_crash_leaves_no_halfproduct(tmp_path):
    user_dir, shared, cards, nbs = _stores(tmp_path)
    _publish_deck(shared)

    def boom(i):
        if i == 1:
            raise RuntimeError("injected mid-copy crash")

    with pytest.raises(RuntimeError, match="injected"):
        _copy(shared, cards, nbs, user_dir, on_card=boom)

    # compensation hard-deleted the partial notebook AND its cards — nothing,
    # not even a hidden barrier row, survives.
    assert list(nbs.all(include_deleted=True)) == []
    assert cards.count() == 0


# ── 4. two copies → unique names → world-export succeeds ───────────


def test_copy_twice_unique_names_and_world_export_ok(tmp_path):
    user_dir, shared, cards, nbs = _stores(tmp_path)
    _publish_deck(shared)

    o1 = _copy(shared, cards, nbs, user_dir, key="k1")
    o2 = _copy(shared, cards, nbs, user_dir, key="k2")
    assert o1.notebook_id != o2.notebook_id
    names = {o1.notebook_name, o2.notebook_name}
    assert len(names) == 2
    assert "Official Starter" in names  # first keeps the base title

    # The duplicate-name trap: two same-titled active notebooks would make
    # world-export fail-loud. Unique naming keeps it replayable.
    r = _cli(str(tmp_path), "world-export", "u1")
    assert r.returncode == 0, r.stderr
    exported = json.loads(r.stdout)
    nb_names = [n["name"] for n in exported["notebooks"]]
    assert len(nb_names) == len(set(nb_names)), nb_names


# ── 5. idempotent retry → same notebook, no dup, no double download ─


def test_copy_idempotent_retry(tmp_path):
    user_dir, shared, cards, nbs = _stores(tmp_path)
    _publish_deck(shared)

    o1 = _copy(shared, cards, nbs, user_dir, key="same-key")
    assert o1.already_copied is False
    o2 = _copy(shared, cards, nbs, user_dir, key="same-key")
    assert o2.already_copied is True
    assert o2.notebook_id == o1.notebook_id

    # exactly one copy notebook, and the download counted once
    assert len([n for n in nbs.all() if not n.is_default]) == 1
    assert shared.get("deck_a").download_count == 1


def test_replay_self_heals_staged_notebook(tmp_path, monkeypatch):
    """Crash-window recovery: a prior copy committed its idempotency log but
    crashed BEFORE revealing the notebook, leaving it staged (is_staged=True,
    NOT user-deleted). A same-key retry reveals it via _replay — never a dup.

    Staging uses a dedicated is_staged flag, never is_deleted, so materialize's
    reveal can never be confused with (or resurrect) a real user soft-delete."""
    user_dir, shared, cards, nbs = _stores(tmp_path)
    _publish_deck(shared)

    # Inject a crash in the reveal window: materialize raises on the first copy,
    # AFTER record_copy has committed the idempotency log (point of no return).
    calls = {"n": 0}
    real_materialize = nbs.materialize

    def flaky(nid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected crash before reveal")
        return real_materialize(nid)

    monkeypatch.setattr(nbs, "materialize", flaky)
    with pytest.raises(RuntimeError, match="injected"):
        _copy(shared, cards, nbs, user_dir, key="k1")

    log = shared.get_copy_log("u1", "k1")
    assert log is not None  # the crash was AFTER the point of no return
    staged = nbs.get(log.result_notebook_id)
    assert staged.is_staged is True
    assert staged.is_deleted is False
    assert log.result_notebook_id not in {n.id for n in nbs.all()}  # hidden

    # same-key retry → _replay reveals via the real materialize, no second dup
    o2 = _copy(shared, cards, nbs, user_dir, key="k1")
    assert o2.already_copied is True
    assert o2.notebook_id == log.result_notebook_id
    nb = nbs.get(log.result_notebook_id)
    assert nb.is_staged is False
    assert nb.is_deleted is False
    assert len([n for n in nbs.all() if not n.is_default]) == 1


def test_replay_does_not_resurrect_user_deleted_notebook(tmp_path):
    """is_deleted is NOT overloaded as the staging barrier: once a copy is
    materialized and the user soft-deletes it, a same-key retry (cross-device
    outbox replay against the permanent copy_log) must NOT revive it. materialize
    only flips is_staged→False and never touches is_deleted, so a user-deleted
    (is_staged=False, is_deleted=True) copy stays deleted."""
    user_dir, shared, cards, nbs = _stores(tmp_path)
    _publish_deck(shared)
    o1 = _copy(shared, cards, nbs, user_dir, key="k1")

    assert nbs.delete(o1.notebook_id) is True  # user soft-deletes the copy
    assert nbs.get(o1.notebook_id).is_deleted is True

    o2 = _copy(shared, cards, nbs, user_dir, key="k1")  # same-key retry
    assert o2.already_copied is True
    assert o2.notebook_id == o1.notebook_id
    nb = nbs.get(o1.notebook_id)
    assert nb.is_deleted is True  # stays deleted — NO resurrection
    assert nb.is_staged is False
    assert o1.notebook_id not in {n.id for n in nbs.all()}


# ── 5b. concurrent same-user copies → serialized, no duplicate name ─


def test_concurrent_same_user_copies_no_duplicate_active_name(tmp_path):
    """Two concurrent same-user copies with DISTINCT idempotency keys (an iOS
    double-tap mints two keys) must not each read the pre-create notebook
    snapshot, pick the SAME unique name, and both INSERT → two same-named
    active notebooks. That breaks world-export's name→id map (§2 name
    uniqueness is mandatory). The per-user copy lock serializes them so the
    second copy sees the first's materialized notebook and disambiguates."""
    import threading

    user_dir, shared, cards, nbs = _stores(tmp_path)
    _publish_deck(shared)

    a_mid = threading.Event()   # A: inside its critical section (holds the lock)
    a_go = threading.Event()    # main → A: you may finish
    results: dict[str, object] = {}
    errors: dict[str, BaseException] = {}

    def a_on_card(i):
        if i == 0:
            a_mid.set()
            # Hold INSIDE the copy critical section until released, so a
            # concurrent same-user copy must queue behind us if the lock works.
            assert a_go.wait(timeout=10)

    def run_a():
        try:
            results["a"] = _copy(shared, cards, nbs, user_dir, key="ka", on_card=a_on_card)
        except BaseException as exc:  # noqa: BLE001
            errors["a"] = exc

    def run_b():
        try:
            results["b"] = _copy(shared, cards, nbs, user_dir, key="kb")
        except BaseException as exc:  # noqa: BLE001
            errors["b"] = exc

    ta = threading.Thread(target=run_a)
    ta.start()
    assert a_mid.wait(timeout=10), "copy A never entered its critical section"

    tb = threading.Thread(target=run_b)
    tb.start()
    # B must block on the per-user lock while A holds it. Without the lock B
    # would race to completion here (and pick the same name).
    tb.join(timeout=0.5)
    assert tb.is_alive(), "copy B was NOT serialized behind A (no per-user lock)"

    a_go.set()
    ta.join(timeout=10)
    tb.join(timeout=10)
    assert not errors, errors

    names = {results["a"].notebook_name, results["b"].notebook_name}
    assert len(names) == 2, f"duplicate active notebook name: {names}"
    assert "Official Starter" in names  # first copy keeps the base title

    # The real consequence: world-export must still produce a replayable spec.
    r = _cli(str(tmp_path), "world-export", "u1")
    assert r.returncode == 0, r.stderr
    exported = json.loads(r.stdout)
    nb_names = [n["name"] for n in exported["notebooks"]]
    assert len(nb_names) == len(set(nb_names)), nb_names


def test_staged_notebook_excluded_from_world_export(tmp_path):
    """A copy-in-progress (staged) notebook must never leak into world-export.
    The raw-SQL readers filter is_deleted only, so moving the barrier to
    is_staged forces them to exclude is_staged too — else a half-copied notebook
    pollutes a replayable world spec (and could inject a duplicate name)."""
    user_dir, shared, cards, nbs = _stores(tmp_path)
    _publish_deck(shared)
    o1 = _copy(shared, cards, nbs, user_dir, key="k1")  # a real, visible copy

    # a staged (copy-in-progress) notebook sitting in the DB, not yet revealed
    nbs.create(name="Ghost Deck", is_staged=True)

    r = _cli(str(tmp_path), "world-export", "u1")
    assert r.returncode == 0, r.stderr
    exported = json.loads(r.stdout)
    names = [n["name"] for n in exported["notebooks"]]
    assert "Ghost Deck" not in names, f"staged notebook leaked into export: {names}"
    assert o1.notebook_name in names  # the materialized copy is present


def test_world_export_tolerates_db_without_is_staged_column(tmp_path):
    """A legacy notebooks.db predating the is_staged migration must still export
    — the raw readers probe for the column and skip the filter when it is
    absent (a WHERE on a missing column would be a hard parse error)."""
    import sqlite3

    user_dir = tmp_path / "users" / "u1"
    user_dir.mkdir(parents=True)
    conn = sqlite3.connect(str(user_dir / "notebooks.db"))
    conn.execute(
        "CREATE TABLE notebook (id TEXT PRIMARY KEY, name TEXT, color TEXT, "
        "cover_pattern TEXT, sort_order INTEGER DEFAULT 0, "
        "is_default INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT, "
        "is_deleted INTEGER DEFAULT 0)"  # NOTE: no is_staged column
    )
    conn.execute(
        "INSERT INTO notebook (id, name, sort_order, is_default, is_deleted) "
        "VALUES ('n1', 'Legacy Book', 0, 0, 0)"
    )
    conn.commit()
    conn.close()

    r = _cli(str(tmp_path), "world-export", "u1")
    assert r.returncode == 0, r.stderr
    names = [n["name"] for n in json.loads(r.stdout)["notebooks"]]
    assert names == ["Legacy Book"]


# ── 6. count-equality: NOCASE/NFC collapse fails loud ──────────────


def test_homograph_collapse_fails_loud(tmp_path):
    user_dir, shared, cards, nbs = _stores(tmp_path)
    # Two homographs distinct by (pos, meaning) → two distinct shared cards, but
    # they collapse under the card table's (content COLLATE NOCASE, notebook_id)
    # uniqueness. Count-equality must catch that, not silently drop a card.
    _publish_deck(shared, cards=[
        {"content": "Lead", "pos": "n.", "meaning": "鉛", "mode": "recognition"},
        {"content": "lead", "pos": "v.", "meaning": "帶領", "mode": "recognition"},
    ])
    assert len(shared.all_cards("deck_a", version=1)) == 2

    with pytest.raises(ConflictError):
        _copy(shared, cards, nbs, user_dir)
    # fail-loud rolls back — no partial notebook, no partial cards
    assert list(nbs.all(include_deleted=True)) == []
    assert cards.count() == 0


# ── 7. download_count atomic increment (sequential) ────────────────


def test_download_count_increments_per_distinct_copy(tmp_path):
    user_dir, shared, cards, nbs = _stores(tmp_path)
    _publish_deck(shared)
    for i in range(3):
        _copy(shared, cards, nbs, user_dir, key=f"k{i}")
    assert shared.get("deck_a").download_count == 3
    # a retry (existing key) does not re-increment
    _copy(shared, cards, nbs, user_dir, key="k0")
    assert shared.get("deck_a").download_count == 3


# ── 8. unknown deck → NotFound ─────────────────────────────────────


def test_copy_unknown_deck_raises_notfound(tmp_path):
    user_dir, shared, cards, nbs = _stores(tmp_path)
    with pytest.raises(NotFoundError):
        _copy(shared, cards, nbs, user_dir, deck_id="ghost")


# ── 9. router wiring: authed POST end-to-end ───────────────────────


def test_copy_endpoint_end_to_end(isolated_api):
    env = isolated_api
    shared = SharedDeckStore(env.data_dir / "shared_decks.db")
    _publish_deck(shared)

    # unauthenticated → rejected (no silent guest write)
    anon = env.client.post("/api/decks/deck_a/copy", json={"idempotencyKey": "x"})
    assert anon.status_code in (401, 403)

    r = env.client.post(
        "/api/decks/deck_a/copy",
        headers=env.headers,
        json={"idempotencyKey": "req-1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alreadyCopied"] is False
    assert body["cardCount"] == len(_DECK_CARDS)
    nb_id = body["notebookId"]

    # the notebook shows up in the copier's list
    nbs = env.client.get("/api/notebooks", headers=env.headers)
    assert nbs.status_code == 200
    assert any(n["id"] == nb_id for n in nbs.json())

    # idempotent retry → same notebook
    r2 = env.client.post(
        "/api/decks/deck_a/copy",
        headers=env.headers,
        json={"idempotencyKey": "req-1"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["alreadyCopied"] is True
    assert r2.json()["notebookId"] == nb_id
