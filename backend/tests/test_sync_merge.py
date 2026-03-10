"""
Tests for sync merge logic — push_review_states, incremental sync, and soft-delete.

Covers the core conflict resolution code in vocab_service.push_review_states()
and the incremental sync boundary in list_vocab_cards().
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kg.cards import CardStore
from kg.vocab_service import push_review_states, list_vocab_cards
from kg.api_models import ReviewStateEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path) -> CardStore:
    return CardStore(tmp_path / "cards.db")


def _iso(dt: datetime) -> str:
    s = dt.isoformat()
    if not s.endswith("Z") and "+" not in s:
        s += "Z"
    return s


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entry(
    word: str,
    last_reviewed_at: str,
    *,
    review_interval_hours: float = 24.0,
    next_review_at: str | None = None,
    review_count: int = 1,
    lapse_count: int = 0,
    review_streak: int = 1,
    last_review_feedback: int = 1,
) -> ReviewStateEntry:
    return ReviewStateEntry(
        word=word,
        review_interval_hours=review_interval_hours,
        next_review_at=next_review_at or _iso(_now() + timedelta(hours=review_interval_hours)),
        last_reviewed_at=last_reviewed_at,
        review_count=review_count,
        lapse_count=lapse_count,
        review_streak=review_streak,
        last_review_feedback=last_review_feedback,
    )


# ============================================================================
# push_review_states — conflict resolution
# ============================================================================


class TestPushReviewStates:

    def test_client_newer_accepts_all_fields(self, tmp_path):
        """When client last_reviewed_at > server, all fields should be accepted."""
        store = _make_store(tmp_path)
        card = store.add("evoke", "喚起")

        server_time = _now() - timedelta(hours=2)
        store.update(card.id, last_reviewed_at=server_time, review_count=3, lapse_count=1)

        client_time = _now()
        entry = _entry(
            "evoke",
            _iso(client_time),
            review_count=5,
            lapse_count=2,
            review_streak=4,
            review_interval_hours=48.0,
            last_review_feedback=1,
        )

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 1, "skipped": 0}

        updated = store.get(card.id)
        assert updated.review_interval_hours == 48.0
        assert updated.review_count == 5  # max(5, 3)
        assert updated.lapse_count == 2  # max(2, 1)
        assert updated.review_streak == 4
        assert updated.last_review_feedback == 1

    def test_server_newer_only_takes_max_counts(self, tmp_path):
        """When server last_reviewed_at >= client, only max counts should be updated."""
        store = _make_store(tmp_path)
        card = store.add("lucid", "清晰的")

        server_time = _now()
        store.update(
            card.id,
            last_reviewed_at=server_time,
            review_count=5,
            lapse_count=3,
            review_streak=10,
            review_interval_hours=72.0,
        )

        client_time = server_time - timedelta(hours=1)
        entry = _entry(
            "lucid",
            _iso(client_time),
            review_count=8,  # higher than server
            lapse_count=1,   # lower than server
            review_streak=2,
            review_interval_hours=24.0,
        )

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 1, "skipped": 0}

        updated = store.get(card.id)
        # Only review_count should change (8 > 5); lapse_count stays (1 < 3)
        assert updated.review_count == 8
        assert updated.lapse_count == 3
        # These must NOT change when server is newer
        assert updated.review_streak == 10
        assert updated.review_interval_hours == 72.0

    def test_server_newer_equal_counts_skips(self, tmp_path):
        """When server is newer and counts are equal or lower, entry is skipped."""
        store = _make_store(tmp_path)
        card = store.add("vivid", "生動的")

        server_time = _now()
        store.update(card.id, last_reviewed_at=server_time, review_count=5, lapse_count=3)

        client_time = server_time - timedelta(hours=1)
        entry = _entry("vivid", _iso(client_time), review_count=4, lapse_count=2)

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 0, "skipped": 1}

    def test_card_not_found_skips(self, tmp_path):
        """Entries for non-existent words should be skipped."""
        store = _make_store(tmp_path)
        store.add("exist", "存在")

        entry = _entry("nonexist", _iso(_now()))
        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 0, "skipped": 1}

    def test_invalid_last_reviewed_at_skips(self, tmp_path):
        """Entries with unparseable last_reviewed_at should be skipped."""
        store = _make_store(tmp_path)
        store.add("apple", "蘋果")

        entry = ReviewStateEntry(
            word="apple",
            review_interval_hours=24.0,
            next_review_at=_iso(_now() + timedelta(hours=24)),
            last_reviewed_at="not-a-date",
            review_count=1,
            lapse_count=0,
            review_streak=1,
            last_review_feedback=1,
        )
        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 0, "skipped": 1}

    def test_case_insensitive_word_match(self, tmp_path):
        """Word matching should be case-insensitive."""
        store = _make_store(tmp_path)
        card = store.add("Evoke", "喚起")

        entry = _entry("evoke", _iso(_now()), review_count=3)
        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 1, "skipped": 0}

    def test_same_timestamp_server_wins(self, tmp_path):
        """When timestamps are identical (>=), server wins — only max counts taken."""
        store = _make_store(tmp_path)
        card = store.add("precise", "精確的")

        same_time = _now()
        store.update(
            card.id,
            last_reviewed_at=same_time,
            review_count=3,
            review_streak=5,
            review_interval_hours=48.0,
        )

        entry = _entry(
            "precise",
            _iso(same_time),
            review_count=3,   # equal
            review_streak=2,
            review_interval_hours=24.0,
        )

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 0, "skipped": 1}

        updated = store.get(card.id)
        assert updated.review_streak == 5  # unchanged
        assert updated.review_interval_hours == 48.0  # unchanged

    def test_multiple_entries_mixed_outcomes(self, tmp_path):
        """Batch with mixed outcomes: some updated, some skipped."""
        store = _make_store(tmp_path)
        store.add("apple", "蘋果")
        banana = store.add("banana", "香蕉")

        # Set banana's server time to be newer than what client will send
        server_time = _now()
        store.update(banana.id, last_reviewed_at=server_time, review_count=5)

        old_time = server_time - timedelta(hours=5)
        new_time = _now() + timedelta(seconds=1)

        entries = [
            _entry("apple", _iso(new_time), review_count=10),     # client newer (server has None) → update
            _entry("banana", _iso(old_time), review_count=1),      # server newer, counts lower → skip
            _entry("cherry", _iso(new_time)),                       # not found → skip
        ]

        result = push_review_states(entries, cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 1, "skipped": 2}

    def test_client_newer_uses_max_for_counts(self, tmp_path):
        """Even when client is newer, counts use max() not blind overwrite."""
        store = _make_store(tmp_path)
        card = store.add("nuance", "細微差別")

        server_time = _now() - timedelta(hours=1)
        store.update(card.id, last_reviewed_at=server_time, review_count=10, lapse_count=5)

        client_time = _now()
        entry = _entry(
            "nuance",
            _iso(client_time),
            review_count=3,   # lower than server
            lapse_count=8,    # higher than server
        )

        push_review_states([entry], cards_store=store, logger=logging.getLogger())
        updated = store.get(card.id)
        assert updated.review_count == 10  # max(3, 10)
        assert updated.lapse_count == 8    # max(8, 5)


# ============================================================================
# Incremental sync — soft-delete visibility
# ============================================================================


class TestIncrementalSync:

    def _build_response(self, card, graph, cards_by_id):
        """Minimal card response builder for testing."""
        from kg.vocab_service import CardResponse
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

        results = list_vocab_cards(
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

        results = list_vocab_cards(
            since=_iso(since),
            cards_store=store,
            graph=mock_graph,
            card_response_builder=self._build_response,
        )

        words = {r.content for r in results}
        assert "new_word" in words
        assert "old_word" not in words

    def test_full_sync_returns_all_active_cards(self, tmp_path):
        """Full sync (since=None) returns all non-deleted cards."""
        store = _make_store(tmp_path)
        store.add("apple", "蘋果")
        store.add("banana", "香蕉")
        deleted = store.add("cherry", "櫻桃")
        store.delete(deleted.id)

        from unittest.mock import MagicMock
        mock_graph = MagicMock()

        results = list_vocab_cards(
            since=None,
            cards_store=store,
            graph=mock_graph,
            card_response_builder=self._build_response,
        )

        words = {r.content for r in results}
        assert words == {"apple", "banana"}

    def test_invalid_since_raises_400(self, tmp_path):
        """Invalid since timestamp should raise HTTP 400."""
        store = _make_store(tmp_path)
        from unittest.mock import MagicMock
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            list_vocab_cards(
                since="not-a-timestamp",
                cards_store=store,
                graph=MagicMock(),
                card_response_builder=self._build_response,
            )
        assert exc_info.value.status_code == 400


# ============================================================================
# CardStore.update — updated_at auto-bump
# ============================================================================


class TestCardStoreUpdate:

    def test_update_bumps_updated_at(self, tmp_path):
        """Any field change via update() must bump updated_at."""
        store = _make_store(tmp_path)
        card = store.add("test", "測試")
        original_updated = card.updated_at

        import time
        time.sleep(0.05)

        store.update(card.id, review_count=5)
        refreshed = store.get(card.id)
        assert refreshed.updated_at > original_updated

    def test_update_no_change_keeps_updated_at(self, tmp_path):
        """If no fields actually changed, updated_at should not bump."""
        store = _make_store(tmp_path)
        card = store.add("test", "測試")
        original_updated = card.updated_at

        store.update(card.id, review_count=card.review_count)
        refreshed = store.get(card.id)
        assert refreshed.updated_at == original_updated

    def test_update_deleted_card_returns_none(self, tmp_path):
        """Updating a soft-deleted card should return None."""
        store = _make_store(tmp_path)
        card = store.add("gone", "消失")
        store.delete(card.id)

        result = store.update(card.id, review_count=99)
        assert result is None
