"""Tests for GraphStore pending_judge functionality."""

from __future__ import annotations

import json

import pytest

from kg.graph import GraphStore


@pytest.fixture()
def store(tmp_path):
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
        pending_judge_path=tmp_path / "pending_judge.json",
    )


class TestAddAndPopPendingJudge:
    def test_add_and_pop(self, store):
        store.add_pending_judge(["card_a", "card_b"])
        assert store.pending_judge_count() == 2

        popped = store.pop_pending_judge()
        assert set(popped) == {"card_a", "card_b"}
        assert store.pending_judge_count() == 0

    def test_add_single_string(self, store):
        store.add_pending_judge("card_a")
        assert store.pending_judge_count() == 1

    def test_pop_empty(self, store):
        popped = store.pop_pending_judge()
        assert popped == []


class TestPendingJudgeDedup:
    def test_adding_same_id_twice(self, store):
        store.add_pending_judge(["card_a"])
        store.add_pending_judge(["card_a"])
        assert store.pending_judge_count() == 1

        popped = store.pop_pending_judge()
        assert set(popped) == {"card_a"}


class TestAddPendingJudgeFlushFailure:
    def _make_store(self, tmp_path, pj_path):
        return GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=pj_path,
        )

    def test_flush_failure_keeps_memory_and_disk_consistent(self, tmp_path):
        pj_path = tmp_path / "pending_judge.json"
        store = self._make_store(tmp_path, pj_path)
        store.add_pending_judge(["card_a"])

        def boom(snapshot):
            raise OSError("disk full")

        store._flush_pending_judge = boom

        with pytest.raises(OSError):
            store.add_pending_judge(["card_b"])

        mem = set(store._pending_judge)
        disk = {r for r in json.loads(pj_path.read_text()) if isinstance(r, str)}
        assert mem == disk == {"card_a"}

        reloaded = self._make_store(tmp_path, pj_path)
        assert reloaded._pending_judge == {"card_a"}


class TestPendingJudgePersistence:
    def test_survives_reload(self, tmp_path):
        pj_path = tmp_path / "pending_judge.json"
        store1 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=pj_path,
        )
        store1.add_pending_judge(["card_x", "card_y"])

        # Reload from disk
        store2 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=pj_path,
        )
        assert store2.pending_judge_count() == 2
        assert set(store2.pop_pending_judge()) == {"card_x", "card_y"}


class TestRemovePendingJudgeFor:
    def test_remove_specific_card(self, store):
        store.add_pending_judge(["card_a", "card_b", "card_c"])

        store.remove_pending_judge_for("card_b")
        assert store.pending_judge_count() == 2
        assert set(store.pop_pending_judge()) == {"card_a", "card_c"}

    def test_flush_failure_keeps_memory_and_disk_consistent(self, tmp_path):
        pj_path = tmp_path / "pending_judge.json"
        store = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=pj_path,
        )
        store.add_pending_judge(["card_a", "card_b"])

        def boom(snapshot):
            raise OSError("disk full")

        store._flush_pending_judge = boom

        with pytest.raises(OSError):
            store.remove_pending_judge_for("card_a")

        assert store._pending_judge == {"card_a", "card_b"}
        assert {r for r in json.loads(pj_path.read_text()) if isinstance(r, str)} == {"card_a", "card_b"}
        reloaded = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=pj_path,
        )
        assert reloaded._pending_judge == {"card_a", "card_b"}

    def test_successful_removal_persists_only_requested_card_removal(self, tmp_path):
        pj_path = tmp_path / "pending_judge.json"
        store = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=pj_path,
        )
        store.add_pending_judge(["card_a", "card_b", "card_c"])

        assert store.remove_pending_judge_for("card_b") == 1
        assert {r for r in json.loads(pj_path.read_text()) if isinstance(r, str)} == {"card_a", "card_c"}

        reloaded = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=pj_path,
        )
        assert reloaded._pending_judge == {"card_a", "card_c"}

    def test_remove_nonexistent_is_noop(self, store):
        store.add_pending_judge(["card_a"])
        store.remove_pending_judge_for("card_z")
        assert store.pending_judge_count() == 1

    def test_cleanup_for_card_removes_pending(self, store):
        store.add_pending_judge(["card_a", "card_b"])
        result = store.cleanup_for_card("card_a")
        assert result["pending_judge_removed"] == 1
        assert store.pending_judge_count() == 1

    def test_cleanup_for_card_persists_remainder_for_reload(self, tmp_path):
        pj_path = tmp_path / "pending_judge.json"
        store = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=pj_path,
        )
        store.add_pending_judge(["card_a", "card_b"])

        result = store.cleanup_for_card("card_a")

        assert result["pending_judge_removed"] == 1
        reloaded = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=pj_path,
        )
        assert reloaded._pending_judge == {"card_b"}


