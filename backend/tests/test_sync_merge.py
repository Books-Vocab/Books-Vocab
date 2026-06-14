"""
Tests for sync merge logic — push_review_states, incremental sync, and soft-delete.

Covers the core conflict resolution code in vocab_service.push_review_states()
and the incremental sync boundary in list_vocab_cards().
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kg.api_models import ReviewStateEntry
from kg.cards import CardStore
from kg.vocab_crud import list_vocab_cards
from kg.vocab_review import push_review_states

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
    return datetime.now(UTC)


def _entry(
    word: str,
    last_reviewed_at: str,
    *,
    card_id: str | None = None,
    review_interval_hours: float = 24.0,
    next_review_at: str | None = None,
    review_count: int = 1,
    lapse_count: int = 0,
    review_streak: int = 1,
    last_review_feedback: int = 1,
) -> ReviewStateEntry:
    return ReviewStateEntry(
        word=word,
        card_id=card_id,
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
        store.add("Evoke", "喚起")

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

    def test_card_id_targets_exact_card_cross_notebook(self, tmp_path):
        """When card_id is provided, only that exact card is updated — not same-word cards in other notebooks."""
        store = _make_store(tmp_path)
        card_a = store.add("run", "跑", notebook_id="notebook-a")
        card_b = store.add("run", "跑", notebook_id="notebook-b")

        client_time = _now()
        entry = _entry("run", _iso(client_time), review_count=5, review_streak=3, card_id=card_a.id)

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 1, "skipped": 0}

        updated_a = store.get(card_a.id)
        updated_b = store.get(card_b.id)
        assert updated_a.review_count == 5
        assert updated_a.review_streak == 3
        # notebook-b's "run" must be untouched
        assert updated_b.review_count == 0
        assert updated_b.review_streak == 0

    def test_card_id_fallback_word_match_without_card_id(self, tmp_path):
        """Without card_id, fallback to word matching — updates all same-word cards (backward compat)."""
        store = _make_store(tmp_path)
        card_a = store.add("evoke", "喚起", notebook_id="notebook-a")
        card_b = store.add("evoke", "喚起", notebook_id="notebook-b")

        client_time = _now()
        entry = _entry("evoke", _iso(client_time), review_count=5, review_streak=3)

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 2, "skipped": 0}

        updated_a = store.get(card_a.id)
        updated_b = store.get(card_b.id)
        assert updated_a.review_count == 5
        assert updated_b.review_count == 5
        assert updated_a.review_streak == 3
        assert updated_b.review_streak == 3

    def test_card_id_not_found_skips(self, tmp_path):
        """Entry with non-existent card_id should be skipped."""
        store = _make_store(tmp_path)
        store.add("run", "跑", notebook_id="default")

        client_time = _now()
        entry = _entry("run", _iso(client_time), review_count=5, card_id="nonexistent-id")

        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 0, "skipped": 1}


# ============================================================================
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

    def test_full_sync_returns_all_active_cards(self, tmp_path):
        """Full sync (since=None) returns all non-deleted cards."""
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
        assert words == {"apple", "banana"}

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


# ============================================================================
# Three-end concurrent sync (iOS + Mac + server)
# ============================================================================


class TestThreeEndConcurrentSync:
    """Cover conflicts that arise when iOS, Mac, and the server all act
    on the same vocabulary state without seeing each other yet.

    Modelling note: the server holds a single CardStore (source of truth).
    "iOS" and "Mac" are two independent clients that build sync payloads
    locally, then flush in some order. The tests therefore drive
    ``push_review_states`` and ``CardStore`` directly — that is the actual
    conflict-resolution surface.
    """

    # --- 1. Concurrent create from three ends must dedup -----------------

    def test_three_end_concurrent_create_dedup(self, tmp_path):
        """iOS + Mac + server-direct each create the same word in the same
        notebook before any sync round-trip. After all three writes land
        in the server store, there must be exactly one active card and
        every "client view" must converge on the same canonical id.
        """
        store = _make_store(tmp_path)

        # Three independent clients call add() with identical (content,
        # notebook_id). Each thinks it is creating a fresh entry.
        card_from_ios = store.add("evoke", "iOS 喚起", notebook_id="default")
        card_from_mac = store.add("evoke", "Mac 喚起", notebook_id="default")
        card_from_server = store.add("evoke", "Server 喚起", notebook_id="default")

        # Dedup contract: UNIQUE(content COLLATE NOCASE, notebook_id) WHERE
        # is_deleted = 0 means add() returns the existing row on conflict.
        # All three call sites must point at the same canonical id.
        assert card_from_ios.id == card_from_mac.id == card_from_server.id

        # And the store must hold exactly one active row for this content.
        active = [c for c in store.all(include_deleted=False) if c.content.lower() == "evoke"]
        assert len(active) == 1
        # The first write wins — its meaning is preserved (add() is a
        # get-or-create, not an upsert that overwrites meaning).
        assert active[0].meaning == "iOS 喚起"

    def test_three_end_create_distinct_notebooks_not_deduped(self, tmp_path):
        """Same word in *different* notebooks is intentionally NOT dedup'd
        — this guards against the dedup test above over-reaching across
        notebook boundaries.
        """
        store = _make_store(tmp_path)
        ios = store.add("evoke", "iOS", notebook_id="ios-nb")
        mac = store.add("evoke", "Mac", notebook_id="mac-nb")
        server = store.add("evoke", "Server", notebook_id="default")
        # Three separate cards survive — dedup is scoped per notebook.
        assert len({ios.id, mac.id, server.id}) == 3

    # --- 2. Three-end modify: last-writer-wins on last_reviewed_at -------

    def test_three_end_concurrent_modify_last_writer_wins(self, tmp_path):
        """Three ends each modify the same card with different
        ``last_reviewed_at`` timestamps. We flush them in iOS → Mac → server
        order; the final state must reflect the entry with the newest
        ``last_reviewed_at``, regardless of arrival order.
        """
        store = _make_store(tmp_path)
        card = store.add("lucid", "清晰的")

        base = _now() - timedelta(hours=10)
        ts_ios = base + timedelta(hours=1)
        ts_mac = base + timedelta(hours=5)   # newest
        ts_server = base + timedelta(hours=3)

        ios_entry = _entry(
            "lucid", _iso(ts_ios),
            review_count=2, review_streak=2, review_interval_hours=12.0,
            last_review_feedback=1,
        )
        mac_entry = _entry(
            "lucid", _iso(ts_mac),
            review_count=4, review_streak=4, review_interval_hours=48.0,
            last_review_feedback=1,
        )
        server_entry = _entry(
            "lucid", _iso(ts_server),
            review_count=3, review_streak=3, review_interval_hours=24.0,
            last_review_feedback=0,
        )

        log = logging.getLogger()
        # Order: iOS → Mac → server (each call merges against current server state).
        push_review_states([ios_entry], cards_store=store, logger=log)
        push_review_states([mac_entry], cards_store=store, logger=log)
        push_review_states([server_entry], cards_store=store, logger=log)

        final = store.get(card.id)
        # Mac had the newest last_reviewed_at, so its review_streak /
        # review_interval_hours / last_review_feedback must be the final state.
        assert final.review_streak == 4
        assert final.review_interval_hours == 48.0
        assert final.last_review_feedback == 1
        # Counts use max() across all merges — must not regress.
        assert final.review_count == max(2, 4, 3)
        # last_reviewed_at must be the latest the server has seen.
        # SQLite drops tzinfo on read; normalize both sides to UTC-naive.
        assert final.last_reviewed_at is not None
        final_lr = final.last_reviewed_at
        if final_lr.tzinfo is not None:
            final_lr = final_lr.astimezone(UTC).replace(tzinfo=None)
        ts_mac_naive = ts_mac.astimezone(UTC).replace(tzinfo=None)
        assert abs((final_lr - ts_mac_naive).total_seconds()) < 1

    def test_three_end_modify_arrival_order_independent(self, tmp_path):
        """Final state must be deterministic regardless of which client's
        payload reaches the server first. We replay the same three-way
        conflict in reverse arrival order and assert convergence.
        """
        log = logging.getLogger()

        def _run(order: list[str]) -> tuple[float, int, int]:
            store = _make_store(tmp_path / order[0])
            card = store.add("nuance", "細微差別")
            base = _now() - timedelta(hours=10)
            payloads = {
                "ios": _entry("nuance", _iso(base + timedelta(hours=1)),
                              review_count=2, review_streak=2,
                              review_interval_hours=12.0),
                "mac": _entry("nuance", _iso(base + timedelta(hours=5)),
                              review_count=4, review_streak=4,
                              review_interval_hours=48.0),
                "server": _entry("nuance", _iso(base + timedelta(hours=3)),
                                 review_count=3, review_streak=3,
                                 review_interval_hours=24.0),
            }
            for who in order:
                push_review_states([payloads[who]], cards_store=store, logger=log)
            final = store.get(card.id)
            return final.review_interval_hours, final.review_streak, final.review_count

        forward = _run(["ios", "mac", "server"])
        reverse = _run(["server", "mac", "ios"])
        scrambled = _run(["mac", "ios", "server"])
        # All three arrival orders must converge to the same final state.
        assert forward == reverse == scrambled
        # And that state must be Mac's (newest last_reviewed_at).
        assert forward == (48.0, 4, 4)

    # --- 3. Tombstone vs restore / modify race ---------------------------

    def test_tombstone_vs_modify_race_tombstone_wins(self, tmp_path):
        """One end deletes the card (tombstone). A second end, unaware of
        the delete, flushes a review-state update for the same card.
        Outcome: the tombstone wins — the card stays deleted and the
        modify is silently skipped. There must be no "modified zombie"
        (is_deleted=True but with the client's new review counts).
        """
        store = _make_store(tmp_path)
        card = store.add("ephemeral", "短暫的", notebook_id="default")

        # End A: delete (tombstone).
        assert store.delete(card.id) is True

        # End B (concurrently, with stale view): push review state.
        # Use card_id so the path is the deterministic id-match branch.
        client_time = _now()
        entry = _entry(
            "ephemeral",
            _iso(client_time),
            card_id=card.id,
            review_count=99,
            review_streak=42,
            review_interval_hours=240.0,
        )
        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())

        # The tombstoned card is invisible to push: it must be skipped.
        assert result == {"updated": 0, "skipped": 1}

        refreshed = store.get(card.id)
        assert refreshed is not None
        assert refreshed.is_deleted is True
        # Critical: the tombstone was NOT mutated by the racing modify.
        assert refreshed.review_count == 0
        assert refreshed.review_streak == 0
        assert refreshed.review_interval_hours == card.review_interval_hours

    def test_tombstone_vs_modify_race_word_match_path(self, tmp_path):
        """Same race as above, but the racing client pushes without a
        ``card_id`` (legacy word-match path). Tombstone must still win:
        ``push_review_states`` word-index iterates ``cards_store.all()``
        which excludes deleted cards, so no same-word *active* card is
        accidentally updated either.
        """
        store = _make_store(tmp_path)
        card = store.add("transient", "暫態的", notebook_id="default")
        store.delete(card.id)

        entry = _entry(
            "transient",
            _iso(_now()),
            review_count=50,
            review_streak=10,
        )
        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 0, "skipped": 1}

        refreshed = store.get(card.id)
        assert refreshed.is_deleted is True
        assert refreshed.review_count == 0

    def test_tombstone_vs_restore_via_readd_creates_fresh_card(self, tmp_path):
        """One end deletes; another end "restores" by re-adding the same
        word (the typical iOS/Mac UX when a user re-captures a word after
        deletion). Because the UNIQUE partial index is scoped to
        ``is_deleted = 0``, ``add()`` creates a brand-new active card
        alongside the tombstone. The tombstone is preserved for
        incremental sync, and the new card carries no stale review state.

        This characterises current behaviour and guards against regressions
        that would either (a) silently reuse the tombstone's id or
        (b) collapse the tombstone, breaking incremental delete propagation
        for the third end that has not yet pulled the delete.
        """
        store = _make_store(tmp_path)
        original = store.add("renew", "更新", notebook_id="default")
        # Seed some review state we must not see leak into the new card.
        store.update(
            original.id,
            review_count=7,
            review_streak=5,
            last_reviewed_at=_now() - timedelta(hours=1),
        )
        assert store.delete(original.id) is True

        # Concurrent re-add by another end.
        readded = store.add("renew", "更新 v2", notebook_id="default")

        assert readded.id != original.id
        assert readded.is_deleted is False
        # Fresh review state — no bleed-through from the tombstone.
        assert readded.review_count == 0
        assert readded.review_streak == 0
        assert readded.last_reviewed_at is None

        # The tombstone is intact so a third end that pulls incrementally
        # still observes the delete.
        from unittest.mock import MagicMock

        from kg.api_models import CardResponse

        def _builder(card, _graph, _cards_by_id):
            return CardResponse(
                id=card.id, content=card.content, meaning=card.meaning,
                pos=card.pos, difficulty=card.difficulty, difficultyTier="unknown",
                note=card.note, examples=card.examples, mode=card.mode,
                isDeleted=card.is_deleted, inflections=card.inflections or [],
                linksByKind={}, reviewIntervalHours=card.review_interval_hours,
                nextReviewAt=None, lastReviewedAt=None,
                reviewCount=card.review_count, lapseCount=card.lapse_count,
                reviewStreak=card.review_streak,
                lastReviewFeedback=card.last_review_feedback,
            )

        results, _cursor = list_vocab_cards(
            since=_iso(_now() - timedelta(hours=24)),
            cards_store=store,
            graph=MagicMock(),
            card_response_builder=_builder,
        )
        by_id = {r.id: r for r in results}
        assert by_id[original.id].isDeleted is True
        assert by_id[readded.id].isDeleted is False

    def test_tombstone_vs_explicit_restore_then_modify(self, tmp_path):
        """One end deletes; another end calls ``CardStore.restore`` (the
        explicit un-delete path used by graph-failure rollback) and then
        a review-state push lands. After restore, the modify must apply
        normally — the tombstone path should not "stick".
        """
        store = _make_store(tmp_path)
        card = store.add("revive", "復活")
        store.delete(card.id)
        assert store.restore(card.id) is True

        # Now push from a client that thinks the card still exists.
        client_time = _now()
        entry = _entry(
            "revive", _iso(client_time),
            card_id=card.id, review_count=11, review_streak=3,
            review_interval_hours=36.0,
        )
        result = push_review_states([entry], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 1, "skipped": 0}

        refreshed = store.get(card.id)
        assert refreshed.is_deleted is False
        assert refreshed.review_count == 11
        assert refreshed.review_streak == 3
        assert refreshed.review_interval_hours == 36.0


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
        assert len(tombstones) == 1, (
            f"expected tombstone in incremental sync, got {len(tombstones)}"
        )
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
            f"pagination produced duplicates: "
            f"{[x for x in collected if collected.count(x) > 1][:5]}"
        )
        # No gaps — every card appears exactly once
        assert set(collected) == {cid for _, cid in ids_by_ts}, (
            f"pagination missed cards: "
            f"missing={ {cid for _, cid in ids_by_ts} - set(collected)} "
            f"extra={set(collected) - {cid for _, cid in ids_by_ts}}"
        )
        assert len(collected) == total
