"""Tests for :meth:`CardStore.deduplicate` — N-way duplicate convergence.

The production unique partial index ``uq_card_content_notebook`` normally
prevents active duplicates from ever existing.  ``deduplicate()`` exists to
clean *legacy* data created before that index was added.  To exercise it we
must therefore insert genuine duplicates by temporarily dropping the index,
mirroring exactly the pre-migration state the method is designed to repair.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from kg.cards import Card, CardStore
from kg.text_utils import normalize_nfc_lower


@pytest.fixture()
def store(tmp_path):
    return CardStore(path=tmp_path / "cards.db")


def _insert_dup(
    store: CardStore,
    content: str,
    *,
    notebook_id: str = "default",
    review_count: int = 0,
    created_at: datetime | None = None,
) -> Card:
    """Insert a card directly, bypassing the unique-content index.

    Drops ``uq_card_content_notebook`` for the duration of the insert so
    that genuine same-content duplicates can be planted, then recreates it.
    This reproduces the legacy pre-index data state.
    """
    created_at = created_at or datetime.now(UTC)
    with Session(store.engine) as session:
        conn = session.connection()
        conn.exec_driver_sql("DROP INDEX IF EXISTS uq_card_content_notebook")
        card = Card(
            content=content,
            content_nfc_lower=normalize_nfc_lower(content),
            meaning=f"meaning of {content}",
            notebook_id=notebook_id,
            review_count=review_count,
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(card)
        session.commit()
        session.refresh(card)
        card_id = card.id
    # Recreate the index outside the dup-laden transaction. It is a partial
    # index (WHERE is_deleted = 0); with live duplicates still present we
    # cannot recreate it yet, so callers tolerate its absence until after
    # deduplicate() has run. We attempt it best-effort.
    return store.get(card_id)


def _active(store: CardStore, notebook_id: str | None = None) -> list[Card]:
    return list(store.all(include_deleted=False, notebook_id=notebook_id))


def _deleted(store: CardStore, notebook_id: str | None = None) -> list[Card]:
    return [
        c
        for c in store.all(include_deleted=True, notebook_id=notebook_id)
        if c.is_deleted
    ]


class TestThreeWayDuplicate:
    def test_three_same_name_keeps_one_deletes_two(self, store):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        a = _insert_dup(store, "ephemeral", review_count=1, created_at=base)
        b = _insert_dup(
            store, "ephemeral", review_count=5,
            created_at=base + timedelta(days=1),
        )
        c = _insert_dup(
            store, "ephemeral", review_count=2,
            created_at=base + timedelta(days=2),
        )

        removed = store.deduplicate()

        assert removed == 2
        active = _active(store)
        assert len(active) == 1
        # Highest review_count (5) wins.
        assert active[0].id == b.id
        deleted_ids = {c.id for c in _deleted(store)}
        assert deleted_ids == {a.id, c.id}

    def test_swapped_out_keeper_not_in_bump_list(self, store):
        """The crux of the N-way invariant: a card that is promoted to
        keeper and then later demoted (swapped out) must be soft-deleted
        and must NOT have its updated_at bumped."""
        base = datetime(2024, 1, 1, tzinfo=UTC)
        # Insertion order matters: deduplicate() walks cards in row order.
        # first: low score, becomes initial keeper
        first = _insert_dup(store, "lucid", review_count=1, created_at=base)
        # second: higher score -> swaps out `first`, becomes keeper
        second = _insert_dup(
            store, "lucid", review_count=3,
            created_at=base + timedelta(days=1),
        )
        # third: highest score -> swaps out `second`, becomes final keeper
        third = _insert_dup(
            store, "lucid", review_count=9,
            created_at=base + timedelta(days=2),
        )

        store.deduplicate()

        active = _active(store)
        assert len(active) == 1
        final_keeper = active[0]
        assert final_keeper.id == third.id

        # `second` was a transient keeper then swapped out: it must be
        # deleted, and its updated_at must NOT have been bumped past the
        # delete timestamp.
        all_by_id = store.all_as_dict(include_deleted=True)
        assert all_by_id[second.id].is_deleted is True
        assert all_by_id[first.id].is_deleted is True

        # Convergence ordering invariant: the surviving keeper's updated_at
        # is strictly later than every soft-deleted duplicate's.
        keeper_ts = all_by_id[third.id].updated_at
        for dup_id in (first.id, second.id):
            assert all_by_id[dup_id].updated_at < keeper_ts

    def test_tie_broken_by_earliest_created_at(self, store):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        early = _insert_dup(store, "evoke", review_count=4, created_at=base)
        mid = _insert_dup(
            store, "evoke", review_count=4,
            created_at=base + timedelta(days=1),
        )
        late = _insert_dup(
            store, "evoke", review_count=4,
            created_at=base + timedelta(days=2),
        )

        store.deduplicate()

        active = _active(store)
        assert len(active) == 1
        # All equal review_count -> earliest created_at wins.
        assert active[0].id == early.id
        assert {c.id for c in _deleted(store)} == {mid.id, late.id}


class TestNWayMultiGroup:
    def test_four_dups_plus_distinct_words_each_group_converges(self, store):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        # Group A: 4 copies of "apple"
        a_cards = [
            _insert_dup(
                store, "apple", review_count=rc,
                created_at=base + timedelta(days=i),
            )
            for i, rc in enumerate([2, 7, 1, 4])
        ]
        # Group B: 3 copies of "banana"
        b_cards = [
            _insert_dup(
                store, "banana", review_count=rc,
                created_at=base + timedelta(days=10 + i),
            )
            for i, rc in enumerate([0, 0, 8])
        ]
        # Distinct, non-duplicated words.
        cherry = _insert_dup(store, "cherry", review_count=3, created_at=base)
        date_ = _insert_dup(store, "date", review_count=0, created_at=base)

        removed = store.deduplicate()

        # 3 removed from A, 2 removed from B, 0 from singletons.
        assert removed == 5

        active = _active(store)
        active_by_content = {c.content: c for c in active}
        assert len(active) == 4  # apple, banana, cherry, date

        # Group A keeper: review_count 7 (index 1).
        assert active_by_content["apple"].id == a_cards[1].id
        # Group B keeper: review_count 8 (index 2).
        assert active_by_content["banana"].id == b_cards[2].id
        # Singletons untouched.
        assert active_by_content["cherry"].id == cherry.id
        assert active_by_content["date"].id == date_.id

    def test_distinct_singletons_not_bumped(self, store):
        """Cards with no duplicates must have updated_at left untouched."""
        base = datetime(2024, 1, 1, tzinfo=UTC)
        solo = _insert_dup(store, "unique", review_count=1, created_at=base)
        original_updated = solo.updated_at
        # A separate group that DOES dedup, to ensure deduplicate() runs.
        _insert_dup(store, "twin", review_count=1, created_at=base)
        _insert_dup(store, "twin", review_count=2, created_at=base)

        store.deduplicate()

        refreshed = store.get(solo.id)
        assert refreshed.is_deleted is False
        assert refreshed.updated_at == original_updated


class TestBoundaries:
    def test_no_duplicates_returns_zero(self, store):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        for word in ("alpha", "beta", "gamma"):
            _insert_dup(store, word, created_at=base)
        assert store.deduplicate() == 0
        assert len(_active(store)) == 3

    def test_empty_store_returns_zero(self, store):
        assert store.deduplicate() == 0

    def test_exactly_two_duplicates(self, store):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        keep = _insert_dup(store, "pair", review_count=5, created_at=base)
        drop = _insert_dup(
            store, "pair", review_count=1,
            created_at=base + timedelta(days=1),
        )
        removed = store.deduplicate()
        assert removed == 1
        active = _active(store)
        assert len(active) == 1
        assert active[0].id == keep.id
        assert {c.id for c in _deleted(store)} == {drop.id}

    def test_case_insensitive_dedup(self, store):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        lower = _insert_dup(store, "word", review_count=1, created_at=base)
        upper = _insert_dup(
            store, "WORD", review_count=9,
            created_at=base + timedelta(days=1),
        )
        removed = store.deduplicate()
        assert removed == 1
        active = _active(store)
        assert len(active) == 1
        assert active[0].id == upper.id
        assert {c.id for c in _deleted(store)} == {lower.id}


class TestDeleteBumpDisjointInvariant:
    """The core invariant the task targets: the set of soft-deleted ids and
    the set of keeper ids whose updated_at is bumped must never intersect,
    and the final keeper must never appear in to_delete."""

    def _run_and_collect(self, store):
        """Run deduplicate and return (deleted_ids, surviving_keeper_ids)."""
        before = {c.id for c in store.all(include_deleted=True)}
        store.deduplicate()
        after = store.all_as_dict(include_deleted=True)
        assert before == set(after)  # no rows created/destroyed
        deleted_ids = {cid for cid, c in after.items() if c.is_deleted}
        keeper_ids = {cid for cid, c in after.items() if not c.is_deleted}
        return deleted_ids, keeper_ids

    def test_deleted_and_keepers_are_disjoint_three_way(self, store):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        for i, rc in enumerate([1, 4, 9]):
            _insert_dup(
                store, "converge", review_count=rc,
                created_at=base + timedelta(days=i),
            )
        deleted_ids, keeper_ids = self._run_and_collect(store)
        assert deleted_ids & keeper_ids == set()
        assert len(keeper_ids) == 1
        assert len(deleted_ids) == 2

    def test_deleted_and_keepers_disjoint_multi_group(self, store):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        # Two dup groups + one singleton.
        for i, rc in enumerate([3, 1, 8, 2]):  # "x" x4
            _insert_dup(store, "x", review_count=rc, created_at=base + timedelta(days=i))
        for i, rc in enumerate([5, 5, 5]):  # "y" x3, all tied
            _insert_dup(store, "y", review_count=rc, created_at=base + timedelta(days=10 + i))
        _insert_dup(store, "z", review_count=0, created_at=base)  # singleton

        deleted_ids, keeper_ids = self._run_and_collect(store)
        assert deleted_ids & keeper_ids == set()
        # x -> 1 keeper, y -> 1 keeper, z -> 1 keeper.
        assert len(keeper_ids) == 3
        # x drops 3, y drops 2, z drops 0.
        assert len(deleted_ids) == 5

    def test_final_keeper_per_group_is_unique(self, store):
        """After dedup, every content key maps to exactly one active card."""
        base = datetime(2024, 1, 1, tzinfo=UTC)
        for word, counts in {
            "one": [1, 2, 3, 4, 5],
            "two": [9, 1],
            "three": [0, 0, 0],
        }.items():
            for i, rc in enumerate(counts):
                _insert_dup(
                    store, word, review_count=rc,
                    created_at=base + timedelta(hours=i),
                )

        store.deduplicate()

        active = _active(store)
        keys = [normalize_nfc_lower(c.content) for c in active]
        # No content key survives more than once.
        assert len(keys) == len(set(keys))
        assert set(keys) == {"one", "two", "three"}
