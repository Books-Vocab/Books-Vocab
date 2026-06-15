"""E1 — query-layer bounded cursor pagination for CardStore.

`page_cards` returns at most `limit` cards ordered by the composite cursor
``(updated_at, id)`` using a row-value comparison, so paging is gap-free and
duplicate-free even when many cards share the same ``updated_at``. Backed by a
composite index ``ix_card_updated_at_id``.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlmodel import Session

from kg.cards.store import Card, CardStore


@pytest.fixture()
def store(tmp_path):
    s = CardStore(tmp_path / "cards.db")
    yield s
    s.close()


def _add(store: CardStore, card_id: str, *, updated_at: datetime, notebook_id: str = "default", is_deleted: bool = False) -> Card:
    # Insert directly so the test controls id + updated_at exactly (store.add
    # generates its own id/timestamps).
    card = Card(
        id=card_id,
        content=f"word-{card_id}",
        meaning="m",
        updated_at=updated_at,
        notebook_id=notebook_id,
        is_deleted=is_deleted,
    )
    with Session(store.engine) as session:
        session.add(card)
        session.commit()
        session.refresh(card)
    return card


def _seed_distinct(store: CardStore, n: int, base: datetime) -> list[str]:
    ids = []
    for i in range(n):
        cid = f"c{i:03d}"
        _add(store, cid, updated_at=base + timedelta(seconds=i))
        ids.append(cid)
    return ids


def test_page_after_cursor_returns_bounded(store):
    base = datetime(2024, 1, 1, 0, 0, 0)
    _seed_distinct(store, 10, base)

    page = store.page_cards(limit=4, after=None, include_deleted=False, notebook_id=None)
    assert len(page) == 4
    # ascending by (updated_at, id)
    assert [c.id for c in page] == ["c000", "c001", "c002", "c003"]


def test_page_cursor_no_gap_no_dup(store):
    base = datetime(2024, 1, 1, 0, 0, 0)
    all_ids = _seed_distinct(store, 7, base)

    collected: list[str] = []
    after = None
    for _ in range(5):  # more than enough iterations to drain
        page = store.page_cards(limit=3, after=after, include_deleted=False, notebook_id=None)
        if not page:
            break
        collected.extend(c.id for c in page)
        last = page[-1]
        after = (last.updated_at, last.id)

    # union over 3 pages == whole table, no duplicates
    assert collected == all_ids
    assert len(collected) == len(set(collected))


def test_page_same_timestamp_tiebreak_by_id(store):
    ts = datetime(2024, 1, 1, 12, 0, 0)
    # All identical updated_at — ordering must fall back to id.
    for cid in ["c_z", "c_a", "c_m", "c_b"]:
        _add(store, cid, updated_at=ts)

    page1 = store.page_cards(limit=2, after=None, include_deleted=False, notebook_id=None)
    assert [c.id for c in page1] == ["c_a", "c_b"]

    last = page1[-1]
    page2 = store.page_cards(limit=2, after=(last.updated_at, last.id), include_deleted=False, notebook_id=None)
    assert [c.id for c in page2] == ["c_m", "c_z"]


def test_page_respects_notebook_id(store):
    base = datetime(2024, 1, 1, 0, 0, 0)
    _add(store, "a1", updated_at=base, notebook_id="nbA")
    _add(store, "b1", updated_at=base + timedelta(seconds=1), notebook_id="nbB")
    _add(store, "a2", updated_at=base + timedelta(seconds=2), notebook_id="nbA")

    page = store.page_cards(limit=10, after=None, include_deleted=False, notebook_id="nbA")
    assert {c.id for c in page} == {"a1", "a2"}


def test_page_include_deleted_flag(store):
    base = datetime(2024, 1, 1, 0, 0, 0)
    _add(store, "live", updated_at=base)
    _add(store, "dead", updated_at=base + timedelta(seconds=1), is_deleted=True)

    excluded = store.page_cards(limit=10, after=None, include_deleted=False, notebook_id=None)
    assert {c.id for c in excluded} == {"live"}

    included = store.page_cards(limit=10, after=None, include_deleted=True, notebook_id=None)
    assert {c.id for c in included} == {"live", "dead"}


def test_index_exists(store):
    from sqlalchemy import text

    with store.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='card'")
        ).all()
    names = {r[0] for r in rows}
    assert "ix_card_updated_at_id" in names
    # old single-column index preserved
    assert "ix_card_updated_at" in names
