"""Tests for hide-link feature: blocked pairs and hidden status."""

from __future__ import annotations

import json

import pytest

from kg.graph import GraphLink, GraphStore, LinkKind


@pytest.fixture()
def store(tmp_path):
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
    )


class TestBlockedPairs:
    """Task 1: _blocked_pairs persistence."""

    def test_hard_delete_removes_link(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        assert store.get_link(lk.id) is None

    def test_hard_delete_returns_pair(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        pair = store.hard_delete_link(lk.id)
        assert pair == ("a", "b")

    def test_hard_delete_adds_to_blocked(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        assert store.is_blocked("a", "b") is True

    def test_is_blocked_bidirectional(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        assert store.is_blocked("b", "a") is True

    def test_has_link_returns_true_for_blocked(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        assert store.has_link("a", "b") is True

    def test_add_candidate_skips_blocked_pair(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        store.add_candidate("a", "b", 0.85)
        assert store.candidate_count() == 0

    def test_blocked_persists_across_reload(self, store, tmp_path):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        reloaded = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
        )
        assert reloaded.is_blocked("a", "b") is True

    def test_remove_blocked_pairs_for(self, store):
        lk1 = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        lk2 = store.add_link("a", "c", LinkKind.SHARES_USAGE, 0.8, "r")
        store.hard_delete_link(lk1.id)
        store.hard_delete_link(lk2.id)
        store.remove_blocked_pairs_for("a")
        assert store.is_blocked("a", "b") is False
        assert store.is_blocked("a", "c") is False

    def test_unblock_pair(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        store.unblock_pair("a", "b")
        assert store.is_blocked("a", "b") is False


class TestHiddenStatus:
    """Task 2: hidden status behavior."""

    def test_hide_link_sets_status(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        assert store.get_link(lk.id).status == "hidden"

    def test_unhide_link_sets_active(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        store.unhide_link(lk.id)
        assert store.get_link(lk.id).status == "active"

    def test_get_links_for_includes_hidden(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        links = store.get_links_for("a")
        assert len(links) == 1
        assert links[0].status == "hidden"

    def test_has_link_true_for_hidden(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        assert store.has_link("a", "b") is True

    def test_find_link_between_finds_hidden(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        found = store.find_link_between("a", "b")
        assert found is not None
        assert found.status == "hidden"

    def test_link_count_excludes_hidden(self, store):
        store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r1")
        lk2 = store.add_link("c", "d", LinkKind.SHARES_USAGE, 0.8, "r2")
        store.hide_link(lk2.id)
        assert store.link_count() == 1

    def test_add_candidate_skips_hidden_pair(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(lk.id)
        store.add_candidate("a", "b", 0.85)
        assert store.candidate_count() == 0

    def test_hide_nonexistent_raises(self, store):
        with pytest.raises(KeyError):
            store.hide_link("nonexistent")


class TestRejectedMigration:
    """Task 2: rejected links migrate to blocked on load."""

    def test_rejected_links_become_blocked_on_load(self, tmp_path):
        # Write a links file with a rejected link directly
        links_data = [
            {
                "id": "lk1",
                "from_id": "a",
                "to_id": "b",
                "kind": "contrasts_with",
                "confidence": 0.9,
                "reason": "old",
                "created_at": "2026-01-01T00:00:00Z",
                "status": "rejected",
            },
            {
                "id": "lk2",
                "from_id": "c",
                "to_id": "d",
                "kind": "shares_usage",
                "confidence": 0.8,
                "reason": "active one",
                "created_at": "2026-01-01T00:00:00Z",
                "status": "active",
            },
        ]
        links_path = tmp_path / "links.json"
        links_path.write_text(json.dumps(links_data))

        store = GraphStore(
            links_path=links_path,
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
        )
        # rejected link should be migrated to blocked, not loaded as link
        assert store.get_link("lk1") is None
        assert store.is_blocked("a", "b") is True
        # active link should still be there
        assert store.get_link("lk2") is not None
        assert store.link_count() == 1
