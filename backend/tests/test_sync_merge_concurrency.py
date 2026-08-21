"""Tests for CardStore updates and concurrent/tombstone sync races."""

from __future__ import annotations

import logging
from datetime import UTC, timedelta

import pytest

from kg.cards import CardStore
from kg.vocab_crud import list_vocab_cards
from kg.vocab_review import push_review_states
from test_sync_merge import _entry, _iso, _make_store, _now


@pytest.fixture(autouse=True)
def _close_card_stores(monkeypatch):
    stores = []
    original_init = CardStore.__init__

    def _track_store(store, *args, **kwargs):
        original_init(store, *args, **kwargs)
        stores.append(store)

    monkeypatch.setattr(CardStore, "__init__", _track_store)
    yield
    for store in reversed(stores):
        store.close()


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