class TestPendingJudgeLoadValidation:
    """W11: pending_judge JSON load must validate type."""

    def _make_store(self, tmp_path, pj_path):
        return GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=pj_path,
        )

    def test_dict_json_resets_to_empty(self, tmp_path):
        pj_path = tmp_path / "pending_judge.json"
        pj_path.write_text(json.dumps({"bad": "data"}))
        store = self._make_store(tmp_path, pj_path)
        assert store.pending_judge_count() == 0

    def test_int_json_resets_to_empty(self, tmp_path):
        pj_path = tmp_path / "pending_judge.json"
        pj_path.write_text(json.dumps(42))
        store = self._make_store(tmp_path, pj_path)
        assert store.pending_judge_count() == 0

    def test_string_json_resets_to_empty(self, tmp_path):
        pj_path = tmp_path / "pending_judge.json"
        pj_path.write_text(json.dumps("not a list"))
        store = self._make_store(tmp_path, pj_path)
        assert store.pending_judge_count() == 0

    def test_list_with_non_string_elements_filters(self, tmp_path):
        pj_path = tmp_path / "pending_judge.json"
        pj_path.write_text(json.dumps(["card_a", 123, None, "card_b"]))
        store = self._make_store(tmp_path, pj_path)
        assert store.pending_judge_count() == 2
        assert store._pending_judge == {"card_a", "card_b"}

    def test_valid_list_loads_normally(self, tmp_path):
        pj_path = tmp_path / "pending_judge.json"
        pj_path.write_text(json.dumps(["card_x", "card_y"]))
        store = self._make_store(tmp_path, pj_path)
        assert store.pending_judge_count() == 2


