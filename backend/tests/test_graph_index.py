from __future__ import annotations

import pytest

from kg.graph import GraphLink, GraphStore, LinkKind


@pytest.fixture()
def store(tmp_path):
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
    )


class TestGetLinksFor:
    def test_empty_graph_returns_empty(self, store):
        assert store.get_links_for("card_a") == []

    def test_from_end_found(self, store):
        lk = store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        result = store.get_links_for("card_a")
        assert len(result) == 1
        assert result[0].id == lk.id

    def test_to_end_found(self, store):
        lk = store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        result = store.get_links_for("card_b")
        assert len(result) == 1
        assert result[0].id == lk.id

    def test_multiple_links(self, store):
        lk1 = store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r1")
        lk2 = store.add_link("card_a", "card_c", LinkKind.CONTRASTS_WITH, 0.8, "r2")
        lk3 = store.add_link("card_d", "card_b", LinkKind.SHARES_USAGE, 0.7, "r3")
        result_a = store.get_links_for("card_a")
        assert {lk.id for lk in result_a} == {lk1.id, lk2.id}
        result_b = store.get_links_for("card_b")
        assert {lk.id for lk in result_b} == {lk1.id, lk3.id}

    def test_deprecated_link_excluded(self, store):
        lk = store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        lk.status = "deprecated"
        store._links[lk.id] = lk
        result = store.get_links_for("card_a")
        assert result == []


class TestHasLink:
    def test_no_link_returns_false(self, store):
        assert store.has_link("card_a", "card_b") is False

    def test_link_found_forward(self, store):
        store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        assert store.has_link("card_a", "card_b") is True

    def test_link_found_reverse(self, store):
        store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        assert store.has_link("card_b", "card_a") is True

    def test_deprecated_link_not_found(self, store):
        lk = store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        lk.status = "deprecated"
        store._links[lk.id] = lk
        assert store.has_link("card_a", "card_b") is False
