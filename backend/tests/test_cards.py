from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kg.cards import Card, CardStore


@pytest.fixture()
def store(tmp_path):
    return CardStore(path=tmp_path / "cards.db")


class TestAddAndGet:
    def test_add_returns_card_with_id(self, store):
        card = store.add(content="ephemeral", meaning="lasting for a very short time")
        assert card.id
        assert card.content == "ephemeral"
        assert card.meaning == "lasting for a very short time"

    def test_get_returns_correct_card(self, store):
        card = store.add(content="lucid", meaning="clearly expressed")
        fetched = store.get(card.id)
        assert fetched is not None
        assert fetched.id == card.id
        assert fetched.content == "lucid"
        assert fetched.meaning == "clearly expressed"

    def test_get_nonexistent_returns_none(self, store):
        assert store.get("nonexistent_id") is None


class TestSoftDelete:
    def test_deleted_card_still_retrievable_via_get(self, store):
        card = store.add(content="evoke", meaning="to bring to mind")
        store.delete(card.id)
        fetched = store.get(card.id)
        assert fetched is not None
        assert fetched.is_deleted is True

    def test_all_excludes_deleted_by_default(self, store):
        c1 = store.add(content="evoke", meaning="bring to mind")
        c2 = store.add(content="lucid", meaning="clear")
        store.delete(c1.id)
        active = list(store.all())
        ids = [c.id for c in active]
        assert c1.id not in ids
        assert c2.id in ids

    def test_all_include_deleted_true_returns_all(self, store):
        c1 = store.add(content="evoke", meaning="bring to mind")
        c2 = store.add(content="lucid", meaning="clear")
        store.delete(c1.id)
        all_cards = list(store.all(include_deleted=True))
        ids = [c.id for c in all_cards]
        assert c1.id in ids
        assert c2.id in ids


class TestUpdate:
    def test_normal_field_update(self, store):
        card = store.add(content="affect", meaning="to have an effect on")
        updated = store.update(card.id, meaning="to influence")
        assert updated is not None
        assert updated.meaning == "to influence"

    def test_update_deleted_card_returns_none(self, store):
        card = store.add(content="affect", meaning="to have an effect on")
        store.delete(card.id)
        result = store.update(card.id, meaning="new meaning")
        assert result is None

    def test_invalid_field_is_ignored(self, store):
        card = store.add(content="affect", meaning="to have an effect on")
        # non-existent field should be silently ignored
        result = store.update(card.id, nonexistent_field="value")
        assert result is not None
        assert result.content == "affect"


class TestGetModifiedSince:
    def test_returns_cards_modified_after_timestamp(self, store):
        c1 = store.add(content="affect", meaning="influence")
        ts = datetime.now(UTC)
        c2 = store.add(content="effect", meaning="result")
        results = store.get_modified_since(ts)
        ids = [c.id for c in results]
        assert c2.id in ids
        assert c1.id not in ids

    def test_boundary_exclusive(self, store):
        c1 = store.add(content="affect", meaning="influence")
        # get_modified_since uses > (strictly greater than), so exact ts excludes c1
        ts = store.get(c1.id).updated_at
        results = store.get_modified_since(ts)
        ids = [c.id for c in results]
        assert c1.id not in ids

    def test_includes_deleted_cards(self, store):
        c1 = store.add(content="affect", meaning="influence")
        ts = datetime.now(UTC)
        store.delete(c1.id)
        results = store.get_modified_since(ts)
        ids = [c.id for c in results]
        assert c1.id in ids


class TestCount:
    def test_count_only_active(self, store):
        c1 = store.add(content="affect", meaning="influence")
        store.add(content="effect", meaning="result")
        assert store.count() == 2
        store.delete(c1.id)
        assert store.count() == 1

    def test_count_empty_store(self, store):
        assert store.count() == 0


class TestBatchUpdate:
    def test_batch_update_modifies_multiple_cards(self, store):
        c1 = store.add(content="lucid", meaning="clear")
        c2 = store.add(content="ephemeral", meaning="short-lived")
        c3 = store.add(content="cogent", meaning="compelling")

        updates = [
            (c1.id, {"difficulty": 0.5}),
            (c2.id, {"difficulty": 0.8}),
            (c3.id, {"difficulty": 0.3}),
        ]
        count = store.batch_update(updates)
        assert count == 3

        assert store.get(c1.id).difficulty == 0.5
        assert store.get(c2.id).difficulty == 0.8
        assert store.get(c3.id).difficulty == 0.3

    def test_batch_update_skips_deleted_cards(self, store):
        c1 = store.add(content="lucid", meaning="clear")
        c2 = store.add(content="ephemeral", meaning="short-lived")
        store.delete(c2.id)

        updates = [
            (c1.id, {"difficulty": 0.5}),
            (c2.id, {"difficulty": 0.8}),
        ]
        count = store.batch_update(updates)
        assert count == 1
        assert store.get(c1.id).difficulty == 0.5

    def test_batch_update_skips_nonexistent_ids(self, store):
        c1 = store.add(content="lucid", meaning="clear")
        updates = [
            (c1.id, {"difficulty": 0.5}),
            ("nonexistent", {"difficulty": 0.9}),
        ]
        count = store.batch_update(updates)
        assert count == 1

    def test_batch_update_empty_list(self, store):
        count = store.batch_update([])
        assert count == 0

    def test_batch_update_no_change_not_counted(self, store):
        c1 = store.add(content="lucid", meaning="clear")
        store.update(c1.id, difficulty=0.5)
        # same value again — should not count as updated
        count = store.batch_update([(c1.id, {"difficulty": 0.5})])
        assert count == 0


class TestEmbedText:
    def test_embed_text_format(self, store):
        card = store.add(content="affect", meaning="to influence")
        assert card.embed_text() == "affect: to influence"

    def test_embed_text_pure_function(self):
        card = Card(content="lucid", meaning="clear")
        assert card.embed_text() == "lucid: clear"


def test_get_batch_returns_matching_cards(tmp_path):
    store = CardStore(tmp_path / "cards.db")
    c1 = store.add("hello", meaning="你好")
    c2 = store.add("world", meaning="世界")
    c3 = store.add("foo", meaning="富")

    result = store.get_batch({c1.id, c3.id})
    assert set(result.keys()) == {c1.id, c3.id}
    assert result[c1.id].content == "hello"

def test_get_batch_empty_set(tmp_path):
    store = CardStore(tmp_path / "cards.db")
    assert store.get_batch(set()) == {}

def test_get_batch_missing_ids(tmp_path):
    store = CardStore(tmp_path / "cards.db")
    c1 = store.add("hello", meaning="你好")
    result = store.get_batch({c1.id, "nonexistent"})
    assert set(result.keys()) == {c1.id}