class TestPendingJudgeClaim:
    """#2084: ``pop_pending_judge`` claims ids instead of deleting them.

    A claimed id stays in the durable pending file until
    ``ack_pending_judge`` (its links are persisted) or ``add_pending_judge``
    (handed back), so a process killed mid-judge leaves it for the next
    process. Durable view == queued ∪ claimed; memory and disk never diverge.
    """

    def _make_store(self, tmp_path):
        return GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=tmp_path / "pending_judge.json",
        )

    @staticmethod
    def _disk(tmp_path):
        rows = json.loads((tmp_path / "pending_judge.json").read_text())
        return {row for row in rows if isinstance(row, str)}

    def test_pop_keeps_ids_on_disk_until_ack(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add_pending_judge(["card_a", "card_b"])

        assert store.pop_pending_judge() == ["card_a", "card_b"]
        assert store.pending_judge_count() == 0
        assert self._disk(tmp_path) == {"card_a", "card_b"}

        store.ack_pending_judge(["card_a"])
        assert self._disk(tmp_path) == {"card_b"}
        store.ack_pending_judge(["card_b"])
        assert self._disk(tmp_path) == set()
        assert self._make_store(tmp_path)._pending_judge == set()

    def test_pop_performs_no_disk_write(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add_pending_judge(["card_a", "card_b"])

        def boom(snapshot):
            raise OSError("disk full")

        store._flush_pending_judge = boom

        assert store.pop_pending_judge() == ["card_a", "card_b"]
        assert self._disk(tmp_path) == {"card_a", "card_b"}

    def test_requeue_of_claimed_id_makes_it_poppable_again(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add_pending_judge(["card_a"])
        assert store.pop_pending_judge() == ["card_a"]

        store.add_pending_judge(["card_a"])

        assert store.pending_judge_count() == 1
        assert store.pop_pending_judge() == ["card_a"]
        assert self._disk(tmp_path) == {"card_a"}

    def test_add_while_claim_in_flight_keeps_claimed_ids_on_disk(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add_pending_judge(["card_a"])
        store.pop_pending_judge()

        store.add_pending_judge(["card_b"])

        assert self._disk(tmp_path) == {"card_a", "card_b"}
        assert store.pop_pending_judge() == ["card_b"]

    def test_remove_claimed_card_drops_it_durably(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add_pending_judge(["card_a", "card_b"])
        store.pop_pending_judge()

        assert store.remove_pending_judge_for("card_a") == 1

        assert self._disk(tmp_path) == {"card_b"}
        store.ack_pending_judge(["card_a", "card_b"])
        assert self._disk(tmp_path) == set()

    def test_ack_ignores_ids_that_are_not_claimed(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add_pending_judge(["card_a"])

        store.ack_pending_judge(["card_a", "card_z"])

        assert store.pending_judge_count() == 1
        assert self._disk(tmp_path) == {"card_a"}

    def test_same_process_fresh_store_does_not_take_a_live_claim(self, tmp_path):
        owner = self._make_store(tmp_path)
        owner.add_pending_judge(["card_a"])
        owner.pop_pending_judge()

        # e.g. the store cache evicted `owner` while its judge run continues.
        assert self._make_store(tmp_path)._pending_judge == set()

        owner.add_pending_judge(["card_a"])  # owner hands the claim back
        assert self._make_store(tmp_path)._pending_judge == {"card_a"}

    def test_ack_flush_failure_keeps_claim_durable(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add_pending_judge(["card_a", "card_b"])
        store.pop_pending_judge()
        original_flush = store._flush_pending_judge

        def boom(snapshot):
            raise OSError("disk full")

        store._flush_pending_judge = boom
        with pytest.raises(OSError):
            store.ack_pending_judge(["card_a"])
        store._flush_pending_judge = original_flush

        assert self._disk(tmp_path) == {"card_a", "card_b"}
        store.ack_pending_judge(["card_a", "card_b"])
        assert self._disk(tmp_path) == set()


class TestAckOwnership:
    """#2084 follow-up: an ack removes only what its own claim covers.

    The durable record distinguishes "claimed under generation G" from
    "enqueued after G", so a second store on the same file (cache eviction
    while a judge run is live) that enqueues a claimed id again is not erased
    by the first store's ack.
    """

    @staticmethod
    def _make_store(tmp_path):
        return GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=tmp_path / "pending_judge.json",
        )

    @staticmethod
    def _disk(tmp_path):
        rows = json.loads((tmp_path / "pending_judge.json").read_text())
        return {row for row in rows if isinstance(row, str)}

    def test_ack_does_not_erase_a_later_enqueue_by_another_store(self, tmp_path):
        a = self._make_store(tmp_path)
        a.add_pending_judge(["c1"])
        assert a.pop_pending_judge() == ["c1"]

        b = self._make_store(tmp_path)  # e.g. store-cache eviction created it
        assert b._pending_judge == set()  # c1 is A's live claim
        b.add_pending_judge("c1")  # intake / embedding retry enqueues it again

        a.ack_pending_judge(["c1"])

        assert self._disk(tmp_path) == {"c1"}
        assert self._make_store(tmp_path)._pending_judge == {"c1"}
        # A's later, unrelated flushes must not take it either.
        a.add_pending_judge(["c9"])
        assert self._disk(tmp_path) == {"c1", "c9"}
        # ...and B can still settle its own enqueue.
        assert b.pop_pending_judge() == ["c1"]
        b.ack_pending_judge(["c1"])
        assert self._disk(tmp_path) == {"c9"}

    def test_ack_still_removes_ids_only_its_own_claim_covers(self, tmp_path):
        a = self._make_store(tmp_path)
        a.add_pending_judge(["c1", "c2"])
        a.pop_pending_judge()
        b = self._make_store(tmp_path)
        b.add_pending_judge("c1")

        a.ack_pending_judge(["c1", "c2"])

        assert self._disk(tmp_path) == {"c1"}

    def test_legacy_file_without_generations_is_claimed_at_generation_zero(self, tmp_path):
        (tmp_path / "pending_judge.json").write_text(json.dumps(["c1", "c2"]))
        a = self._make_store(tmp_path)
        assert a.pop_pending_judge() == ["c1", "c2"]
        b = self._make_store(tmp_path)
        b.add_pending_judge("c1")

        a.ack_pending_judge(["c1", "c2"])

        assert self._disk(tmp_path) == {"c1"}
        solo = self._make_store(tmp_path)
        solo.pop_pending_judge()
        solo.ack_pending_judge(["c1"])
        assert self._disk(tmp_path) == set()

    def test_ids_stay_a_plain_string_list_for_old_readers(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add_pending_judge(["c1", "c2"])

        rows = json.loads((tmp_path / "pending_judge.json").read_text())

        # Old code keeps only str rows; generation metadata must not hide ids.
        assert [row for row in rows if isinstance(row, str)] == ["c1", "c2"]

    def test_explicit_removal_still_wins_over_a_later_enqueue(self, tmp_path):
        a = self._make_store(tmp_path)
        a.add_pending_judge(["c1"])
        a.pop_pending_judge()
        b = self._make_store(tmp_path)
        b.add_pending_judge("c1")

        # Deleting the card is not an ack: the id must go regardless.
        assert a.remove_pending_judge_for("c1") == 1

        assert self._disk(tmp_path) == set()


class TestMigrateCandidatesToPending:
    def test_migrate_old_candidates(self, tmp_path):
        """Old candidates.json data gets migrated to pending_judge on load."""
        cand_path = tmp_path / "candidates.json"
        pj_path = tmp_path / "pending_judge.json"

        # Write old-style candidates data
        old_candidates = [
            {"from_id": "card_a", "to_id": "card_b", "similarity": 0.85, "created_at": "2026-01-01T00:00:00Z"},
            {"from_id": "card_c", "to_id": "card_d", "similarity": 0.72, "created_at": "2026-01-01T00:00:00Z"},
        ]
        cand_path.write_text(json.dumps(old_candidates))

        store = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=cand_path,
            blocked_path=tmp_path / "blocked.json",
            pending_judge_path=pj_path,
        )

        # Old candidates from_ids should be migrated to pending_judge
        assert store.pending_judge_count() == 2  # card_a, card_c (unique from_ids)
        popped = store.pop_pending_judge()
        assert set(popped) == {"card_a", "card_c"}

        # Old candidates should be cleared after migration
        assert store.candidate_count() == 0

    def test_no_migration_without_pending_judge_path(self, tmp_path):
        """Without pending_judge_path, candidates stay as-is."""
        cand_path = tmp_path / "candidates.json"
        old_candidates = [
            {"from_id": "card_a", "to_id": "card_b", "similarity": 0.85, "created_at": "2026-01-01T00:00:00Z"},
        ]
        cand_path.write_text(json.dumps(old_candidates))

        store = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=cand_path,
            blocked_path=tmp_path / "blocked.json",
        )
        # candidates should still be there (no migration)
        assert len(store._candidates) == 1
