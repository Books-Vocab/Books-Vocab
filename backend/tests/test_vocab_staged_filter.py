"""Issue #2269: cards of a staged (copy-in-progress) notebook must not leak into
the global (notebook_id=None) vocab pull, on both the full-sync and incremental
paths; materialize reveals them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
