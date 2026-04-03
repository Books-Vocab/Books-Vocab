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

    def test_remove_nonexistent_is_noop(self, store):
        store.add_pending_judge(["card_a"])
        store.remove_pending_judge_for("card_z")
        assert store.pending_judge_count() == 1

    def test_cleanup_for_card_removes_pending(self, store):
        store.add_pending_judge(["card_a", "card_b"])
        result = store.cleanup_for_card("card_a")
        assert result["pending_judge_removed"] == 1
        assert store.pending_judge_count() == 1


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


class TestMigrateCandidatesToPending:
    def test_migrate_old_candidates(self, tmp_path):
        """Old candidates.json data gets migrated to pending_judge on load."""
        cand_path = tmp_path / "candidates.json"
        pj_path = tmp_path / "pending_judge.json"

        # Write old-style candidates data
        old_candidates = [
            {"from_id": "card_a", "to_id": "card_b", "similarity": 0.85,
             "created_at": "2026-01-01T00:00:00Z"},
            {"from_id": "card_c", "to_id": "card_d", "similarity": 0.72,
             "created_at": "2026-01-01T00:00:00Z"},
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
            {"from_id": "card_a", "to_id": "card_b", "similarity": 0.85,
             "created_at": "2026-01-01T00:00:00Z"},
        ]
        cand_path.write_text(json.dumps(old_candidates))

        store = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=cand_path,
            blocked_path=tmp_path / "blocked.json",
        )
        # candidates should still be there (no migration)
        assert len(store._candidates) == 1
