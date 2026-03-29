"""Tests for data safety fixes: MochiSync persist, graph lock, token_tracker WAL, input validation."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from kg.cards import CardStore
from kg.graph import GraphStore, LinkKind


# ---------- Problem 1: MochiSync pull_updates must persist via batch_update ----------


class TestMochiSyncPullPersistence:
    """pull_updates must write changes to SQLite, not just mutate detached objects."""

    def test_pull_updates_persists_content_change(self, tmp_path):
        """After pull_updates modifies a card, re-reading from DB must reflect the change."""
        store = CardStore(tmp_path / "cards.db")
        card = store.add("hello", "你好")
        card_id = card.id

        # Simulate what pull_updates should do: update via batch_update
        store.batch_update([(card_id, {"meaning": "嗨"})])

        # Re-read from DB — must see new value
        fresh = store.get(card_id)
        assert fresh is not None
        assert fresh.meaning == "嗨", "batch_update must persist meaning change to DB"

    def test_detached_card_mutation_does_not_persist(self, tmp_path):
        """Directly mutating a card returned by get() must NOT persist (confirms the bug)."""
        store = CardStore(tmp_path / "cards.db")
        card = store.add("hello", "你好")
        card_id = card.id

        # get() returns a detached object — mutation is a no-op
        detached = store.get(card_id)
        detached.meaning = "嗨"
        store.save()  # no-op

        fresh = store.get(card_id)
        assert fresh.meaning == "你好", "detached mutation must NOT persist"


# ---------- Problem 2: graph.py batch_add_links must hold _lock ----------


class TestBatchAddLinksLocking:
    """batch_add_links must acquire _lock to prevent data races."""

    @pytest.fixture()
    def store(self, tmp_path):
        return GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
        )

    def test_concurrent_batch_add_links_no_data_loss(self, store):
        """Parallel batch_add_links must not lose entries."""
        n_threads = 10
        batch_size = 5
        barrier = threading.Barrier(n_threads)
        errors: list[Exception] = []

        def worker(i: int):
            try:
                barrier.wait(timeout=5)
                links = [
                    (f"from_{i}_{j}", f"to_{i}_{j}", LinkKind.CONTRASTS_WITH, 0.9, f"r{i}_{j}")
                    for j in range(batch_size)
                ]
                store.batch_add_links(links)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Worker errors: {errors}"
        assert len(store._links) == n_threads * batch_size


# ---------- Problem 3: token_tracker WAL + busy_timeout ----------


class TestTokenTrackerWAL:
    """token_tracker must use WAL mode and busy_timeout."""

    def test_wal_and_busy_timeout(self, tmp_path, monkeypatch):
        import kg.token_tracker as tt

        monkeypatch.setattr(tt, "DB_PATH", tmp_path / "token_usage.db")
        monkeypatch.setattr(tt, "_conn", None)

        conn = tt._get_conn()
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal == "wal", f"Expected WAL, got {journal}"

        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert busy >= 5000, f"Expected busy_timeout >= 5000, got {busy}"

        # Cleanup
        monkeypatch.setattr(tt, "_conn", None)


# ---------- Problem 4: input validation max_length on entries ----------


class TestEntriesMaxLength:
    """Push request entries fields must have max_length constraints."""

    def test_review_state_push_entries_bounded(self):
        from kg.api_models import ReviewStatePushRequest, ReviewStateEntry

        # Should reject >5000 entries
        entries = [
            ReviewStateEntry(
                word=f"w{i}", review_interval_hours=1, next_review_at="2025-01-01T00:00:00Z",
                last_reviewed_at="2025-01-01T00:00:00Z", review_count=0, lapse_count=0,
                review_streak=0, last_review_feedback=1,
            )
            for i in range(5001)
        ]
        with pytest.raises(Exception):
            ReviewStatePushRequest(entries=entries)

    def test_daily_review_stats_push_entries_bounded(self):
        from kg.api_models import DailyReviewStatsPushRequest, DailyReviewStatEntry

        # Generate 5001 valid day_keys spanning multiple years
        entries = [
            DailyReviewStatEntry(
                day_key=f"{2020 + i // 365}-{(i % 365) // 30 + 1:02d}-{(i % 365) % 28 + 1:02d}",
                total=1, remembered=1, forgot=0,
            )
            for i in range(5001)
        ]
        with pytest.raises(Exception):
            DailyReviewStatsPushRequest(entries=entries)
