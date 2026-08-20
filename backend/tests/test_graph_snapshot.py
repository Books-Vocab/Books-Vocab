"""GraphSnapshot 測試 — 圖譜整檔狀態週期 checkpoint。

event log 記逐筆 diff,snapshot 記某時點的完整 link 狀態。兩者合一即可重建任意時間點
的圖譜(從最近 snapshot 起,套用其後的 diff 事件),也是 event log 萬一被截斷時的安全網。
is_synthetic 區分遷移當下的初始合成 snapshot 與上線後真實週期 snapshot。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kg.graph_event_log import GraphEventStore, GraphSnapshotStore


def _links(n: int) -> list[dict]:
    return [
        {"id": f"L{i}", "from_id": f"a{i}", "to_id": f"b{i}", "kind": "shares_usage",
         "confidence": 0.5, "reason": "r", "created_at": "2026-04-01T00:00:00+00:00",
         "status": "active"}
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
    store.save("default", _links(1), is_synthetic=True,
               taken_at=datetime(2026, 1, 1, tzinfo=UTC))
    store.save("default", _links(2), is_synthetic=False,
               taken_at=datetime(2026, 2, 1, tzinfo=UTC))
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
    links = [{"id": "L0", "from_id": "a", "to_id": "b", "kind": "contrasts_with",
              "confidence": 0.9, "reason": "語意對比:嚴謹 vs 馬虎", "created_at": "2026-04-01T00:00:00+00:00",
              "status": "active"}]
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
