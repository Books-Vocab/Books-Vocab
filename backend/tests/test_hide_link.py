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
