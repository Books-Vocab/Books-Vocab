"""#2057: account deletion must evict every per-user store cache entry.

Stores are cached process-wide (``service_factories._STORE_CACHE``). If a
deleted user's entries survive the ``rmtree``, a re-login with the same
provider ``sub`` resolves the same ``user_dir`` and gets the pre-deletion
objects back: ``GraphStore`` serves (and later re-flushes) the old in-memory
links, and ``CardStore``'s pooled connection keeps reading/writing the
unlinked SQLite inode.
"""

from __future__ import annotations

import threading
from pathlib import Path

import kg.api as api_mod
import kg.routers.auth as auth_router
from kg import service_factories as sf
from kg.auth_types import VerifiedIdentity
from kg.graph import LinkKind


def _relogin(isolated_api, monkeypatch) -> dict[str, str]:
    """Sign in again through /auth/verify with the same Apple ``sub``."""
    monkeypatch.setattr(
        auth_router,
        "verify_apple_token",
        lambda token, audience: VerifiedIdentity(isolated_api.user_id, None, False),
    )
    resp = isolated_api.client.post("/auth/verify", json={"provider": "apple", "token": "relogin-token"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user_id"] == isolated_api.user_id
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_delete_then_relogin_sees_empty_stores_and_new_writes_persist(isolated_api, monkeypatch):
    client = isolated_api.client
    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id

    cards = api_mod._card_store(user_dir)
    graph = api_mod._graph_store(user_dir)
    evoke = cards.add(content="evoke", meaning="喚起")
    invoke = cards.add(content="invoke", meaning="援引")
    graph.add_link(evoke.id, invoke.id, LinkKind.SHARES_USAGE, 0.9, "seeded before deletion")

    before = client.get("/api/vocab", headers=isolated_api.headers)
    assert before.status_code == 200, before.text
    assert sorted(card["content"] for card in before.json()) == ["evoke", "invoke"]

    deleted = client.delete("/api/user/account", headers=isolated_api.headers)
    assert deleted.status_code == 200, deleted.text
    assert not user_dir.exists()

    headers = _relogin(isolated_api, monkeypatch)

    vocab = client.get("/api/vocab", headers=headers)
    assert vocab.status_code == 200, vocab.text
    assert vocab.json() == []
    links = client.get("/api/graph/links", headers=headers)
    assert links.status_code == 200, links.text
    assert links.json() == []

    # Writes after re-login must land in the real on-disk files: a cached
    # CardStore would write into the unlinked inode, and a cached GraphStore
    # would flush the pre-deletion links back to disk.
    fresh = api_mod._card_store(user_dir).add(content="fresh", meaning="新的")
    other = api_mod._card_store(user_dir).add(content="other", meaning="其他")
    api_mod._graph_store(user_dir).add_link(fresh.id, other.id, LinkKind.SHARES_USAGE, 0.8, "after re-login")

    sf.clear_store_cache()  # simulate a process restart: reopen from disk

    reopened_cards = api_mod._card_store(user_dir)
    assert sorted(card.content for card in reopened_cards.all()) == ["fresh", "other"]
    reopened_links = api_mod._graph_store(user_dir).all_links()
    assert [{link.from_id, link.to_id} for link in reopened_links] == [{fresh.id, other.id}]


class _Closable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _populate_every_per_user_store(user_dir: Path) -> list[str]:
    sf.create_card_store(user_dir)
    sf.create_review_event_store(user_dir)
    sf.create_graph_event_store(user_dir)
    sf.create_graph_snapshot_store(user_dir)
    sf.create_graph_store(user_dir)
    sf.create_graph_store(user_dir, notebook_id="nb2")
    sf.create_notebook_store(user_dir)
    sf.create_library_store(user_dir)
    sf.create_embedding_store(user_dir, llm=None, model="test-embed", dim=4)
    with sf._STORE_CACHE_LOCK:
        return [key for key in sf._STORE_CACHE if str(user_dir) in key]


def test_evict_user_store_cache_closes_and_drops_only_that_users_entries(tmp_path):
    sf.clear_store_cache()
    victim_dir = tmp_path / "users" / "victim"
    # Prefix sibling: must NOT be matched by a naive startswith(user_dir).
    sibling_dir = tmp_path / "users" / "victim2"
    shared_path = tmp_path / "shared_decks.db"
    try:
        victim_keys = _populate_every_per_user_store(victim_dir)
        assert {key.split(":", 1)[0] for key in victim_keys} == {
            "card",
            "review_events",
            "graph_events",
            "graph_snapshots",
            "graph",
            "notebook",
            "library",
            "embedding",
        }
        sibling_keys = _populate_every_per_user_store(sibling_dir)
        sf.create_shared_deck_store(shared_path)

        victim_card_store = sf.create_card_store(victim_dir)
        sf.evict_user_store_cache(victim_dir)

        with sf._STORE_CACHE_LOCK:
            remaining = set(sf._STORE_CACHE)
        assert remaining.isdisjoint(victim_keys)
        assert set(sibling_keys) <= remaining
        assert f"shared_decks:{shared_path}" in remaining
        assert victim_card_store.engine is None  # closed, not just dropped
        assert sf.create_card_store(victim_dir) is not victim_card_store
    finally:
        sf.clear_store_cache()


def test_evict_user_store_cache_invalidates_in_flight_build(tmp_path):
    """A build racing the eviction must not be published into the cache."""
    sf.clear_store_cache()
    user_dir = tmp_path / "users" / "racer"
    key = f"card:{user_dir}"
    started = threading.Event()
    release = threading.Event()
    built = _Closable()
    result: dict[str, object] = {}

    def slow_factory():
        started.set()
        release.wait(timeout=5)
        return built

    worker = threading.Thread(target=lambda: result.setdefault("store", sf._get_cached(key, slow_factory)))
    worker.start()
    try:
        assert started.wait(timeout=5)
        sf.evict_user_store_cache(user_dir)
        release.set()
        worker.join(timeout=5)
        assert result["store"] is built
        assert built.closed
        with sf._STORE_CACHE_LOCK:
            assert key not in sf._STORE_CACHE
    finally:
        release.set()
        worker.join(timeout=5)
        sf.clear_store_cache()


# ── eviction ordering / partial rmtree failure (review follow-up) ─────────────


def _delete_linked_pair(tmp_path, monkeypatch, *, failing_uid: str | None):
    """Delete canonical ``a`` + linked ``b``; record save / evict / rmtree order."""
    import shutil
    from unittest.mock import MagicMock

    import pytest
    from fastapi import HTTPException

    import kg.user_handlers as handlers
    from kg.user_store import collect_account_ids_for_deletion

    for uid in ("a", "b"):
        (tmp_path / "users" / uid).mkdir(parents=True)
        (tmp_path / "users" / uid / "cards.db").write_text("x")
    users: dict = {"a": {"id": "a", "linked_ids": ["b"]}, "b": {"id": "b", "_linked_to": "a"}}
    events: list[tuple[str, str]] = []
    real_rmtree = shutil.rmtree

    def fake_evict(user_dir: Path) -> None:
        events.append(("evict", user_dir.name))

    def fake_rmtree(path, *args, **kwargs):
        events.append(("rmtree", Path(path).name))
        if Path(path).name == failing_uid:
            raise OSError("disk says no")
        real_rmtree(path, *args, **kwargs)

    def save_users(payload) -> None:
        events.append(("save", ""))

    monkeypatch.setattr(handlers, "evict_user_store_cache", fake_evict)
    monkeypatch.setattr(handlers.shutil, "rmtree", fake_rmtree)

    def call():
        return handlers.delete_user_account_response(
            {"id": "a"},
            users_lock_file=tmp_path / "users.json.lock",
            load_users=lambda: users,
            save_users=save_users,
            collect_account_ids_for_deletion=collect_account_ids_for_deletion,
            data_dir=tmp_path,
            logger=MagicMock(),
        )

    if failing_uid is None:
        return call(), events
    with pytest.raises(HTTPException) as exc_info:
        call()
    return exc_info.value, events


def test_delete_evicts_stores_right_after_the_tombstone_save_and_again_after_rmtree(tmp_path, monkeypatch):
    _, events = _delete_linked_pair(tmp_path, monkeypatch, failing_uid=None)

    first_rmtree = next(i for i, event in enumerate(events) if event[0] == "rmtree")
    last_rmtree = max(i for i, event in enumerate(events) if event[0] == "rmtree")
    save_at = events.index(("save", ""))
    for uid in ("a", "b"):
        before = [i for i, event in enumerate(events) if event == ("evict", uid) and save_at < i < first_rmtree]
        after = [i for i, event in enumerate(events) if event == ("evict", uid) and i > last_rmtree]
        assert before, f"{uid}: no eviction between the tombstone save and rmtree: {events}"
        assert after, f"{uid}: no eviction after rmtree: {events}"


def test_delete_keeps_removing_and_evicting_linked_ids_when_one_rmtree_fails(tmp_path, monkeypatch):
    error, events = _delete_linked_pair(tmp_path, monkeypatch, failing_uid="a")

    assert error.status_code == 500
    assert not (tmp_path / "users" / "b").exists(), "later linked id was left on disk after an earlier failure"
    last_rmtree = max(i for i, event in enumerate(events) if event[0] == "rmtree")
    for uid in ("a", "b"):
        assert any(event == ("evict", uid) and i > last_rmtree for i, event in enumerate(events)), (
            f"{uid} not evicted after the failed deletion: {events}"
        )


# ── #2701: a failed rmtree must not leave a re-attachable directory ───────────


def test_failed_rmtree_does_not_strand_data_a_relogin_would_reattach(tmp_path, monkeypatch):
    error, _ = _delete_linked_pair(tmp_path, monkeypatch, failing_uid="a")

    assert error.status_code == 500
    # resolve_current_user does users/<uid>.mkdir(exist_ok=True): whatever sits
    # at that path after the failure is what a same-sub re-login gets.
    assert not (tmp_path / "users" / "a").exists()
    assert not (tmp_path / "users" / "a" / "cards.db").exists()


def test_next_deletion_sweeps_quarantined_leftovers(tmp_path, monkeypatch):
    _delete_linked_pair(tmp_path, monkeypatch, failing_uid="a")
    leftovers = list((tmp_path / ".deleting").rglob("cards.db"))
    assert leftovers, "failed rmtree should leave the data quarantined, not in users/"

    (tmp_path / "users" / "c").mkdir(parents=True)
    from unittest.mock import MagicMock

    import kg.user_handlers as handlers
    from kg.user_store import collect_account_ids_for_deletion

    users = {"c": {"id": "c"}}
    handlers.delete_user_account_response(
        {"id": "c"},
        users_lock_file=tmp_path / "users.json.lock",
        load_users=lambda: users,
        save_users=lambda payload: None,
        collect_account_ids_for_deletion=collect_account_ids_for_deletion,
        data_dir=tmp_path,
        logger=MagicMock(),
    )

    assert not list((tmp_path / ".deleting").rglob("cards.db"))
