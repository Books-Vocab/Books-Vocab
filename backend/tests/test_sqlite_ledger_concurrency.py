"""Contract test for the two append-only SQLite ledger implementations.

Both stores use the same transaction installation seam, so this test deliberately
opens two independent writers for each ledger against one database.  A single
writer test cannot observe the lock / max-watermark race this contract protects.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

from kg.api_models import ReviewEventEntry
from kg.graph_event_log import GraphEventDraft, GraphEventStore
from kg.review_events import ReviewEventStore
from kg.sqlite_ledger import as_utc

_ROUNDS = 3
_DISJOINT_PER_WRITER = 6


def _review_entry(event_id: str) -> ReviewEventEntry:
    return ReviewEventEntry(
        event_id=event_id,
        card_id="card-1",
        word_snapshot="ledger",
        notebook_id="default",
        feedback=1,
        reviewed_at="2026-08-11T00:00:00+00:00",
        created_at="2026-08-11T00:00:01+00:00",
    )


def _graph_draft(event_id: str) -> GraphEventDraft:
    return GraphEventDraft(
        event_id=event_id,
        event_type="link_added",
        link_id="link-1",
        from_id="card-1",
        to_id="card-2",
        kind="contrasts_with",
        confidence_before=None,
        confidence_after=0.8,
        reason="concurrency contract",
        status_before=None,
        status_after="active",
        source="auto",
        notebook_id="default",
        occurred_at=datetime(2026, 8, 11, tzinfo=UTC),
    )


def _parallel_rounds(stores, make_entry, prefix: str) -> None:
    """Run disjoint writes, then duplicate replay, across two independent writers."""
    for round_no in range(_ROUNDS):
        barrier = Barrier(len(stores))

        def writer(writer_no: int, *, barrier=barrier, round_no=round_no):
            barrier.wait(timeout=30)
            disjoint = [make_entry(f"{prefix}-{round_no}-{writer_no}-{i}") for i in range(_DISJOINT_PER_WRITER)]
            first = stores[writer_no].insert_many(disjoint)
            barrier.wait(timeout=30)
            duplicate = stores[writer_no].insert_many([make_entry(f"{prefix}-{round_no}-shared")])
            return first, duplicate

        with ThreadPoolExecutor(max_workers=len(stores)) as pool:
            results = [future.result(timeout=45) for future in [pool.submit(writer, i) for i in range(len(stores))]]
        assert all(first == {"inserted": _DISJOINT_PER_WRITER, "skipped": 0} for first, _duplicate in results)
        assert sum(duplicate["inserted"] for _first, duplicate in results) == 1
        assert sum(duplicate["skipped"] for _first, duplicate in results) == 1


def _paginate(store, expected_ids: list[str]) -> list[str]:
    """Advance one cursor row at a time and prove the strict ``>`` boundary."""
    cursor = datetime(1970, 1, 1, tzinfo=UTC)
    seen: list[str] = []
    while True:
        page = store.get_since(cursor)
        if not page:
            break
        event = page[0]
        timestamp = as_utc(event.ingested_at)
        assert timestamp > cursor
        seen.append(event.event_id)
        cursor = timestamp
        assert len(seen) <= len(expected_ids)
    assert sorted(seen) == sorted(expected_ids)
    assert len(seen) == len(set(seen))
    return seen


def _assert_ledger(store, expected_ids: list[str]) -> None:
    events = store.all()
    timestamps = [as_utc(event.ingested_at) for event in events]
    assert [event.event_id for event in events] == _paginate(store, expected_ids)
    assert len(events) == len(expected_ids)
    assert len(set(timestamps)) == len(timestamps), "ingested_at duplicated within ledger"
    assert timestamps == sorted(timestamps), "ingested_at lost strict ordering within ledger"


def test_review_and_graph_ledgers_are_safe_with_two_concurrent_writers(tmp_path: Path, monkeypatch):
    """Frozen clocks and duplicate replays must not lose events or watermarks."""
    frozen = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    monkeypatch.setattr("kg.review_events._now", lambda: frozen)
    monkeypatch.setattr("kg.graph_event_log._now", lambda: frozen)

    db_path = tmp_path / "shared-ledgers.db"
    review_stores = [ReviewEventStore(db_path), ReviewEventStore(db_path)]
    graph_stores = [GraphEventStore(db_path), GraphEventStore(db_path)]
    try:
        _parallel_rounds(review_stores, _review_entry, "review")
        _parallel_rounds(graph_stores, _graph_draft, "graph")

        expected_review = [
            f"review-{round_no}-{writer_no}-{i}"
            for round_no in range(_ROUNDS)
            for writer_no in range(2)
            for i in range(_DISJOINT_PER_WRITER)
        ] + [f"review-{round_no}-shared" for round_no in range(_ROUNDS)]
        expected_graph = [
            f"graph-{round_no}-{writer_no}-{i}"
            for round_no in range(_ROUNDS)
            for writer_no in range(2)
            for i in range(_DISJOINT_PER_WRITER)
        ] + [f"graph-{round_no}-shared" for round_no in range(_ROUNDS)]
        _assert_ledger(review_stores[0], expected_review)
        _assert_ledger(graph_stores[0], expected_graph)
    finally:
        for store in [*review_stores, *graph_stores]:
            store.close()
