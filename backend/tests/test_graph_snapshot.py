"""GraphSnapshot 測試 — 圖譜整檔狀態週期 checkpoint。

event log 記逐筆 diff,snapshot 記某時點的完整 link 狀態。兩者合一即可重建任意時間點
的圖譜(從最近 snapshot 起,套用其後的 diff 事件),也是 event log 萬一被截斷時的安全網。
is_synthetic 區分遷移當下的初始合成 snapshot 與上線後真實週期 snapshot。
"""

from __future__ import annotations

from datetime import UTC, datetime

from kg.graph_event_log import GraphSnapshotStore


def _links(n: int) -> list[dict]:
    return [
        {"id": f"L{i}", "from_id": f"a{i}", "to_id": f"b{i}", "kind": "shares_usage",
         "confidence": 0.5, "reason": "r", "created_at": "2026-04-01T00:00:00+00:00",
         "status": "active"}
        for i in range(n)
    ]


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


def test_persists_across_reopen(tmp_path):
    path = tmp_path / "g.db"
    store = GraphSnapshotStore(path)
    store.save("default", _links(4), is_synthetic=True)
    store.close()
    reopened = GraphSnapshotStore(path)
    assert reopened.latest("default").link_count == 4
