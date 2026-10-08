"""GraphSnapshot 測試 — 圖譜整檔狀態週期 checkpoint。

event log 記逐筆 diff,snapshot 記某時點的完整 link 狀態。兩者合一即可重建任意時間點
的圖譜(從最近 snapshot 起,套用其後的 diff 事件),也是 event log 萬一被截斷時的安全網。
is_synthetic 區分遷移當下的初始合成 snapshot 與上線後真實週期 snapshot。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event as sa_event

from kg.graph_event_log import GraphEventStore, GraphSnapshot, GraphSnapshotStore

_SNAPSHOT_TABLE = GraphSnapshot.__tablename__


def _links(n: int) -> list[dict]:
    return [
        {
            "id": f"L{i}",
            "from_id": f"a{i}",
            "to_id": f"b{i}",
            "kind": "shares_usage",
            "confidence": 0.5,
            "reason": "r",
            "created_at": "2026-04-01T00:00:00+00:00",
            "status": "active",
        }
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _graph_stores_are_closed(monkeypatch):
    stores = []
    real_event_init = GraphEventStore.__init__
    real_snapshot_init = GraphSnapshotStore.__init__

    def track_event_init(store, path):
        real_event_init(store, path)
        stores.append(store)

    def track_snapshot_init(store, path):
        real_snapshot_init(store, path)
        stores.append(store)

    monkeypatch.setattr(GraphEventStore, "__init__", track_event_init)
    monkeypatch.setattr(GraphSnapshotStore, "__init__", track_snapshot_init)
    yield
    for store in reversed(stores):
        store.close()


def test_save_and_latest_roundtrip(tmp_path):
    store = GraphSnapshotStore(tmp_path / "graph_events.db")
    sid = store.save("default", _links(3), is_synthetic=True)
    assert sid
    snap = store.latest("default")
    assert snap is not None
    assert snap.notebook_id == "default"
    assert snap.link_count == 3
    assert snap.is_synthetic is True
    assert len(snap.links) == 3
    assert snap.links[0]["id"] == "L0"


def test_latest_returns_most_recent(tmp_path):
    store = GraphSnapshotStore(tmp_path / "g.db")
    store.save("default", _links(2), is_synthetic=True)
    store.save("default", _links(5), is_synthetic=False)
    snap = store.latest("default")
    assert snap.link_count == 5
    assert snap.is_synthetic is False


def test_latest_is_per_notebook(tmp_path):
    store = GraphSnapshotStore(tmp_path / "g.db")
    store.save("default", _links(2), is_synthetic=True)
    store.save("work", _links(7), is_synthetic=True)
    assert store.latest("default").link_count == 2
    assert store.latest("work").link_count == 7
    assert store.latest("missing") is None


def test_explicit_taken_at_is_preserved(tmp_path):
    store = GraphSnapshotStore(tmp_path / "g.db")
    ts = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
    store.save("default", _links(1), is_synthetic=True, taken_at=ts)
    snap = store.latest("default")
    assert snap.taken_at.replace(tzinfo=UTC) == ts if snap.taken_at.tzinfo is None else snap.taken_at == ts


def test_all_lists_chronologically(tmp_path):
    store = GraphSnapshotStore(tmp_path / "g.db")
    store.save("default", _links(1), is_synthetic=True, taken_at=datetime(2026, 1, 1, tzinfo=UTC))
    store.save("default", _links(2), is_synthetic=False, taken_at=datetime(2026, 2, 1, tzinfo=UTC))
    snaps = store.all(notebook_id="default")
    assert [s.link_count for s in snaps] == [1, 2]


def test_empty_links_snapshot_is_valid(tmp_path):
    store = GraphSnapshotStore(tmp_path / "g.db")
    store.save("default", [], is_synthetic=True)
    snap = store.latest("default")
    assert snap.link_count == 0
    assert snap.links == []


def test_latest_deterministic_on_tied_taken_at(tmp_path):
    # 同 taken_at 多筆:latest 須確定回 snapshot_id 最大者,不可非確定。
    store = GraphSnapshotStore(tmp_path / "g.db")
    ts = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    ids = {store.save("default", _links(i + 1), is_synthetic=True, taken_at=ts) for i in range(5)}
    snap = store.latest("default")
    assert snap.snapshot_id == max(ids)


def test_chinese_reason_round_trips(tmp_path):
    store = GraphSnapshotStore(tmp_path / "g.db")
    links = [
        {
            "id": "L0",
            "from_id": "a",
            "to_id": "b",
            "kind": "contrasts_with",
            "confidence": 0.9,
            "reason": "語意對比:嚴謹 vs 馬虎",
            "created_at": "2026-04-01T00:00:00+00:00",
            "status": "active",
        }
    ]
    store.save("default", links, is_synthetic=True)
    assert store.latest("default").links[0]["reason"] == "語意對比:嚴謹 vs 馬虎"


def test_persists_across_reopen(tmp_path):
    path = tmp_path / "g.db"
    store = GraphSnapshotStore(path)
    store.save("default", _links(4), is_synthetic=True)
    store.close()
    reopened = GraphSnapshotStore(path)
    assert reopened.latest("default").link_count == 4


def test_periodic_snapshot_saved_immediately_when_missing(tmp_path):
    store = GraphSnapshotStore(tmp_path / "g.db")
    res = store.maybe_save_periodic("default", _links(2), min_events_since_snapshot=50)
    assert res["saved"] is True
    assert res["reason"] == "no-snapshot"
    latest = store.latest("default")
    assert latest is not None
    assert latest.is_synthetic is False
    assert latest.link_count == 2


def test_periodic_snapshot_skips_below_threshold(tmp_path):
    path = tmp_path / "g.db"
    events = GraphEventStore(path)
    snaps = GraphSnapshotStore(path)
    snaps.save("default", _links(1), is_synthetic=False, taken_at=datetime(2026, 6, 1, tzinfo=UTC))
    for i in range(2):
        events.append(
            event_id=f"e{i}",
            event_type="link_updated",
            link_id=f"L{i}",
            from_id="a",
            to_id="b",
            kind="shares_usage",
            source="auto",
            notebook_id="default",
            occurred_at=datetime(2026, 6, 2, tzinfo=UTC),
            confidence_before=0.1,
            confidence_after=0.2,
            status_before="active",
            status_after="active",
        )
    res = snaps.maybe_save_periodic("default", _links(3), min_events_since_snapshot=3)
    assert res["saved"] is False
    assert res["reason"] == "below-threshold"
    assert res["events_since_snapshot"] == 2
    assert len(snaps.all(notebook_id="default")) == 1


def test_periodic_snapshot_saves_once_threshold_reached(tmp_path):
    path = tmp_path / "g.db"
    events = GraphEventStore(path)
    snaps = GraphSnapshotStore(path)
    snaps.save("default", _links(1), is_synthetic=False, taken_at=datetime(2026, 6, 1, tzinfo=UTC))
    for i in range(3):
        events.append(
            event_id=f"e{i}",
            event_type="link_updated",
            link_id=f"L{i}",
            from_id="a",
            to_id="b",
            kind="shares_usage",
            source="auto",
            notebook_id="default",
            occurred_at=datetime(2026, 6, 2, tzinfo=UTC),
            confidence_before=0.1,
            confidence_after=0.2,
            status_before="active",
            status_after="active",
        )
    res = snaps.maybe_save_periodic("default", _links(4), min_events_since_snapshot=3)
    assert res["saved"] is True
    assert res["reason"] == "event-threshold"
    latest = snaps.latest("default")
    assert latest is not None
    assert latest.link_count == 4
    assert latest.is_synthetic is False
    assert len(snaps.all(notebook_id="default")) == 2


def _capture_snapshot_reads(store: GraphSnapshotStore, call):
    """Run ``call``; return its result, the GraphSnapshot rows the ORM loaded, and
    every SELECT on the snapshot table that pulls ``links_json`` blobs."""
    loaded: list[str] = []
    blob_selects: list[str] = []

    def _on_load(target, _context):
        loaded.append(target.snapshot_id)

    def _before(conn, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.split()).lower()
        if normalized.startswith("select") and _SNAPSHOT_TABLE in normalized and "links_json" in normalized:
            blob_selects.append(normalized)

    sa_event.listen(GraphSnapshot, "load", _on_load)
    sa_event.listen(store.engine, "before_cursor_execute", _before)
    try:
        result = call()
    finally:
        sa_event.remove(store.engine, "before_cursor_execute", _before)
        sa_event.remove(GraphSnapshot, "load", _on_load)
    return result, loaded, blob_selects


def _save_history(store: GraphSnapshotStore, count: int, *, days_per_group: int = 1) -> list[tuple[datetime, str]]:
    """Save ``count`` snapshots for 'default'; return (taken_at, id) newest-first in
    the store's (taken_at desc, snapshot_id desc) order. ``days_per_group`` > 1 puts
    several snapshots on one taken_at so the snapshot_id tie-break is exercised."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    saved = []
    for i in range(count):
        taken_at = base + timedelta(days=i // days_per_group)
        saved.append((taken_at, store.save("default", _links(i % 3 + 1), is_synthetic=False, taken_at=taken_at)))
    return sorted(saved, reverse=True)


def test_latest_and_periodic_load_only_newest_snapshot_row(tmp_path):
    """Reading the newest snapshot must not pull every snapshot blob into Python."""
    path = tmp_path / "graph_events.db"
    GraphEventStore(path)  # maybe_save_periodic counts events in the shared db
    store = GraphSnapshotStore(path)
    newest_first = [snapshot_id for _taken_at, snapshot_id in _save_history(store, 25)]
    for i in range(3):  # newer rows in another notebook must not leak in
        store.save("work", _links(1), is_synthetic=False, taken_at=datetime(2027, 1, 1 + i, tzinfo=UTC))

    latest, loaded, blob_selects = _capture_snapshot_reads(store, lambda: store.latest("default"))
    assert latest is not None
    assert latest.snapshot_id == newest_first[0]
    assert loaded == [newest_first[0]]
    assert blob_selects
    assert all(" limit " in sql for sql in blob_selects), blob_selects

    result, loaded, blob_selects = _capture_snapshot_reads(
        store, lambda: store.maybe_save_periodic("default", _links(2), min_events_since_snapshot=50)
    )
    assert result["reason"] == "below-threshold"
    assert loaded == [newest_first[0]]
    assert blob_selects
    assert all(" limit " in sql for sql in blob_selects), blob_selects


def test_latest_skips_multiple_corrupt_newest_snapshots_among_many(tmp_path, monkeypatch):
    """Corrupt newest rows filling the first two reads still resolve to the newest
    valid snapshot, which also stays the periodic-checkpoint watermark."""
    import kg.graph_event_log as mod

    path = tmp_path / "graph_events.db"
    events = GraphEventStore(path)
    store = GraphSnapshotStore(path)
    history = _save_history(store, 25, days_per_group=3)
    # The first read takes one row, the second a fallback page: corrupt exactly
    # those so the valid row opens the third page. It shares taken_at with the
    # last corrupt row, so only the snapshot_id tie-break of the cursor finds it.
    edge = 1 + GraphSnapshotStore._FALLBACK_PAGE_SIZE
    assert history[edge - 1][0] == history[edge][0]
    corrupt, expected_id = [snapshot_id for _taken_at, snapshot_id in history[:edge]], history[edge][1]
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executemany(
            f"UPDATE {_SNAPSHOT_TABLE} SET links_json='not-json' WHERE snapshot_id=?",
            [(snapshot_id,) for snapshot_id in corrupt],
        )

    latest = store.latest("default")
    assert latest is not None
    assert latest.snapshot_id == expected_id

    # One event after the valid watermark but before every corrupt snapshot:
    # only the valid watermark counts it.
    event_at = latest.taken_at.replace(tzinfo=UTC) + timedelta(hours=12)
    monkeypatch.setattr(mod, "_now", lambda: event_at)
    events.append(
        event_id="e-after-valid",
        event_type="link_updated",
        link_id="L0",
        from_id="a",
        to_id="b",
        kind="shares_usage",
        source="auto",
        notebook_id="default",
        occurred_at=event_at,
    )
    result = store.maybe_save_periodic("default", _links(4), min_events_since_snapshot=1)
    assert result["saved"] is True
    assert result["reason"] == "event-threshold"
    assert result["events_since_snapshot"] == 1


def test_latest_returns_none_when_every_snapshot_is_corrupt(tmp_path):
    """The fallback walk must terminate (including on an exactly full last page)."""
    path = tmp_path / "graph_events.db"
    store = GraphSnapshotStore(path)
    _save_history(store, 1 + GraphSnapshotStore._FALLBACK_PAGE_SIZE)  # last page exactly full
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(f"UPDATE {_SNAPSHOT_TABLE} SET links_json='not-json'")

    assert store.latest("default") is None


def _index_columns(path) -> dict[str, list[str]]:
    with closing(sqlite3.connect(path)) as connection:
        names = [row[1] for row in connection.execute(f"PRAGMA index_list('{_SNAPSHOT_TABLE}')")]
        return {name: [col[2] for col in connection.execute(f"PRAGMA index_info('{name}')")] for name in names}


_LATEST_LOOKUP_COLUMNS = ["notebook_id", "taken_at", "snapshot_id"]


def _latest_lookup_index(path) -> str | None:
    return next((name for name, cols in _index_columns(path).items() if cols == _LATEST_LOOKUP_COLUMNS), None)


def test_snapshot_composite_index_exists_on_fresh_and_legacy_db(tmp_path):
    """The newest-per-notebook lookup needs (notebook_id, taken_at, snapshot_id),
    including on stores whose table predates the index (create_all skips them)."""
    fresh = tmp_path / "fresh.db"
    GraphSnapshotStore(fresh)
    assert _latest_lookup_index(fresh) is not None, _index_columns(fresh)

    legacy = tmp_path / "legacy.db"
    with closing(sqlite3.connect(legacy)) as connection, connection:
        connection.executescript(
            f"""
            CREATE TABLE {_SNAPSHOT_TABLE} (
                snapshot_id VARCHAR NOT NULL,
                notebook_id VARCHAR NOT NULL,
                taken_at DATETIME NOT NULL,
                link_count INTEGER NOT NULL,
                links_json VARCHAR NOT NULL,
                is_synthetic BOOLEAN NOT NULL,
                PRIMARY KEY (snapshot_id)
            );
            CREATE INDEX ix_{_SNAPSHOT_TABLE}_notebook_id ON {_SNAPSHOT_TABLE} (notebook_id);
            CREATE INDEX ix_{_SNAPSHOT_TABLE}_taken_at ON {_SNAPSHOT_TABLE} (taken_at);
            CREATE INDEX ix_{_SNAPSHOT_TABLE}_is_synthetic ON {_SNAPSHOT_TABLE} (is_synthetic);
            INSERT INTO {_SNAPSHOT_TABLE} VALUES
                ('legacy', 'default', '2026-01-01 00:00:00.000000', 0, '[]', 1);
            """
        )
    assert _latest_lookup_index(legacy) is None

    store = GraphSnapshotStore(legacy)
    index_name = _latest_lookup_index(legacy)
    assert index_name is not None, _index_columns(legacy)
    assert store.latest("default").snapshot_id == "legacy"

    captured: list[tuple[str, tuple]] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        if " ".join(statement.split()).lower().startswith("select"):
            captured.append((statement, parameters))

    sa_event.listen(store.engine, "before_cursor_execute", _before)
    try:
        store.latest("default")
    finally:
        sa_event.remove(store.engine, "before_cursor_execute", _before)
    assert len(captured) == 1, captured
    statement, parameters = captured[0]
    with closing(sqlite3.connect(legacy)) as connection:
        plan = [row[3] for row in connection.execute(f"EXPLAIN QUERY PLAN {statement}", parameters)]
    assert any(index_name in detail for detail in plan), plan
    assert not any("TEMP B-TREE" in detail for detail in plan), plan
