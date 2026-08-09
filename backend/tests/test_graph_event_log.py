"""graph_event_log 單元測試 — per-user append-only 圖譜變動帳本的護欄。

對齊 review_events 範式:event_id 冪等去重、ingested_at 嚴格單調(並發安全)、
is_synthetic 區分合成過去 / 真實未來。本帳本補上圖譜「怎麼變成現在這樣」的歷史,
供未來研究。圖譜本身只存當前態,故這層 event 是無損回溯的唯一來源。
"""

from __future__ import annotations

from datetime import UTC, datetime

from kg.graph_event_log import (
    GraphEvent,
    GraphEventDraft,
    GraphEventSource,
    GraphEventStore,
    GraphEventType,
)


def _draft(
    event_id: str,
    *,
    link_id: str = "L1",
    event_type: GraphEventType = GraphEventType.LINK_ADDED,
    is_synthetic: bool = False,
    source: GraphEventSource = GraphEventSource.AUTO,
    occurred_at: datetime | None = None,
    **overrides,
) -> GraphEventDraft:
    base = dict(
        event_id=event_id,
        event_type=str(event_type),
        link_id=link_id,
        from_id="c1",
        to_id="c2",
        kind="contrasts_with",
        confidence_before=None,
        confidence_after=0.8,
        reason="對比",
        status_before=None,
        status_after="active",
        source=str(source),
        notebook_id="default",
        occurred_at=occurred_at or datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
        is_synthetic=is_synthetic,
    )
    base.update(overrides)
    return GraphEventDraft(**base)


def test_insert_and_read_roundtrip(tmp_path):
    store = GraphEventStore(tmp_path / "graph_events.db")
    res = store.insert_many([_draft("e1"), _draft("e2", link_id="L2")])
    assert res == {"inserted": 2, "skipped": 0}
    events = store.all()
    assert [e.event_id for e in events] == ["e1", "e2"]
    assert events[0].confidence_after == 0.8
    assert events[0].status_after == "active"
    assert events[0].event_type == "link_added"
    assert events[1].link_id == "L2"


def test_event_id_idempotent(tmp_path):
    store = GraphEventStore(tmp_path / "g.db")
    store.insert_many([_draft("e1")])
    res = store.insert_many([_draft("e1"), _draft("e2")])
    assert res == {"inserted": 1, "skipped": 1}
    assert len(store.all()) == 2


def test_ingested_at_strictly_monotonic(tmp_path):
    store = GraphEventStore(tmp_path / "g.db")
    store.insert_many([_draft(f"e{i}") for i in range(25)])
    ts = [e.ingested_at for e in store.all()]
    # 補 UTC 以比較(SQLite 讀回 naive)。
    ts = [t.replace(tzinfo=UTC) if t.tzinfo is None else t for t in ts]
    assert all(ts[i] < ts[i + 1] for i in range(len(ts) - 1))


def test_get_since_cursor(tmp_path):
    store = GraphEventStore(tmp_path / "g.db")
    store.insert_many([_draft(f"e{i}") for i in range(5)])
    allev = store.all()
    cursor = allev[2].ingested_at
    after = store.get_since(cursor)
    assert [e.event_id for e in after] == ["e3", "e4"]


def test_synthetic_filter(tmp_path):
    store = GraphEventStore(tmp_path / "g.db")
    store.insert_many(
        [
            _draft("real", is_synthetic=False),
            _draft("synth", is_synthetic=True, source=GraphEventSource.SYNTH),
        ]
    )
    assert {e.event_id for e in store.query(synthetic=False)} == {"real"}
    assert {e.event_id for e in store.query(synthetic=True)} == {"synth"}
    assert len(store.query()) == 2
    # is_synthetic 讀回為真正的 bool。
    synth = store.query(synthetic=True)[0]
    assert synth.is_synthetic is True
    assert synth.source == "synth"


def test_query_by_link_and_type(tmp_path):
    store = GraphEventStore(tmp_path / "g.db")
    store.insert_many(
        [
            _draft("e1", link_id="L1", event_type=GraphEventType.LINK_ADDED),
            _draft("e2", link_id="L2", event_type=GraphEventType.LINK_ADDED),
            _draft("e3", link_id="L1", event_type=GraphEventType.LINK_DELETED),
        ]
    )
    assert {e.event_id for e in store.query(link_id="L1")} == {"e1", "e3"}
    assert {e.event_id for e in store.query(event_type=GraphEventType.LINK_DELETED)} == {"e3"}


def test_get_since_accepts_naive_cursor(tmp_path):
    # cursor 傳 naive(呼叫端忘了帶 tz):須正規化為 UTC 後比較,不可漏撈/重撈。
    store = GraphEventStore(tmp_path / "g.db")
    store.insert_many([_draft(f"e{i}") for i in range(5)])
    aware_cursor = store.all()[2].ingested_at
    aware_cursor = aware_cursor.replace(tzinfo=UTC) if aware_cursor.tzinfo is None else aware_cursor
    naive_cursor = aware_cursor.replace(tzinfo=None)
    assert [e.event_id for e in store.get_since(naive_cursor)] == ["e3", "e4"]


