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


import pytest
from unittest.mock import MagicMock
from kg.judge import ManualLinkJudge
from kg.vocab_service import create_manual_link, reject_graph_link


class FakeCard:
    def __init__(self, id, content="word", meaning="meaning", is_deleted=False, is_archived=False):
        self.id = id
        self.content = content
        self.meaning = meaning
        self.is_deleted = is_deleted
        self.is_archived = is_archived


class FakeCardsStore:
    def __init__(self, cards):
        self._cards = {c.id: c for c in cards}
        self.touched = []

    def get(self, card_id):
        return self._cards.get(card_id)

    def touch(self, card_id):
        self.touched.append(card_id)


def _make_judge(response_json: str):
    client = MagicMock()
    choice = MagicMock()
    choice.message.content = response_json
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None
    client.chat.completions.create.return_value = resp
    return ManualLinkJudge(client)


class TestCreateManualLink:
    def test_creates_link_successfully(self, store):
        cards = FakeCardsStore([
            FakeCard("a", content="apple", meaning="蘋果"),
            FakeCard("b", content="banana", meaning="香蕉"),
        ])
        judge = _make_judge('{"link": "shares_usage", "confidence": 0.9, "reason": "都是水果"}')
        result = create_manual_link(from_id="a", to_id="b", cards_store=cards, graph=store, judge=judge)
        assert result.kind == LinkKind.SHARES_USAGE
        assert result.confidence == 1.0
        assert result.reason == "都是水果"

    def test_touches_both_cards(self, store):
        cards = FakeCardsStore([FakeCard("a"), FakeCard("b")])
        judge = _make_judge('{"link": "shares_usage", "confidence": 0.9, "reason": "r"}')
        create_manual_link(from_id="a", to_id="b", cards_store=cards, graph=store, judge=judge)
        assert "a" in cards.touched and "b" in cards.touched

    def test_rejects_missing_card(self, store):
        cards = FakeCardsStore([FakeCard("a")])
        judge = _make_judge('{"link": "shares_usage", "confidence": 0.9, "reason": "r"}')
        from kg.exceptions import NotFoundError
        with pytest.raises(NotFoundError) as exc:
            create_manual_link(from_id="a", to_id="missing", cards_store=cards, graph=store, judge=judge)
        assert exc.value.status_code == 404

    def test_rejects_duplicate_active_link(self, store):
        cards = FakeCardsStore([FakeCard("a"), FakeCard("b")])
        store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "existing")
        judge = _make_judge('{"link": "shares_usage", "confidence": 0.9, "reason": "r"}')
        from kg.exceptions import ConflictError
        with pytest.raises(ConflictError) as exc:
            create_manual_link(from_id="a", to_id="b", cards_store=cards, graph=store, judge=judge)
        assert exc.value.status_code == 409

    def test_revives_rejected_link(self, store):
        cards = FakeCardsStore([
            FakeCard("a", content="apple", meaning="蘋果"),
            FakeCard("b", content="banana", meaning="香蕉"),
        ])
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "old reason")
        store.reject_link(lk.id)
        judge = _make_judge('{"link": "shares_usage", "confidence": 0.9, "reason": "新原因"}')
        result = create_manual_link(from_id="a", to_id="b", cards_store=cards, graph=store, judge=judge)
        assert result.status == "active"
        assert result.kind == LinkKind.SHARES_USAGE
        assert result.reason == "新原因"
        assert result.id == lk.id  # same link, not new


class TestRejectGraphLink:
    def test_rejects_link(self, store):
        cards = FakeCardsStore([FakeCard("a"), FakeCard("b")])
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        reject_graph_link(link_id=lk.id, graph=store, cards_store=cards)
        assert store.find_link_between("a", "b").status == "rejected"

    def test_touches_both_cards(self, store):
        cards = FakeCardsStore([FakeCard("a"), FakeCard("b")])
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        reject_graph_link(link_id=lk.id, graph=store, cards_store=cards)
        assert "a" in cards.touched and "b" in cards.touched

    def test_rejects_nonexistent_link(self, store):
        cards = FakeCardsStore([])
        from kg.exceptions import NotFoundError
        with pytest.raises(NotFoundError) as exc:
            reject_graph_link(link_id="nonexistent", graph=store, cards_store=cards)
        assert exc.value.status_code == 404
