"""Tests for daily review stats storage and sync logic."""

from __future__ import annotations

import logging
from pathlib import Path

from kg.api_models import DailyReviewStatEntry
from kg.daily_stats import DailyReviewStatsStore
from kg.vocab_review import pull_daily_review_stats, push_daily_review_stats


def _make_store(tmp_path: Path) -> DailyReviewStatsStore:
    return DailyReviewStatsStore(tmp_path / "daily_stats.db")


class TestDailyReviewStatsStore:

    def test_upsert_new(self, tmp_path):
        store = _make_store(tmp_path)
        stat = store.upsert("2026-03-10", total=5, remembered=4, forgot=1)
        assert stat.day_key == "2026-03-10"
        assert stat.total == 5
        assert stat.remembered == 4
        assert stat.forgot == 1

    def test_upsert_takes_max(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert("2026-03-10", total=5, remembered=4, forgot=1)
        stat = store.upsert("2026-03-10", total=8, remembered=3, forgot=5)
        # max(5,8)=8, max(4,3)=4, max(1,5)=5
        assert stat.total == 8
        assert stat.remembered == 4
        assert stat.forgot == 5

    def test_all_ordered(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert("2026-03-12", total=1, remembered=1, forgot=0)
        store.upsert("2026-03-10", total=3, remembered=2, forgot=1)
        store.upsert("2026-03-11", total=2, remembered=1, forgot=1)
        result = store.all()
        assert [s.day_key for s in result] == ["2026-03-10", "2026-03-11", "2026-03-12"]

    def test_get_since(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert("2026-03-10", total=3, remembered=2, forgot=1)
        store.upsert("2026-03-11", total=2, remembered=1, forgot=1)
        store.upsert("2026-03-12", total=1, remembered=1, forgot=0)
        result = store.get_since("2026-03-11")
        assert len(result) == 2
        assert result[0].day_key == "2026-03-11"
        assert result[1].day_key == "2026-03-12"


class TestPushDailyReviewStats:

    def test_push_upserts_entries(self, tmp_path):
        store = _make_store(tmp_path)
        entries = [
            DailyReviewStatEntry(day_key="2026-03-10", total=5, remembered=4, forgot=1),
            DailyReviewStatEntry(day_key="2026-03-11", total=3, remembered=2, forgot=1),
        ]
        result = push_daily_review_stats(entries, stats_store=store, logger=logging.getLogger())
        assert result == {"upserted": 2}
        assert len(store.all()) == 2

    def test_push_idempotent(self, tmp_path):
        store = _make_store(tmp_path)
        entry = DailyReviewStatEntry(day_key="2026-03-10", total=5, remembered=4, forgot=1)
        push_daily_review_stats([entry], stats_store=store, logger=logging.getLogger())
        push_daily_review_stats([entry], stats_store=store, logger=logging.getLogger())
        result = store.all()
        assert len(result) == 1
        assert result[0].total == 5


class TestPullDailyReviewStats:

    def test_pull_all(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert("2026-03-10", total=5, remembered=4, forgot=1)
        store.upsert("2026-03-11", total=3, remembered=2, forgot=1)
        result = pull_daily_review_stats(since=None, stats_store=store)
        assert len(result) == 2

    def test_pull_with_since(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert("2026-03-10", total=5, remembered=4, forgot=1)
        store.upsert("2026-03-11", total=3, remembered=2, forgot=1)
        result = pull_daily_review_stats(since="2026-03-11", stats_store=store)
        assert len(result) == 1
        assert result[0].day_key == "2026-03-11"

    def test_pull_empty(self, tmp_path):
        store = _make_store(tmp_path)
        result = pull_daily_review_stats(since=None, stats_store=store)
        assert result == []
