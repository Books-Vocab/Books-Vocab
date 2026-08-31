"""Tests for incremental and full sync behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kg.cards import CardStore
from kg.vocab_crud import list_vocab_cards
from test_sync_merge import _iso, _make_store, _now

# Incremental sync — soft-delete visibility
# ============================================================================


class TestIncrementalSync:
    def _build_response(self, card, graph, cards_by_id):
        """Minimal card response builder for testing."""
        from kg.api_models import CardResponse

        return CardResponse(
            id=card.id,
            content=card.content,
            meaning=card.meaning,
            pos=card.pos,
            difficulty=card.difficulty,
            difficultyTier="unknown",
            note=card.note,
            examples=card.examples,
            mode=card.mode,
            isDeleted=card.is_deleted,
            inflections=card.inflections or [],
            linksByKind={},
            reviewIntervalHours=card.review_interval_hours,
            nextReviewAt=None,
            lastReviewedAt=None,
            reviewCount=card.review_count,
            lapseCount=card.lapse_count,
            reviewStreak=card.review_streak,
            lastReviewFeedback=card.last_review_feedback,
        )

    def test_soft_deleted_card_appears_in_incremental_sync(self, tmp_path):
        """Soft-deleted cards must appear in incremental sync results with isDeleted=true."""
        store = _make_store(tmp_path)
        card = store.add("obsolete", "過時的")

        before_delete = _now() - timedelta(seconds=1)
        store.delete(card.id)

        from unittest.mock import MagicMock

        mock_graph = MagicMock()

        results, _cursor = list_vocab_cards(
            since=_iso(before_delete),
            cards_store=store,
            graph=mock_graph,
            card_response_builder=self._build_response,
        )

        deleted_cards = [r for r in results if r.content == "obsolete"]
        assert len(deleted_cards) == 1
        assert deleted_cards[0].isDeleted is True

    def test_incremental_sync_excludes_unmodified_cards(self, tmp_path):
        """Cards not modified after `since` should not appear."""
        store = _make_store(tmp_path)
        store.add("old_word", "舊詞")

        import time

        time.sleep(0.05)
        since = _now()
        time.sleep(0.05)

        store.add("new_word", "新詞")

        from unittest.mock import MagicMock

        mock_graph = MagicMock()

        results, _cursor = list_vocab_cards(
            since=_iso(since),
            cards_store=store,
            graph=mock_graph,
            card_response_builder=self._build_response,
        )

        words = {r.content for r in results}
        assert "new_word" in words
        assert "old_word" not in words

    def test_full_sync_returns_all_cards_including_tombstones(self, tmp_path):
        """Full sync (since=None) returns active cards and tombstones."""
        store = _make_store(tmp_path)
        store.add("apple", "蘋果")
        store.add("banana", "香蕉")
        deleted = store.add("cherry", "櫻桃")
        store.delete(deleted.id)

        from unittest.mock import MagicMock

        mock_graph = MagicMock()

        results, _cursor = list_vocab_cards(
            since=None,
            cards_store=store,
            graph=mock_graph,
            card_response_builder=self._build_response,
        )

        words = {r.content for r in results}
        assert words == {"apple", "banana", "cherry"}
        assert next(r for r in results if r.content == "cherry").isDeleted is True

    def test_invalid_since_raises_400(self, tmp_path):
        """Invalid since timestamp should raise HTTP 400."""
        store = _make_store(tmp_path)
        from unittest.mock import MagicMock

        from kg.exceptions import BadRequestError

        with pytest.raises(BadRequestError) as exc_info:
            list_vocab_cards(
                since="not-a-timestamp",
                cards_store=store,
                graph=MagicMock(),
                card_response_builder=self._build_response,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.parametrize("since", ["", "   "])
    def test_empty_since_raises_400(self, tmp_path, since):
        """Explicit empty since values must not silently restart full sync."""
        store = _make_store(tmp_path)
        from unittest.mock import MagicMock

        from kg.exceptions import BadRequestError

        with pytest.raises(BadRequestError) as exc_info:
            list_vocab_cards(
                since=since,
                cards_store=store,
                graph=MagicMock(),
                card_response_builder=self._build_response,
            )
        assert exc_info.value.status_code == 400

    def test_numeric_since_remains_incremental(self, tmp_path):
        """Numeric timestamp strings must continue using the incremental path."""
        store = _make_store(tmp_path)
        store.add("numeric_since", "數字游標")
        from unittest.mock import MagicMock

        store.get_modified_since = MagicMock(wraps=store.get_modified_since)
        store.page_cards = MagicMock(wraps=store.page_cards)

        results, _cursor = list_vocab_cards(
            since="0",
            cards_store=store,
            graph=MagicMock(),
            card_response_builder=self._build_response,
        )

        assert {r.content for r in results} == {"numeric_since"}
        store.get_modified_since.assert_called_once()
        store.page_cards.assert_not_called()


# ============================================================================
# Incremental sync — edge cases (since boundary / tombstone / pagination)
# ============================================================================


class TestIncrementalSyncEdges:
    """Edge cases for `since`-based incremental sync.

    Targets the contract that client incremental sync depends on:
    - `since=midpoint` returns only future-modified rows
    - tombstones (soft-deleted rows) created after `since` are returned with
      `is_deleted=True` so the client can propagate the delete
    - chunked retrieval (cursor-style by updated_at) is exhaustive and
      duplicate-free
    """

    @staticmethod
    def _set_updated_at(store: CardStore, card_id: str, ts: datetime) -> None:
        """Force `updated_at` (and `created_at`) on a card for test setup.

        `store.add()` / `store.update()` always stamp `datetime.now(UTC)`,
        so we bypass them via the engine to plant rows in the past or future.
        """
        from sqlmodel import Session

        from kg.cards import Card

        # Strip tzinfo — SQLModel persists naive datetimes for `updated_at`.
        naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
        with Session(store.engine) as session:
            card = session.get(Card, card_id)
            assert card is not None, f"card {card_id} not found"
            card.created_at = naive
            card.updated_at = naive
            session.add(card)
            session.commit()

    def test_incremental_sync_since_timestamp_returns_only_modified(self, tmp_path):
        """5 past + 3 future; since=midpoint returns exactly the 3 future."""
        store = _make_store(tmp_path)
        midpoint = datetime(2026, 1, 1, 12, 0, 0)
        past = midpoint - timedelta(days=1)
        future = midpoint + timedelta(hours=1)

        past_ids: list[str] = []
        for i in range(5):
            c = store.add(content=f"past_{i}", meaning=f"舊_{i}")
            self._set_updated_at(store, c.id, past + timedelta(seconds=i))
            past_ids.append(c.id)

        future_ids: list[str] = []
        for i in range(3):
            c = store.add(content=f"future_{i}", meaning=f"新_{i}")
            self._set_updated_at(store, c.id, future + timedelta(seconds=i))
            future_ids.append(c.id)

        results = store.get_modified_since(midpoint)
        returned_ids = {c.id for c in results}

        assert returned_ids == set(future_ids), (
            f"expected only future cards; got past={returned_ids & set(past_ids)}, "
            f"missing future={set(future_ids) - returned_ids}"
        )
        assert len(results) == 3

    def test_incremental_sync_orders_by_utc_instant_then_card_id(self, tmp_path):
        """Order results by actual UTC time, then id, not DB insertion order."""
        from sqlalchemy import text
        from sqlmodel import Session

        from kg.cards.store import Card

        store = _make_store(tmp_path)
        since = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        cards = [
            Card(id="card-late", content="late", meaning="晚"),
            Card(id="card-tie-z", content="tie-z", meaning="同時 z"),
            Card(id="card-earlier", content="earlier", meaning="早"),
            Card(id="card-tie-a", content="tie-a", meaning="同時 a"),
        ]
        with Session(store.engine) as session:
            session.add_all(cards)
            session.commit()

        # Insert order is deliberately [late, tie-z, earlier, tie-a]. The
        # tie cards use different offsets but represent the same UTC instant.
        timestamps = {
            "card-late": "2026-01-01 08:45:00-05:00",  # 13:45 UTC
            "card-tie-z": "2026-01-01 12:30:00+00:00",  # 12:30 UTC
            "card-earlier": "2026-01-01 12:15:00+00:00",  # 12:15 UTC
            "card-tie-a": "2026-01-01 07:30:00-05:00",  # 12:30 UTC
        }
        with store.engine.begin() as connection:
            for card_id, timestamp in timestamps.items():
                connection.execute(
                    text("UPDATE card SET updated_at = :timestamp, created_at = :timestamp WHERE id = :card_id"),
                    {"timestamp": timestamp, "card_id": card_id},
                )

        results = store.get_modified_since(since)

        assert [card.id for card in results] == [
            "card-earlier",
            "card-tie-a",
            "card-tie-z",
            "card-late",
        ]

    def test_incremental_sync_includes_tombstones_after_since(self, tmp_path):
        """Soft-delete after `since` must surface a tombstone with isDeleted=True."""
        store = _make_store(tmp_path)
        card = store.add(content="ephemeral", meaning="短暫的")

        # Plant the card in the past so it would be excluded by `since=midpoint`
        # if it weren't subsequently deleted.
        midpoint = datetime(2026, 1, 1, 12, 0, 0)
        past = midpoint - timedelta(days=1)
        self._set_updated_at(store, card.id, past)

        # Soft-delete after midpoint. `delete()` bumps updated_at to now(UTC),
        # so we then force it to a known future ts for deterministic comparison.
        store.delete(card.id)
        deletion_ts = midpoint + timedelta(minutes=5)
        self._set_updated_at(store, card.id, deletion_ts)
        # _set_updated_at goes through the engine without flipping is_deleted,
        # so the row is still soft-deleted; verify.
        assert store.get(card.id).is_deleted is True

        from unittest.mock import MagicMock

        mock_graph = MagicMock()
        mock_graph.get_links_for.return_value = []

        # Drive the full handler path so we exercise CardResponse(isDeleted=...)
        # — that's the field clients use to propagate the delete.
        results, _cursor = list_vocab_cards(
            since=_iso(midpoint),
            cards_store=store,
            graph=mock_graph,
            card_response_builder=TestIncrementalSync()._build_response,
        )

        tombstones = [r for r in results if r.id == card.id]
        assert len(tombstones) == 1, f"expected tombstone in incremental sync, got {len(tombstones)}"
        assert tombstones[0].isDeleted is True

    def test_incremental_sync_pagination_consistency(self, tmp_path):
        """Cursor-style chunked sync (limit=N by updated_at) is exhaustive + duplicate-free.

        The store doesn't expose page/offset on get_modified_since today, so we
        simulate the contract any paginated client would rely on: walk by
        ascending `updated_at`, slicing in chunks; the union must equal the
        full result, with no row appearing twice.
        """
        store = _make_store(tmp_path)
        base = datetime(2026, 1, 1, 12, 0, 0)
        since = base - timedelta(seconds=1)

        total = 47  # not a multiple of any plausible page size
        ids_by_ts: list[tuple[datetime, str]] = []
        for i in range(total):
            c = store.add(content=f"card_{i:03d}", meaning=f"含義_{i}")
            ts = base + timedelta(seconds=i)
            self._set_updated_at(store, c.id, ts)
            ids_by_ts.append((ts, c.id))

        # Full sweep — ground truth.
        full = store.get_modified_since(since)
        assert len(full) == total

        # Walk in chunks of 10 using (updated_at, id) as the cursor.
        # Page boundary uses `>` to match `get_modified_since`'s exclusive semantics.
        page_size = 10
        collected: list[str] = []
        cursor_ts = since
        all_rows = sorted(full, key=lambda c: (c.updated_at, c.id))

        while True:
            chunk = [c for c in all_rows if c.updated_at > cursor_ts][:page_size]
            if not chunk:
                break
            collected.extend(c.id for c in chunk)
            cursor_ts = chunk[-1].updated_at

        # No duplicates
        assert len(collected) == len(set(collected)), (
            f"pagination produced duplicates: {[x for x in collected if collected.count(x) > 1][:5]}"
        )
        # No gaps — every card appears exactly once
        assert set(collected) == {cid for _, cid in ids_by_ts}, (
            f"pagination missed cards: "
            f"missing={ {cid for _, cid in ids_by_ts} - set(collected) } "
            f"extra={set(collected) - {cid for _, cid in ids_by_ts}}"
        )
        assert len(collected) == total
