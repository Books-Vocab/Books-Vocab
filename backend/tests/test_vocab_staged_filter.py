"""Issue #2269: cards of a staged (copy-in-progress) notebook must not leak into
the global (notebook_id=None) vocab pull, on both the full-sync and incremental
paths; materialize reveals them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kg.cards import CardStore
from kg.notebook import NotebookStore
from kg.vocab_handlers.crud import list_vocab_response


def _add(cards: CardStore, notebook_id: str, content: str, at: datetime):
    return cards.add_shared_copy(
        content=content,
        meaning="m",
        pos=None,
        examples=None,
        collocations=None,
        note=None,
        difficulty=None,
        mode="recognition",
        root_form=None,
        inflections=None,
        notebook_id=notebook_id,
        updated_at=at,
        source_shared_card_guid=f"g-{content}",
    )


def _list(tmp_path, cards, nbs, *, since, limit=5000):
    class _Graph:
        def get_links_for(self, _card_id):
            return []

    return list_vocab_response(
        since,
        {"dir": tmp_path},
        card_store_factory=lambda _d: cards,
        graph_store_factory=lambda _d, notebook_id="default": _Graph(),
        card_response_builder=lambda card, _g, _by_id: card.content,
        notebook_store_factory=lambda _d: nbs,
        limit=limit,
    )


def _setup(tmp_path):
    cards = CardStore(tmp_path / "cards.db")
    nbs = NotebookStore(tmp_path / "notebooks.db")
    staged = nbs.create(name="Staged", is_staged=True)
    live = nbs.create(name="Live")
    base = datetime.now(UTC)
    for i in range(3):
        _add(cards, staged.id, f"s{i}", base + timedelta(milliseconds=i))
    _add(cards, live.id, "live0", base + timedelta(milliseconds=1))
    _add(cards, live.id, "live1", base + timedelta(milliseconds=5))
    return cards, nbs, staged, base


def test_full_sync_excludes_staged_cards_and_pages_gap_free(tmp_path):
    cards, nbs, _staged, _base = _setup(tmp_path)
    got, cursor = [], None
    while True:
        page, cursor = _list_page(tmp_path, cards, nbs, cursor)
        got += page
        if cursor is None:
            break
    assert sorted(got) == ["live0", "live1"]


def _list_page(tmp_path, cards, nbs, cursor):
    class _Graph:
        def get_links_for(self, _card_id):
            return []

    return list_vocab_response(
        None,
        {"dir": tmp_path},
        card_store_factory=lambda _d: cards,
        graph_store_factory=lambda _d, notebook_id="default": _Graph(),
        card_response_builder=lambda card, _g, _by_id: card.content,
        notebook_store_factory=lambda _d: nbs,
        limit=1,
        cursor=cursor,
    )


def test_incremental_excludes_staged_cards(tmp_path):
    cards, nbs, _staged, base = _setup(tmp_path)
    got, _ = _list(tmp_path, cards, nbs, since=(base - timedelta(seconds=5)).isoformat())
    assert sorted(got) == ["live0", "live1"]


def test_materialize_reveals_cards(tmp_path):
    cards, nbs, staged, base = _setup(tmp_path)
    assert nbs.materialize(staged.id)
    full, _ = _list(tmp_path, cards, nbs, since=None)
    inc, _ = _list(tmp_path, cards, nbs, since=(base - timedelta(seconds=5)).isoformat())
    expected = ["live0", "live1", "s0", "s1", "s2"]
    assert sorted(full) == expected
    assert sorted(inc) == expected


# ── reveal must reach incremental pullers (sync-hole regression) ─────


def _copy_old(tmp_path, *, now, key="k1"):
    """Run a real shared-deck copy whose cards are stamped at ``now`` (the copy
    start), returning the stores plus the new notebook id."""
    from kg.shared_decks.copy import copy_shared_deck
    from kg.shared_decks.store import SharedDeckStore

    user_dir = tmp_path / "users" / "u1"
    user_dir.mkdir(parents=True)
    shared = SharedDeckStore(tmp_path / "shared_decks.db")
    shared.publish_official(
        deck_id="deck_a",
        title="Official Starter",
        cards=[{"content": f"w{i}", "pos": "n.", "meaning": "m", "mode": "recognition"} for i in range(3)],
        color="#112233",
        cover_pattern="waves",
        language_pair="en-zh",
        category="language",
        publisher_display_name="KG Team",
    )
    cards = CardStore(user_dir / "cards.db")
    nbs = NotebookStore(user_dir / "notebooks.db")
    outcome = copy_shared_deck(
        shared_store=shared,
        card_store=cards,
        notebook_store=nbs,
        user_dir=user_dir,
        deck_id="deck_a",
        copier_id="u1",
        idempotency_key=key,
        now=now,
    )
    return shared, cards, nbs, user_dir, outcome


def test_reveal_delivers_cards_to_pull_started_during_copy(tmp_path):
    """A device pulling incrementally while the copy runs gets boundary T_p later
    than the cards' copy-start timestamps. Reveal must re-stamp the cards so the
    next ``since=T_p`` pull returns them, not just the (bumped) notebook row."""
    now = datetime.now(UTC) - timedelta(seconds=30)  # copy started 30s ago
    _shared, cards, nbs, _dir, outcome = _copy_old(tmp_path, now=now)
    assert nbs.get(outcome.notebook_id).is_staged is False
    since = (now + timedelta(seconds=10)).isoformat()  # pull inside the window
    got, _ = _list(tmp_path, cards, nbs, since=since)
    assert sorted(got) == ["w0", "w1", "w2"]


def test_replay_reveal_delivers_cards_to_late_incremental_pull(tmp_path, monkeypatch):
    """Same guarantee on the crash-recovery path: _replay reveals the notebook."""
    from kg.shared_decks.copy import copy_shared_deck

    now = datetime.now(UTC) - timedelta(seconds=30)
    real = NotebookStore.materialize
    state = {"n": 0}

    def flaky(self, nid):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("injected crash before reveal")
        return real(self, nid)

    monkeypatch.setattr(NotebookStore, "materialize", flaky)
    with pytest.raises(RuntimeError, match="injected"):
        _copy_old(tmp_path, now=now)
    user_dir = tmp_path / "users" / "u1"
    from kg.shared_decks.store import SharedDeckStore

    shared = SharedDeckStore(tmp_path / "shared_decks.db")
    cards = CardStore(user_dir / "cards.db")
    nbs = NotebookStore(user_dir / "notebooks.db")
    outcome = copy_shared_deck(
        shared_store=shared,
        card_store=cards,
        notebook_store=nbs,
        user_dir=user_dir,
        deck_id="deck_a",
        copier_id="u1",
        idempotency_key="k1",
        now=now,
    )
    assert outcome.already_copied is True
    since = (now + timedelta(seconds=10)).isoformat()
    got, _ = _list(tmp_path, cards, nbs, since=since)
    assert sorted(got) == ["w0", "w1", "w2"]


def _recopy(tmp_path, *, now, key="k1"):
    """Retry the copy started by :func:`_copy_old` on fresh store handles, as a
    transport retry after a server crash would."""
    from kg.shared_decks.copy import copy_shared_deck
    from kg.shared_decks.store import SharedDeckStore

    user_dir = tmp_path / "users" / "u1"
    shared = SharedDeckStore(tmp_path / "shared_decks.db")
    cards = CardStore(user_dir / "cards.db")
    nbs = NotebookStore(user_dir / "notebooks.db")
    outcome = copy_shared_deck(
        shared_store=shared,
        card_store=cards,
        notebook_store=nbs,
        user_dir=user_dir,
        deck_id="deck_a",
        copier_id="u1",
        idempotency_key=key,
        now=now,
    )
    return shared, cards, nbs, outcome


def test_restamp_failure_after_reveal_is_recovered_by_retry(tmp_path, monkeypatch):
    """A raise from the restamp AFTER materialize committed leaves the notebook
    visible but its cards on their pre-reveal stamps. The retry lands in _replay,
    where materialize is already a no-op; it must still re-stamp the cards so an
    incremental puller whose boundary fell inside the copy window receives them."""
    now = datetime.now(UTC) - timedelta(seconds=30)
    real = CardStore.restamp_by_notebook
    calls = {"n": 0}

    def flaky(self, notebook_id, start):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected crash after reveal")
        return real(self, notebook_id, start)

    monkeypatch.setattr(CardStore, "restamp_by_notebook", flaky)
    with pytest.raises(RuntimeError, match="injected"):
        _copy_old(tmp_path, now=now)

    user_dir = tmp_path / "users" / "u1"
    survivor = NotebookStore(user_dir / "notebooks.db").all(include_staged=True)
    assert len(survivor) == 1 and survivor[0].is_staged is False  # revealed, cards not yet re-stamped

    shared, cards, nbs, outcome = _recopy(tmp_path, now=now)
    assert outcome.already_copied is True
    assert outcome.notebook_id == survivor[0].id
    since = (now + timedelta(seconds=10)).isoformat()
    got, _ = _list(tmp_path, cards, nbs, since=since)
    assert sorted(got) == ["w0", "w1", "w2"]
    assert len(nbs.all(include_staged=True)) == 1  # the retry never mints a second notebook
    assert shared.get("deck_a").download_count == 1


def test_settled_replay_does_not_restamp_again(tmp_path):
    """Once the copy fully finished (reveal + restamp + download counted) an
    idempotent replay is a pure read: it must not bump the deck's cards."""
    now = datetime.now(UTC) - timedelta(seconds=30)
    _shared, cards, _nbs, _dir, outcome = _copy_old(tmp_path, now=now)
    stamps = {c.id: c.updated_at for c in cards.all(notebook_id=outcome.notebook_id)}

    _shared2, cards2, _nbs2, replay = _recopy(tmp_path, now=now)

    assert replay.already_copied is True
    assert {c.id: c.updated_at for c in cards2.all(notebook_id=outcome.notebook_id)} == stamps
