from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch, call

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


class TestBatchTouch:
    def test_bumps_updated_at_for_multiple_cards(self, store):
        c1 = store.add(content="alpha", meaning="first")
        c2 = store.add(content="beta", meaning="second")
        old_ts_1 = store.get(c1.id).updated_at
        old_ts_2 = store.get(c2.id).updated_at
        touched = store.batch_touch({c1.id, c2.id})
        assert touched == 2
        assert store.get(c1.id).updated_at > old_ts_1
        assert store.get(c2.id).updated_at > old_ts_2
        # Both should have the exact same timestamp (single transaction)
        assert store.get(c1.id).updated_at == store.get(c2.id).updated_at

    def test_skips_deleted_cards(self, store):
        c1 = store.add(content="alpha", meaning="first")
        c2 = store.add(content="beta", meaning="second")
        store.delete(c1.id)
        touched = store.batch_touch({c1.id, c2.id})
        assert touched == 1

    def test_skips_nonexistent_ids(self, store):
        c1 = store.add(content="alpha", meaning="first")
        touched = store.batch_touch({c1.id, "nonexistent"})
        assert touched == 1

    def test_empty_set_returns_zero(self, store):
        touched = store.batch_touch(set())
        assert touched == 0

    def test_shows_up_in_get_modified_since(self, store):
        """Core invariant: touched cards must appear in incremental sync."""
        c1 = store.add(content="alpha", meaning="first")
        ts = store.get(c1.id).updated_at  # naive, matches DB
        store.batch_touch({c1.id})
        results = store.get_modified_since(ts)
        assert any(c.id == c1.id for c in results)


class TestBatchUpdateNoN1:
    """Verify batch_update uses a single WHERE IN query, not N individual SELECTs."""

    def test_batch_update_uses_single_query_not_n_selects(self, store, tmp_path):
        """N+1 regression: batch_update must fetch all cards with one WHERE IN, not session.get() per card."""
        c1 = store.add(content="alpha", meaning="first")
        c2 = store.add(content="beta", meaning="second")
        c3 = store.add(content="gamma", meaning="third")

        select_call_count = 0
        original_exec = store.engine.connect().__class__.execute

        # Track how many DB SELECT round-trips happen via sqlalchemy event
        from sqlalchemy import event

        queries = []

        @event.listens_for(store.engine, "before_cursor_execute")
        def before_execute(conn, cursor, statement, params, context, executemany):
            if statement.strip().upper().startswith("SELECT"):
                queries.append(statement)

        updates = [
            (c1.id, {"difficulty": 0.1}),
            (c2.id, {"difficulty": 0.2}),
            (c3.id, {"difficulty": 0.3}),
        ]
        store.batch_update(updates)

        select_queries = [q for q in queries if "card" in q.lower()]
        # Must be exactly 1 SELECT (the WHERE IN batch fetch), not 3 individual SELECTs
        assert len(select_queries) == 1, (
            f"Expected 1 SELECT query (batch WHERE IN), got {len(select_queries)}. "
            f"Queries: {select_queries}"
        )

    def test_batch_update_intake_consistency(self, store):
        """Functional correctness unchanged after N+1 fix."""
        c1 = store.add(content="alpha", meaning="first")
        c2 = store.add(content="beta", meaning="second")
        count = store.batch_update([(c1.id, {"difficulty": 0.5}), (c2.id, {"difficulty": 0.7})])
        assert count == 2
        assert store.get(c1.id).difficulty == 0.5
        assert store.get(c2.id).difficulty == 0.7