def test_query_by_source_and_notebook(tmp_path):
    store = GraphEventStore(tmp_path / "g.db")
    store.insert_many(
        [
            _draft("e1", source=GraphEventSource.MANUAL, notebook_id="default"),
            _draft("e2", source=GraphEventSource.OPS, notebook_id="default"),
            _draft("e3", source=GraphEventSource.MANUAL, notebook_id="work"),
        ]
    )
    assert {e.event_id for e in store.query(source=GraphEventSource.MANUAL)} == {"e1", "e3"}
    assert {e.event_id for e in store.query(notebook_id="work")} == {"e3"}
    assert {
        e.event_id
        for e in store.query(source=GraphEventSource.MANUAL, notebook_id="default")
    } == {"e1"}


def test_ingested_at_fallback_when_clock_does_not_advance(tmp_path, monkeypatch):
    # 凍結 wall clock:同微秒多筆寫入仍須靠 +1µs fallback 保持嚴格遞增、唯一。
    import kg.graph_event_log as mod

    frozen = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(mod, "_now", lambda: frozen)
    store = GraphEventStore(tmp_path / "g.db")
    store.insert_many([_draft(f"e{i}") for i in range(4)])
    ts = [
        (t.replace(tzinfo=UTC) if t.tzinfo is None else t)
        for t in (e.ingested_at for e in store.all())
    ]
    assert all(ts[i] < ts[i + 1] for i in range(len(ts) - 1))  # 嚴格遞增
    assert len(set(ts)) == 4                                    # 全唯一


def test_append_single_convenience(tmp_path):
    store = GraphEventStore(tmp_path / "g.db")
    store.append(
        event_id="x1",
        event_type=GraphEventType.LINK_UPDATED,
        link_id="L9",
        from_id="a",
        to_id="b",
        kind="shares_usage",
        confidence_before=0.5,
        confidence_after=0.9,
        reason="bump",
        status_before="active",
        status_after="active",
        source=GraphEventSource.MANUAL,
        notebook_id="default",
        occurred_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    e = store.all()[0]
    assert e.event_type == "link_updated"
    assert e.confidence_before == 0.5 and e.confidence_after == 0.9
    assert e.source == "manual"
    assert e.is_synthetic is False


def test_naive_occurred_at_normalized_to_utc(tmp_path):
    store = GraphEventStore(tmp_path / "g.db")
    store.insert_many([_draft("e1", occurred_at=datetime(2026, 3, 1, 12, 0))])  # naive
    e = store.all()[0]
    assert e.occurred_at.year == 2026 and e.occurred_at.month == 3 and e.occurred_at.hour == 12


def test_persistence_across_reopen(tmp_path):
    path = tmp_path / "g.db"
    store = GraphEventStore(path)
    store.insert_many([_draft("e1"), _draft("e2")])
    store.close()
    reopened = GraphEventStore(path)
    assert {e.event_id for e in reopened.all()} == {"e1", "e2"}
    # 重開後續寫,ingested_at 仍續接單調。
    reopened.insert_many([_draft("e3")])
    ts = [
        (t.replace(tzinfo=UTC) if t.tzinfo is None else t)
        for t in (e.ingested_at for e in reopened.all())
    ]
    assert ts[-1] > ts[-2]


def _count_graphevent_selects(store: GraphEventStore, drafts: list[GraphEventDraft]) -> int:
    """Run insert_many and count SELECTs that touch the graph events table."""
    from sqlalchemy import event as sa_event

    table = GraphEvent.__tablename__
    seen: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.split()).lower()
        if normalized.startswith("select") and table in normalized:
            seen.append(normalized)

    sa_event.listen(store.engine, "before_cursor_execute", _before)
    try:
        store.insert_many(drafts)
    finally:
        sa_event.remove(store.engine, "before_cursor_execute", _before)
    return len(seen)


def test_duplicate_insert_existence_check_does_not_scale_with_batch_size(tmp_path):
    """Existing graph events must be checked in batches, not one query per id."""
    small = [_draft(f"small-{i}") for i in range(20)]
    large = [_draft(f"large-{i}") for i in range(200)]

    small_store = GraphEventStore(tmp_path / "small.db")
    large_store = GraphEventStore(tmp_path / "large.db")
    small_store.insert_many(small)
    large_store.insert_many(large)

    small_selects = _count_graphevent_selects(small_store, small)
    large_selects = _count_graphevent_selects(large_store, large)

    assert small_selects <= 4, f"even a 20-event batch issued {small_selects} SELECTs"
    assert large_selects - small_selects <= 2, (
        f"existence check scales with batch size: {small_selects} -> {large_selects}"
    )


def test_duplicate_event_id_within_one_batch_is_skipped(tmp_path):
    """The batched lookup must preserve the intra-batch duplicate guard."""
    store = GraphEventStore(tmp_path / "graph_events.db")
    first = _draft("evt-dup", reason="first")
    second = _draft("evt-dup", reason="second")

    assert store.insert_many([first, second]) == {"inserted": 1, "skipped": 1}
    assert [event.reason for event in store.all()] == ["first"]
