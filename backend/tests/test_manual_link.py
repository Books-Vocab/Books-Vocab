from __future__ import annotations
import pytest
from kg.graph import GraphStore, LinkKind

@pytest.fixture()
def store(tmp_path):
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
    )

class TestRejectedStatus:
    def test_has_link_returns_true_for_rejected(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.reject_link(lk.id)
        assert store.has_link("a", "b") is True

    def test_get_links_for_excludes_rejected(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.reject_link(lk.id)
        assert store.get_links_for("a") == []

    def test_add_candidate_skips_rejected_pair(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.reject_link(lk.id)
        store.add_candidate("a", "b", 0.85)
        assert store.candidate_count() == 0

    def test_reject_nonexistent_link_raises(self, store):
        with pytest.raises(KeyError):
            store.reject_link("nonexistent")

class TestFindLinkBetween:
    def test_finds_active_link(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        found = store.find_link_between("a", "b")
        assert found is not None
        assert found.id == lk.id

    def test_finds_link_reverse_direction(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        found = store.find_link_between("b", "a")
        assert found is not None
        assert found.id == lk.id

    def test_finds_rejected_link(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.reject_link(lk.id)
        found = store.find_link_between("a", "b")
        assert found is not None
        assert found.status == "rejected"

    def test_returns_none_when_no_link(self, store):
        assert store.find_link_between("a", "b") is None

    def test_skips_deprecated_link(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.deprecate_links_for("a")
        found = store.find_link_between("a", "b")
        assert found is None
