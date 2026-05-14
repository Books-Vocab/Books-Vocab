"""Tests for kg.vocab_review — push/pull review states using lightweight fakes.

Complements test_sync_merge.py (CardStore integration) and test_daily_stats.py
(stats happy path). Focuses on branches that are otherwise easy to regress:
  * card_id-precise match wins over word fallback.
  * deleted card with matching card_id is treated as "not found".
  * get_batch is only called when at least one entry carries a card_id.
  * word-fallback updates *every* card sharing that word.
  * pending_updates is flushed via a single batch_update call.
  * client client_last unparseable -> skipped; no batch_update.
  * pull_daily_review_stats since="" branch + empty store.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from kg.api_models import DailyReviewStatEntry, ReviewStateEntry
from kg.vocab_review import (
    pull_daily_review_stats,
    push_daily_review_stats,
    push_review_states,
)


# --------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------- #
@dataclass
class _ReviewCard:
    id: str
    content: str
    last_reviewed_at: datetime | None = None
    review_count: int = 0
    lapse_count: int = 0
    review_interval_hours: float = 0.0
    review_streak: int = 0
    last_review_feedback: int = 0
    next_review_at: datetime | None = None
    is_deleted: bool = False


class _FakeCardsStore:
    def __init__(self, cards: list[_ReviewCard]) -> None:
        self._cards = list(cards)
        self.batch_update_calls: list[list[tuple[str, dict[str, Any]]]] = []
        self.get_batch_calls: list[set[str]] = []
        self.all_calls: list[str | None] = []

    def all(self, notebook_id: str | None = None) -> list[_ReviewCard]:
        self.all_calls.append(notebook_id)
        return [c for c in self._cards if not c.is_deleted]

    def get_batch(self, ids: set[str]) -> dict[str, _ReviewCard]:
        self.get_batch_calls.append(set(ids))
        return {c.id: c for c in self._cards if c.id in ids}

    def batch_update(self, updates: list[tuple[str, dict[str, Any]]]) -> None:
        self.batch_update_calls.append(list(updates))
        by_id = {c.id: c for c in self._cards}
        for cid, patch in updates:
            c = by_id.get(cid)
            if c is None:
                continue
            for k, v in patch.items():
                setattr(c, k, v)


class _FakeStatsStore:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []
        self._all: list[Any] = []
        self._since: list[Any] = []

    def upsert(self, *, day_key: str, total: int, remembered: int, forgot: int) -> None:
        self.upserts.append({"day_key": day_key, "total": total, "remembered": remembered, "forgot": forgot})

    def all(self) -> list[Any]:
        return list(self._all)

    def get_since(self, since: str) -> list[Any]:
        return [s for s in self._all if s.day_key >= since]


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _entry(
    *,
    word: str,
    last_reviewed_at: str,
    card_id: str | None = None,
    review_count: int = 1,
    lapse_count: int = 0,
    review_streak: int = 1,
    review_interval_hours: float = 24.0,
    next_review_at: str | None = None,
    last_review_feedback: int = 1,
) -> ReviewStateEntry:
    return ReviewStateEntry(
        word=word,
        card_id=card_id,
        review_interval_hours=review_interval_hours,
        next_review_at=next_review_at or _iso(datetime.now(UTC) + timedelta(hours=24)),
        last_reviewed_at=last_reviewed_at,
        review_count=review_count,
        lapse_count=lapse_count,
        review_streak=review_streak,
        last_review_feedback=last_review_feedback,
    )


# --------------------------------------------------------------------- #
# push_review_states
# --------------------------------------------------------------------- #
class TestPushReviewStatesFakes:
    def test_card_id_match_wins_over_word_fallback(self):
        # Two cards share the word "run" — entry's card_id must select c2.
        c1 = _ReviewCard(id="c1", content="run")
        c2 = _ReviewCard(id="c2", content="run")
        store = _FakeCardsStore([c1, c2])
        client_time = datetime.now(UTC)
        entry = _entry(word="run", last_reviewed_at=_iso(client_time), card_id="c2", review_count=7)

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())

        assert result == {"updated": 1, "skipped": 0}
        # Only c2 must be touched.
        assert len(store.batch_update_calls) == 1
        flushed = store.batch_update_calls[0]
        assert [cid for cid, _ in flushed] == ["c2"]
        # get_batch was queried; word index was never built.
        assert store.get_batch_calls == [{"c2"}]
        assert store.all_calls == []

    def test_deleted_card_with_matching_card_id_is_skipped(self):
        c1 = _ReviewCard(id="c1", content="cat", is_deleted=True)
        store = _FakeCardsStore([c1])
        entry = _entry(
            word="cat",
            card_id="c1",
            last_reviewed_at=_iso(datetime.now(UTC)),
        )

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        # get_batch returns c1, but the filter `not card.is_deleted` rejects it.
        assert result == {"updated": 0, "skipped": 1}
        assert store.batch_update_calls == []

    def test_no_card_id_entries_skip_get_batch(self):
        c1 = _ReviewCard(id="c1", content="cat")
        store = _FakeCardsStore([c1])
        entry = _entry(word="cat", last_reviewed_at=_iso(datetime.now(UTC)))

        push_review_states([entry], cards_store=store, logger=logging.getLogger())
        # When no entry has a card_id, the pre-fetch is skipped entirely.
        assert store.get_batch_calls == []
        # word lookup did happen.
        assert store.all_calls == [None]

    def test_word_fallback_updates_all_matching_cards(self):
        c1 = _ReviewCard(id="c1", content="run")
        c2 = _ReviewCard(id="c2", content="Run")  # case-insensitive same word
        store = _FakeCardsStore([c1, c2])
        entry = _entry(word="run", last_reviewed_at=_iso(datetime.now(UTC)))

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())

        assert result == {"updated": 2, "skipped": 0}
        flushed_ids = [cid for cid, _ in store.batch_update_calls[0]]
        assert sorted(flushed_ids) == ["c1", "c2"]

    def test_unparseable_last_reviewed_at_is_skipped(self):
        c1 = _ReviewCard(id="c1", content="cat")
        store = _FakeCardsStore([c1])
        # last_reviewed_at is a string the field allows but parse_datetime can't read.
        entry = _entry(word="cat", last_reviewed_at="not-a-timestamp")

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())

        assert result == {"updated": 0, "skipped": 1}
        assert store.batch_update_calls == []

    def test_server_newer_takes_max_counts(self):
        server_time = datetime.now(UTC)
        client_time = server_time - timedelta(hours=1)
        c1 = _ReviewCard(
            id="c1", content="cat", last_reviewed_at=server_time,
            review_count=3, lapse_count=1,
        )
        store = _FakeCardsStore([c1])
        entry = _entry(
            word="cat",
            last_reviewed_at=_iso(client_time),
            review_count=5, lapse_count=0,  # only review_count is higher than server
        )

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())

        assert result == {"updated": 1, "skipped": 0}
        flushed = store.batch_update_calls[0][0][1]
        # Server stayed in charge of dates — only counts moved.
        assert "next_review_at" not in flushed
        assert flushed == {"review_count": 5, "lapse_count": 1}

    def test_server_newer_no_count_change_skipped(self):
        server_time = datetime.now(UTC)
        client_time = server_time - timedelta(hours=1)
        c1 = _ReviewCard(
            id="c1", content="cat", last_reviewed_at=server_time,
            review_count=10, lapse_count=2,
        )
        store = _FakeCardsStore([c1])
        entry = _entry(
            word="cat",
            last_reviewed_at=_iso(client_time),
            review_count=5, lapse_count=1,
        )

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 0, "skipped": 1}
        assert store.batch_update_calls == []  # nothing flushed

    def test_single_batch_update_call_for_many_entries(self):
        """N entries must collapse into ONE batch_update call (write-path perf)."""
        cards = [_ReviewCard(id=f"c{i}", content=f"w{i}") for i in range(5)]
        store = _FakeCardsStore(cards)
        client = datetime.now(UTC)
        entries = [_entry(word=f"w{i}", last_reviewed_at=_iso(client)) for i in range(5)]

        push_review_states(entries, cards_store=store, logger=logging.getLogger())

        assert len(store.batch_update_calls) == 1
        assert len(store.batch_update_calls[0]) == 5

    def test_notebook_scope_threaded_into_all(self):
        store = _FakeCardsStore([_ReviewCard(id="c1", content="cat")])
        entry = _entry(word="cat", last_reviewed_at=_iso(datetime.now(UTC)))

        push_review_states(
            [entry], cards_store=store, logger=logging.getLogger(), notebook_id="nb_x"
        )
        assert store.all_calls == ["nb_x"]

    def test_empty_entries_returns_zero(self):
        store = _FakeCardsStore([])
        result = push_review_states([], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 0, "skipped": 0}
        assert store.get_batch_calls == []
        assert store.batch_update_calls == []


# --------------------------------------------------------------------- #
# push_daily_review_stats / pull_daily_review_stats branch coverage
# --------------------------------------------------------------------- #
class TestDailyReviewStatsBranches:
    def test_pull_with_empty_since_uses_all(self):
        """Falsy `since` (None or "") must take the .all() branch, not .get_since('')."""
        store = _FakeStatsStore()
        store._all = [
            SimpleNamespace(day_key="2026-05-12", total=3, remembered=2, forgot=1),
        ]
        result = pull_daily_review_stats(since=None, stats_store=store)
        assert len(result) == 1
        result2 = pull_daily_review_stats(since="", stats_store=store)  # falsy str
        assert len(result2) == 1
        assert isinstance(result[0], DailyReviewStatEntry)

    def test_pull_with_since_filters(self):
        store = _FakeStatsStore()
        store._all = [
            SimpleNamespace(day_key="2026-05-10", total=1, remembered=1, forgot=0),
            SimpleNamespace(day_key="2026-05-12", total=3, remembered=2, forgot=1),
        ]
        result = pull_daily_review_stats(since="2026-05-11", stats_store=store)
        assert [r.day_key for r in result] == ["2026-05-12"]

    def test_pull_returns_pydantic_models(self):
        store = _FakeStatsStore()
        store._all = [SimpleNamespace(day_key="2026-05-12", total=3, remembered=2, forgot=1)]
        result = pull_daily_review_stats(since=None, stats_store=store)
        assert all(isinstance(r, DailyReviewStatEntry) for r in result)
        assert result[0].total == 3 and result[0].remembered == 2 and result[0].forgot == 1

    def test_push_returns_upserted_count(self):
        store = _FakeStatsStore()
        entries = [
            DailyReviewStatEntry(day_key="2026-05-12", total=3, remembered=2, forgot=1),
            DailyReviewStatEntry(day_key="2026-05-13", total=1, remembered=1, forgot=0),
        ]
        out = push_daily_review_stats(entries, stats_store=store, logger=logging.getLogger())
        assert out == {"upserted": 2}
        assert [u["day_key"] for u in store.upserts] == ["2026-05-12", "2026-05-13"]

    def test_push_empty_is_zero(self):
        store = _FakeStatsStore()
        out = push_daily_review_stats([], stats_store=store, logger=logging.getLogger())
        assert out == {"upserted": 0}
        assert store.upserts == []
