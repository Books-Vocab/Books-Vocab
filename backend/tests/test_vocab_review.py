"""Tests for kg.vocab_review — push/pull review states using lightweight fakes.

Complements test_sync_merge.py (CardStore integration). Focuses on branches
that are otherwise easy to regress:
  * card_id-precise match wins over word fallback.
  * deleted card with matching card_id is treated as "not found".
  * get_batch is only called when at least one entry carries a card_id.
  * word-fallback updates *every* card sharing that word.
  * pending_updates is flushed via a single batch_update call.
  * client client_last unparseable -> skipped; no batch_update.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from kg.api_models import ReviewStateEntry
from kg.vocab_review import push_review_states


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

    def test_malformed_next_review_at_warns_but_still_accepts(self, caplog):
        """Client is newer + next_review_at present but unparseable.

        The schedule is silently reset to None today; this must now emit a
        WARNING (with card id + raw value) so the reset is diagnosable — while
        keeping the existing accept/write behaviour unchanged.
        """
        c1 = _ReviewCard(id="c1", content="cat")
        store = _FakeCardsStore([c1])
        client_time = datetime.now(UTC)
        entry = _entry(
            word="cat",
            card_id="c1",
            last_reviewed_at=_iso(client_time),
            next_review_at="garbage-not-a-date",  # present, but parse_datetime -> None
        )

        with caplog.at_level(logging.WARNING):
            result = push_review_states([entry], cards_store=store, logger=logging.getLogger())

        # Behaviour is unchanged: card is still accepted/written, next_review_at=None.
        assert result == {"updated": 1, "skipped": 0}
        flushed = store.batch_update_calls[0][0][1]
        assert flushed["next_review_at"] is None
        assert flushed["last_reviewed_at"] == client_time
        # The silent reset is now visible: a WARNING naming the card + raw value.
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        assert "c1" in msg
        assert "garbage-not-a-date" in msg

    def test_valid_next_review_at_does_not_warn(self, caplog):
        """Normal payload (parseable next_review_at) must not emit any warning."""
        c1 = _ReviewCard(id="c1", content="cat")
        store = _FakeCardsStore([c1])
        client_time = datetime.now(UTC)
        entry = _entry(
            word="cat",
            card_id="c1",
            last_reviewed_at=_iso(client_time),
            next_review_at=_iso(client_time + timedelta(hours=24)),
        )

        with caplog.at_level(logging.WARNING):
            result = push_review_states([entry], cards_store=store, logger=logging.getLogger())

        assert result == {"updated": 1, "skipped": 0}
        assert [r for r in caplog.records if r.levelno == logging.WARNING] == []

    def test_empty_next_review_at_does_not_warn(self, caplog):
        """Empty next_review_at == 'not meaningfully sent' -> reset is expected,
        no false-positive warning. Distinguishes 'absent/empty' from 'malformed'."""
        c1 = _ReviewCard(id="c1", content="cat")
        store = _FakeCardsStore([c1])
        client_time = datetime.now(UTC)
        entry = _entry(
            word="cat",
            card_id="c1",
            last_reviewed_at=_iso(client_time),
            next_review_at="   ",  # whitespace-only -> parse None, but not a real value
        )

        with caplog.at_level(logging.WARNING):
            result = push_review_states([entry], cards_store=store, logger=logging.getLogger())

        # Still accepted (behaviour unchanged), but no warning fired.
        assert result == {"updated": 1, "skipped": 0}
        assert store.batch_update_calls[0][0][1]["next_review_at"] is None
        assert [r for r in caplog.records if r.levelno == logging.WARNING] == []

    def test_server_newer_takes_max_counts(self):
        server_time = datetime.now(UTC)
        client_time = server_time - timedelta(hours=1)
        c1 = _ReviewCard(
            id="c1",
            content="cat",
            last_reviewed_at=server_time,
            review_count=3,
            lapse_count=1,
        )
        store = _FakeCardsStore([c1])
        entry = _entry(
            word="cat",
            last_reviewed_at=_iso(client_time),
            review_count=5,
            lapse_count=0,  # only review_count is higher than server
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
            id="c1",
            content="cat",
            last_reviewed_at=server_time,
            review_count=10,
            lapse_count=2,
        )
        store = _FakeCardsStore([c1])
        entry = _entry(
            word="cat",
            last_reviewed_at=_iso(client_time),
            review_count=5,
            lapse_count=1,
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

        push_review_states([entry], cards_store=store, logger=logging.getLogger(), notebook_id="nb_x")
        assert store.all_calls == ["nb_x"]

    def test_empty_entries_returns_zero(self):
        store = _FakeCardsStore([])
        result = push_review_states([], cards_store=store, logger=logging.getLogger())
        assert result == {"updated": 0, "skipped": 0}
        assert store.get_batch_calls == []
        assert store.batch_update_calls == []

    def test_duplicate_word_fallback_coalesces_to_newest_schedule(self):
        """Legacy word-only retries must not roll a card back by input order."""
        older_last = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
        newer_last = older_last + timedelta(hours=1)
        store = _FakeCardsStore([_ReviewCard(id="c1", content="review")])
        older_entry = _entry(
            word="review",
            last_reviewed_at=_iso(older_last),
            review_interval_hours=12.0,
            next_review_at=_iso(older_last + timedelta(hours=12)),
            review_count=1,
            review_streak=1,
            last_review_feedback=0,
        )
        newer_entry = _entry(
            word="review",
            last_reviewed_at=_iso(newer_last),
            review_interval_hours=48.0,
            next_review_at=_iso(newer_last + timedelta(hours=48)),
            review_count=2,
            review_streak=4,
            last_review_feedback=1,
        )

        result = push_review_states(
            [newer_entry, older_entry],
            cards_store=store,
            logger=logging.getLogger(),
        )

        assert result == {"updated": 1, "skipped": 1}
        assert len(store.batch_update_calls) == 1
        assert len(store.batch_update_calls[0]) == 1
        updated = store._cards[0]
        assert updated.review_interval_hours == 48.0
        assert updated.next_review_at == newer_last + timedelta(hours=48)
        assert updated.review_streak == 4
        assert updated.last_review_feedback == 1
        assert updated.last_reviewed_at == newer_last