class TestVocabIntakeNoN1:
    """Verify add_vocab_entries doesn't call find_by_content per duplicate (N+1)."""

    def test_duplicate_lookup_uses_dict_not_db(self):
        """vocab_intake N+1 regression: duplicate words must be resolved from in-memory dict."""
        from types import SimpleNamespace
        from kg.vocab_intake import add_vocab_entries
        from kg.api_models import VocabEntry

        db_lookup_calls = []

        class TrackingCardsStore:
            def __init__(self):
                self._cards = [
                    SimpleNamespace(id="c1", content="ephemeral", meaning="short-lived",
                                    is_deleted=False, is_archived=False,
                                    embed_text=lambda: "ephemeral: short-lived")
                ]

            def all(self, include_deleted=False, notebook_id=None):
                return list(self._cards)

            def find_by_content(self, content, notebook_id=None):
                db_lookup_calls.append(content)
                for c in self._cards:
                    if c.content.lower() == content.lower():
                        return c
                return None

            def add(self, content, meaning, **kwargs):
                c = SimpleNamespace(id=f"new_{content}", content=content, meaning=meaning,
                                    is_deleted=False, is_archived=False,
                                    embed_text=lambda: f"{content}: {meaning}")
                self._cards.append(c)
                return c

            def get(self, card_id):
                for c in self._cards:
                    if c.id == card_id:
                        return c
                return None

        class TrackingEmbeddings:
            def has(self, card_id): return False
            def add(self, card_id, vec): pass
            def add_batch(self, items): pass

        entries = [
            VocabEntry(word="ephemeral", translation="短暫的"),  # duplicate
            VocabEntry(word="lucid", translation="清晰的"),        # new
        ]

        result = add_vocab_entries(
            entries,
            user={},
            cards=TrackingCardsStore(),
            embeddings=TrackingEmbeddings(),
            graph=SimpleNamespace(find_candidates=lambda *a, **k: [], batch_add_candidates=lambda *a: None),
            logger=__import__("logging").getLogger("test"),
        )

        assert result.skipped == 1
        assert result.created == 1
        # After fix: find_by_content must NOT be called for duplicates (resolved from dict)
        assert db_lookup_calls == [], (
            f"Expected 0 DB calls for duplicate lookup, got {len(db_lookup_calls)}: {db_lookup_calls}"
        )


class TestBuildContentLookupNoFullScan:
    """Verify _build_content_lookup full-table-scan is not triggered multiple times per request."""

    def test_vocab_crud_batch_delete_single_scan(self):
        """batch_delete_vocab_words must call cards_store.all() exactly once."""
        from types import SimpleNamespace
        from kg.vocab_crud import batch_delete_vocab_words

        all_call_count = 0

        class CountingCardsStore:
            def __init__(self):
                self._cards = [
                    SimpleNamespace(id="c1", content="evoke", is_deleted=False, is_archived=False),
                    SimpleNamespace(id="c2", content="lucid", is_deleted=False, is_archived=False),
                ]

            def all(self, include_deleted=False, notebook_id=None):
                nonlocal all_call_count
                all_call_count += 1
                return [c for c in self._cards if not c.is_deleted]

            def delete(self, card_id):
                for c in self._cards:
                    if c.id == card_id:
                        c.is_deleted = True

        result = batch_delete_vocab_words(
            ["evoke", "lucid"],
            cards_store=CountingCardsStore(),
        )
        assert result["deleted"] == 2
        assert all_call_count == 1, f"Expected 1 full-scan, got {all_call_count}"

    def test_vocab_crud_batch_archive_single_scan(self):
        """batch_archive_vocab_words must call cards_store.all() exactly once."""
        from types import SimpleNamespace
        from kg.vocab_crud import batch_archive_vocab_words

        all_call_count = 0

        class CountingCardsStore:
            def __init__(self):
                self._cards = [
                    SimpleNamespace(id="c1", content="evoke", is_deleted=False, is_archived=False),
                    SimpleNamespace(id="c2", content="lucid", is_deleted=False, is_archived=False),
                ]

            def all(self, include_deleted=False, notebook_id=None):
                nonlocal all_call_count
                all_call_count += 1
                return [c for c in self._cards if not c.is_deleted]

            def update(self, card_id, **kwargs):
                for c in self._cards:
                    if c.id == card_id:
                        for k, v in kwargs.items():
                            setattr(c, k, v)

        result = batch_archive_vocab_words(
            ["evoke", "lucid"],
            archived=True,
            cards_store=CountingCardsStore(),
        )
        assert result["updated"] == 2
        assert all_call_count == 1, f"Expected 1 full-scan, got {all_call_count}"


class TestSoftDeleteByNotebook:
    def test_soft_deletes_all_cards_in_notebook(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        store.add(content="apple", meaning="蘋果", notebook_id="nb1")
        store.add(content="banana", meaning="香蕉", notebook_id="nb1")
        store.add(content="cherry", meaning="櫻桃", notebook_id="nb2")
        count = store.soft_delete_by_notebook("nb1")
        assert count == 2
        assert list(store.all(notebook_id="nb1")) == []
        assert len(list(store.all(notebook_id="nb2"))) == 1

    def test_skips_already_deleted(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        c = store.add(content="apple", meaning="蘋果", notebook_id="nb1")
        store.delete(c.id)
        count = store.soft_delete_by_notebook("nb1")
        assert count == 0

    def test_empty_notebook_returns_zero(self, tmp_path):
        store = CardStore(tmp_path / "cards.db")
        count = store.soft_delete_by_notebook("nonexistent")
        assert count == 0


