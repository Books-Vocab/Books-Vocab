from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kg.api_models import ReviewEventEntry
from kg.exceptions import BadRequestError
from kg.review_events import ReviewEventStore, pull_review_events, push_review_events


def _event(
    event_id: str = "evt-1",
    *,
    reviewed_at: datetime | None = None,
    word: str = "serendipity",
    card_id: str | None = "card-1",
) -> ReviewEventEntry:
    reviewed = reviewed_at or datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    return ReviewEventEntry(
        event_id=event_id,
        card_id=card_id,
        word_snapshot=word,
        notebook_id="default",
        feedback=1,
        reviewed_at=reviewed.isoformat(),
        created_at=(reviewed + timedelta(seconds=5)).isoformat(),
    )


def test_review_event_store_empty(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")

    assert store.all() == []


def test_push_and_pull_review_events_round_trip(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    first = _event("evt-1", reviewed_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC))
    second = _event("evt-2", reviewed_at=datetime(2026, 6, 2, 10, 0, tzinfo=UTC), word="ephemeral")

    result = push_review_events([second, first], event_store=store)
    pulled = pull_review_events(since=None, event_store=store)

    assert result == {"inserted": 2, "skipped": 0}
    assert [event.event_id for event in pulled] == ["evt-1", "evt-2"]
    assert pulled[0].word_snapshot == "serendipity"
    assert pulled[1].word_snapshot == "ephemeral"


def test_duplicate_event_id_is_skipped(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    first = _event("evt-1", word="first")
    duplicate = _event("evt-1", word="second")

    assert push_review_events([first], event_store=store) == {"inserted": 1, "skipped": 0}
    assert push_review_events([duplicate], event_store=store) == {"inserted": 0, "skipped": 1}

    pulled = pull_review_events(since=None, event_store=store)
    assert len(pulled) == 1
    assert pulled[0].word_snapshot == "first"


def test_since_filters_by_reviewed_at(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    old = _event("old", reviewed_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC))
    new = _event("new", reviewed_at=datetime(2026, 6, 2, 10, 0, tzinfo=UTC))
    push_review_events([old, new], event_store=store)

    pulled = pull_review_events(
        since="2026-06-02T00:00:00+00:00",
        event_store=store,
    )

    assert [event.event_id for event in pulled] == ["new"]


@pytest.mark.parametrize("bad_since", ["garbage", "2026-13-99", "2026-06-01", "1717668000", "2026-06-01T10:00:00"])
def test_since_must_be_iso8601(tmp_path, bad_since):
    store = ReviewEventStore(tmp_path / "review_events.db")

    with pytest.raises(BadRequestError):
        pull_review_events(since=bad_since, event_store=store)


@pytest.mark.parametrize("field_name", ["reviewed_at", "created_at"])
@pytest.mark.parametrize("bad_value", ["2026-06-01", "1717668000", "2026-06-01T10:00:00"])
def test_event_timestamps_must_be_timezone_aware_iso8601(tmp_path, field_name, bad_value):
    store = ReviewEventStore(tmp_path / "review_events.db")
    event = _event("evt-bad-time")
    data = event.model_dump()
    data[field_name] = bad_value

    with pytest.raises(BadRequestError):
        push_review_events([ReviewEventEntry(**data)], event_store=store)


def test_unknown_card_id_is_preserved(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    event = _event("evt-unknown", card_id="deleted-card")

    push_review_events([event], event_store=store)

    pulled = pull_review_events(since=None, event_store=store)
    assert pulled[0].card_id == "deleted-card"
