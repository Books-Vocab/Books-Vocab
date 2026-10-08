"""Issue #2269: startup reaper compensates stale staged copy notebooks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kg.cards import CardStore
from kg.notebook import NotebookStore
from kg.shared_decks.reaper import reap_stale_staged_copies
from kg.shared_decks.store import SharedDeckStore
from test_vocab_staged_filter import _add


def _age(nbs: NotebookStore, notebook_id: str, minutes: int) -> None:
    import sqlite3

    stamp = (datetime.now(UTC) - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S.%f")
    with sqlite3.connect(nbs.path) as conn:
        conn.execute("UPDATE notebook SET created_at = ? WHERE id = ?", (stamp, notebook_id))


def test_reaper_compensates_only_orphaned_stale_staged(tmp_path):
    user_dir = tmp_path / "users" / "u1"
    user_dir.mkdir(parents=True)
    shared = SharedDeckStore(tmp_path / "shared_decks.db")
    cards = CardStore(user_dir / "cards.db")
    nbs = NotebookStore(user_dir / "notebooks.db")

    old = nbs.create(name="old", is_staged=True)
    fresh = nbs.create(name="fresh", is_staged=True)
    logged = nbs.create(name="logged", is_staged=True)
    live = nbs.create(name="live")
    for nb in (old, fresh, logged, live):
        _add(cards, nb.id, f"c-{nb.name}", datetime.now(UTC))
    for nb in (old, logged, live):
        _age(nbs, nb.id, 60)
    assert shared.record_copy("u1", "k", "deck", 1, logged.id)
    graph = user_dir / f"graph_{old.id}.json"
    graph.write_text("[]")

    assert reap_stale_staged_copies(tmp_path, older_than=timedelta(minutes=10)) == 1

    remaining = {n.id for n in nbs.all(include_deleted=True, include_staged=True)}
    assert remaining == {fresh.id, logged.id, live.id}
    assert not graph.exists()
    tomb = {c.content: c.is_deleted for c in cards.all(include_deleted=True)}
    assert tomb["c-old"] is True
    assert tomb["c-fresh"] is False and tomb["c-logged"] is False and tomb["c-live"] is False


def test_reaper_noop_without_users_dir(tmp_path):
    assert reap_stale_staged_copies(tmp_path) == 0
