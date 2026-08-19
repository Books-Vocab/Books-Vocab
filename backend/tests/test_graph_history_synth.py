"""graph_history_synth 單元測試 — 從圖譜終態 link 反推合成生命史的護欄。

圖譜檔(graph_{nb}.json)只存每條 link 的「當前態」(id/from/to/kind/confidence/
reason/created_at/status),沒有「怎麼變成這樣」的逐步歷史。要讓 graph_event_log 有
回溯料,必須把終態**確定式**展開成生命史事件:每條 link 至少一筆 link_added(錨定
created_at);終態為 hidden/deprecated 者再補一筆對應 transition。全部 is_synthetic=True、
source=synth、event_id 依 link.id+序號穩定 → 重跑經 store 去重而冪等。

刻意最小化:我們只知道終態 confidence,不偽造 confidence 演進斜坡(無依據);只還原
status 生命線(born active → 終態),這是從終態能誠實重建的範圍。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kg.graph.models import GraphLink, LinkKind
from kg.graph_event_log import GraphEventStore, GraphEventType
from kg.graph_history_synth import synthesize_graph_history, synthesize_graph_history_many


def _link(
    *,
    link_id: str = "lk1",
    from_id: str = "cardA",
    to_id: str = "cardB",
    kind: LinkKind = LinkKind.SHARES_USAGE,
    confidence: float = 0.82,
    reason: str = "both used in formal register",
    created_at: datetime | None = None,
    status: str = "active",
) -> GraphLink:
    return GraphLink(
        id=link_id,
        from_id=from_id,
        to_id=to_id,
        kind=kind,
        confidence=confidence,
        reason=reason,
        created_at=created_at or datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
        status=status,  # type: ignore[arg-type]
    )


@pytest.fixture(autouse=True)
def _graph_event_stores_are_closed(monkeypatch):
    stores = []
    closed = set()
    real_init = GraphEventStore.__init__
    real_close = GraphEventStore.close

    def track_init(store, path):
        real_init(store, path)
        stores.append(store)

    def track_close(store):
        real_close(store)
        closed.add(id(store))

    monkeypatch.setattr(GraphEventStore, "__init__", track_init)
    monkeypatch.setattr(GraphEventStore, "close", track_close)
    yield
    assert all(id(store) in closed for store in stores)


def test_active_link_yields_single_add_event():
    events = synthesize_graph_history(_link(status="active"), notebook_id="default")
    assert len(events) == 1
    e = events[0]
    assert e.event_type == GraphEventType.LINK_ADDED
    assert e.status_before is None
    assert e.status_after == "active"
    assert e.confidence_before is None
    assert e.confidence_after == 0.82
    assert e.is_synthetic is True
    assert e.source == "synth"


def test_add_event_carries_link_identity_and_anchor_time():
    born = datetime(2026, 3, 15, 12, 30, tzinfo=UTC)
    e = synthesize_graph_history(
        _link(link_id="L9", from_id="X", to_id="Y", kind=LinkKind.CONTRASTS_WITH,
              created_at=born, reason="opposite valence"),
        notebook_id="nbk",
    )[0]
    assert e.event_id == "synth-L9-0"
    assert e.link_id == "L9"
    assert e.from_id == "X"
    assert e.to_id == "Y"
    assert e.kind == "contrasts_with"
    assert e.reason == "opposite valence"
    assert e.notebook_id == "nbk"
    assert e.occurred_at == born


def test_hidden_link_yields_add_then_hide():
    events = synthesize_graph_history(_link(status="hidden"), notebook_id="default")
    assert [e.event_type for e in events] == [
        GraphEventType.LINK_ADDED,
        GraphEventType.LINK_HIDDEN,
    ]
    add, hide = events
    assert add.status_after == "active"
    assert hide.status_before == "active"
    assert hide.status_after == "hidden"
    assert hide.event_id == "synth-lk1-1"
    assert hide.is_synthetic is True
    assert hide.reason is None  # 終態無從得知隱藏理由,不沿用建立理由


def test_deprecated_link_yields_add_then_deprecate():
    events = synthesize_graph_history(_link(status="deprecated"), notebook_id="default")
    assert [e.event_type for e in events] == [
        GraphEventType.LINK_ADDED,
        GraphEventType.LINK_DEPRECATED,
    ]
    assert events[1].status_before == "active"
    assert events[1].status_after == "deprecated"


def test_candidate_link_is_born_candidate_with_no_transition():
    events = synthesize_graph_history(_link(status="candidate"), notebook_id="default")
    assert len(events) == 1
    assert events[0].status_after == "candidate"


def test_transition_occurs_at_or_after_birth_and_is_distinct():
    events = synthesize_graph_history(_link(status="hidden"), notebook_id="default")
    assert events[1].occurred_at >= events[0].occurred_at
    assert events[0].event_id != events[1].event_id


def test_naive_created_at_is_normalized_to_utc():
    # 圖譜檔可能存 naive created_at;合成須產 tz-aware 供 store 接收。
    e = synthesize_graph_history(
        _link(created_at=datetime(2026, 4, 1, 9, 0)), notebook_id="default"
    )[0]
    assert e.occurred_at.tzinfo is not None


def test_deterministic_across_calls():
    link = _link(status="hidden")
    a = synthesize_graph_history(link, notebook_id="default")
    b = synthesize_graph_history(link, notebook_id="default")
    assert [(e.event_id, e.event_type, e.status_after) for e in a] == [
        (e.event_id, e.event_type, e.status_after) for e in b
    ]


def test_many_flattens_all_link_histories():
    links = [
        _link(link_id="a", status="active"),
        _link(link_id="b", status="hidden"),
        _link(link_id="c", status="deprecated"),
    ]
    events = synthesize_graph_history_many(links, notebook_id="default")
    assert len(events) == 1 + 2 + 2  # active=1, hidden=2, deprecated=2


def test_round_trips_through_graph_event_store(tmp_path):
    store = GraphEventStore(tmp_path / "graph_events.db")
    try:
        links = [_link(link_id="a", status="active"), _link(link_id="b", status="hidden")]
        res = store.insert_many(synthesize_graph_history_many(links, notebook_id="default"))
        assert res["inserted"] == 3
        synthetic = store.query(synthetic=True)
        assert len(synthetic) == 3
        assert all(e.is_synthetic for e in synthetic)
    finally:
        store.close()


def test_re_synth_and_reinsert_is_idempotent(tmp_path):
    store = GraphEventStore(tmp_path / "graph_events.db")
    try:
        link = _link(link_id="dup", status="deprecated")
        first = store.insert_many(synthesize_graph_history(link, notebook_id="default"))
        second = store.insert_many(synthesize_graph_history(link, notebook_id="default"))
        assert first["inserted"] == 2
        assert second["inserted"] == 0
        assert second["skipped"] == 2
    finally:
        store.close()
