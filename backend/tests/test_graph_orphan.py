from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from kg.graph import GraphStore, LinkKind
from kg.vocab_service import delete_vocab_word


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def graph_store(tmp_path):
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
    )


@dataclass
class _FakeCard:
    id: str
    content: str
    is_deleted: bool = False


class _FakeCardsStore:
    def __init__(self, cards):
        self._cards = list(cards)
        self.deleted = None

    def all(self, include_deleted: bool = False):
        if include_deleted:
            return list(self._cards)
        return [c for c in self._cards if not c.is_deleted]

    def find_by_content(self, content: str, notebook_id: str | None = None):
        norm = content.strip().lower()
        for c in self._cards:
            if c.content.strip().lower() == norm and not c.is_deleted:
                return c
        return None

    def delete(self, card_id: str):
        self.deleted = card_id


# ---------------------------------------------------------------------------
# GraphStore.deprecate_links_for()
# ---------------------------------------------------------------------------

class TestDeprecateLinksFor:
    def test_no_links_returns_zero(self, graph_store):
        count = graph_store.deprecate_links_for("card_x")
        assert count == 0

    def test_deprecates_from_side(self, graph_store):
        graph_store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        count = graph_store.deprecate_links_for("card_a")
        assert count == 1
        active = graph_store.get_links_for("card_a")
        assert active == []

    def test_deprecates_to_side(self, graph_store):
        graph_store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        count = graph_store.deprecate_links_for("card_b")
        assert count == 1
        assert graph_store.get_links_for("card_b") == []

    def test_deprecates_multiple_links(self, graph_store):
        graph_store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r1")
        graph_store.add_link("card_a", "card_c", LinkKind.CONTRASTS_WITH, 0.8, "r2")
        count = graph_store.deprecate_links_for("card_a")
        assert count == 2
        assert graph_store.get_links_for("card_a") == []

    def test_does_not_affect_unrelated_links(self, graph_store):
        graph_store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r1")
        graph_store.add_link("card_c", "card_d", LinkKind.SHARES_USAGE, 0.7, "r2")
        graph_store.deprecate_links_for("card_a")
        assert len(graph_store.get_links_for("card_c")) == 1
        assert len(graph_store.get_links_for("card_d")) == 1

    def test_already_deprecated_not_counted(self, graph_store):
        lk = graph_store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        lk.status = "deprecated"
        graph_store._links[lk.id] = lk
        count = graph_store.deprecate_links_for("card_a")
        assert count == 0

    def test_persists_after_reload(self, tmp_path):
        store = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
        )
        store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.deprecate_links_for("card_a")

        reloaded = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
        )
        assert reloaded.get_links_for("card_a") == []


# ---------------------------------------------------------------------------
# delete_vocab_word() + graph integration
# ---------------------------------------------------------------------------

class TestDeleteVocabWordWithGraph:
    def test_deprecates_links_on_delete(self, graph_store):
        cards = _FakeCardsStore([_FakeCard(id="c1", content="evoke")])
        graph_store.add_link("c1", "c2", LinkKind.CONTRASTS_WITH, 0.9, "r")

        result = delete_vocab_word("evoke", cards_store=cards, graph=graph_store)

        assert result == {"deleted": "evoke", "id": "c1"}
        assert graph_store.get_links_for("c1") == []

    def test_without_graph_still_works(self):
        cards = _FakeCardsStore([_FakeCard(id="c1", content="evoke")])
        result = delete_vocab_word("evoke", cards_store=cards)
        assert result == {"deleted": "evoke", "id": "c1"}
        assert cards.deleted == "c1"

    def test_graph_none_explicit_still_works(self, graph_store):
        cards = _FakeCardsStore([_FakeCard(id="c1", content="lucid")])
        graph_store.add_link("c1", "c2", LinkKind.SHARES_USAGE, 0.8, "r")

        result = delete_vocab_word("lucid", cards_store=cards, graph=None)
        assert result["deleted"] == "lucid"
        # link not deprecated because graph=None
        assert len(graph_store.get_links_for("c1")) == 1

    def test_not_found_raises_404(self, graph_store):
        cards = _FakeCardsStore([])
        with pytest.raises(HTTPException) as exc_info:
            delete_vocab_word("missing", cards_store=cards, graph=graph_store)
        assert exc_info.value.status_code == 404
