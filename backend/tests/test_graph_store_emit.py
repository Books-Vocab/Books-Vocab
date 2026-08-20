"""GraphStore → graph_event_log emit 測試(Phase 6)。

Store 層是圖譜變動的唯一 100% 攔截點(pipeline AI 回寫不經 sync handler),故真實
變動歷史在此 emit。每個 mutation 方法成功改檔後 append 一筆 diff 事件(is_synthetic=
False,與合成過去區隔);event_store=None 時完全 no-op(既有用法零影響);emit 失敗
不可炸掉圖譜寫入(帳本是研究料,不是寫入關鍵路徑)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kg.graph.models import LinkKind
from kg.graph.store import GraphStore
from kg.graph_event_log import GraphEventStore, GraphEventType, GraphSnapshotStore


def _register_store_cleanup(
    request: pytest.FixtureRequest,
    gs: GraphStore,
    ev: GraphEventStore | None,
    snap: GraphSnapshotStore | None,
) -> None:
    def cleanup() -> None:
        if ev is not None:
            ev.close()
        if snap is not None:
            snap.close()
        gs._event_store = None
        gs._snapshot_store = None

    request.addfinalizer(cleanup)


def _store(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    with_events: bool = True,
) -> tuple[GraphStore, GraphEventStore | None]:
    ev = GraphEventStore(tmp_path / "graph_events.db") if with_events else None
    snap = GraphSnapshotStore(tmp_path / "graph_events.db") if with_events else None
    gs = GraphStore(
        links_path=tmp_path / "graph_default.json",
        candidates_path=tmp_path / "candidates_default.json",
        blocked_path=tmp_path / "blocked_default.json",
        event_store=ev,
        snapshot_store=snap,
        event_notebook_id="default",
    )
    _register_store_cleanup(request, gs, ev, snap)
    return gs, ev


def test_add_link_emits_link_added(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    link = gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.8, "r")
    events = ev.all()
    assert len(events) == 1
    e = events[0]
    assert e.event_type == GraphEventType.LINK_ADDED
    assert e.link_id == link.id
    assert e.confidence_before is None and e.confidence_after == 0.8
    assert e.status_before is None and e.status_after == "active"
    assert e.is_synthetic is False
    assert e.source == "auto"
    assert e.notebook_id == "default"
    snapshot_store = GraphSnapshotStore(tmp_path / "graph_events.db")
    try:
        snap = snapshot_store.latest("default")
    finally:
        snapshot_store.close()
    assert snap is not None
    assert snap.is_synthetic is False
    assert snap.link_count == 1


def test_add_link_source_override(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.8, "r", source="manual")
    assert ev.all()[0].source == "manual"


def test_duplicate_add_does_not_emit(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.8, "r")
    gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.9, "r2")  # dedup → 既有,不應再 emit
    assert len(ev.all()) == 1


def test_batch_add_emits_one_per_created(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    gs.batch_add_links([
        ("a", "b", LinkKind.SHARES_USAGE, 0.7, "r1"),
        ("c", "d", LinkKind.CONTRASTS_WITH, 0.6, "r2"),
        ("a", "b", LinkKind.SHARES_USAGE, 0.5, "dup"),  # dedup,不 emit
    ])
    added = ev.query(event_type=GraphEventType.LINK_ADDED)
    assert len(added) == 2


def test_update_link_emits_diff(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    link = gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.5, "r")
    gs.update_link(link.id, confidence=0.95)
    upd = ev.query(event_type=GraphEventType.LINK_UPDATED)
    assert len(upd) == 1
    assert upd[0].confidence_before == 0.5
    assert upd[0].confidence_after == 0.95
    assert upd[0].status_before == "active"
    assert upd[0].status_after == "active"


def test_hide_and_unhide_emit(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    link = gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.5, "r")
    gs.hide_link(link.id)
    gs.unhide_link(link.id)
    hidden = ev.query(event_type=GraphEventType.LINK_HIDDEN)
    unhidden = ev.query(event_type=GraphEventType.LINK_UNHIDDEN)
    assert len(hidden) == 1 and hidden[0].status_before == "active" and hidden[0].status_after == "hidden"
    assert len(unhidden) == 1 and unhidden[0].status_before == "hidden" and unhidden[0].status_after == "active"


def test_hard_delete_emits_link_deleted(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    link = gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.5, "r")
    gs.hard_delete_link(link.id)
    deleted = ev.query(event_type=GraphEventType.LINK_DELETED)
    assert len(deleted) == 1
    assert deleted[0].status_before == "active"
    assert deleted[0].link_id == link.id


def test_deprecate_links_for_emits_per_link(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    l1 = gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.5, "r")
    l2 = gs.add_link("a", "c", LinkKind.SHARES_USAGE, 0.6, "r")
    gs.deprecate_links_for("a")
    dep = ev.query(event_type=GraphEventType.LINK_DEPRECATED)
    assert {e.link_id for e in dep} == {l1.id, l2.id}
    assert all(e.status_before == "active" and e.status_after == "deprecated" for e in dep)
    assert all(e.source == "auto" for e in dep)


class _FakeCard:
    def __init__(self, alive: bool = True) -> None:
        self.is_deleted = not alive
        self.is_archived = False


class _FakeCardsStore:
    """restore_links_for 只用 .get(other_id).is_deleted/is_archived。"""

    def get(self, _card_id: str):  # noqa: ANN001
        return _FakeCard(alive=True)


def test_add_link_emits_reason(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.8, "因為同詞根")
    assert ev.all()[0].reason == "因為同詞根"


def test_batch_add_emits_reason_per_link(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    gs.batch_add_links([
        ("a", "b", LinkKind.SHARES_USAGE, 0.7, "r1"),
        ("c", "d", LinkKind.CONTRASTS_WITH, 0.6, "r2"),
    ])
    reasons = {e.link_id: e.reason for e in ev.query(event_type=GraphEventType.LINK_ADDED)}
    assert set(reasons.values()) == {"r1", "r2"}


def test_update_link_emits_new_reason(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    link = gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.5, "old")
    gs.update_link(link.id, reason="new reason")
    upd = ev.query(event_type=GraphEventType.LINK_UPDATED)
    assert len(upd) == 1 and upd[0].reason == "new reason"


def test_restore_links_for_emits_link_restored(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    link = gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.5, "r")
    gs.deprecate_links_for("a")
    restored = gs.restore_links_for("a", _FakeCardsStore(), source="manual")
    assert restored == 1
    ev_restored = ev.query(event_type=GraphEventType.LINK_RESTORED)
    assert len(ev_restored) == 1
    e = ev_restored[0]
    assert e.link_id == link.id
    assert e.status_before == "deprecated" and e.status_after == "active"
    assert e.source == "manual"
    # 不得再用 link_unhidden 混淆 deprecated→active
    assert ev.query(event_type=GraphEventType.LINK_UNHIDDEN) == []


def test_cleanup_for_card_source_propagates(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.5, "r")
    gs.cleanup_for_card("a", source="manual")
    dep = ev.query(event_type=GraphEventType.LINK_DEPRECATED)
    assert len(dep) == 1 and dep[0].source == "manual"


def test_no_event_store_is_silent_noop(tmp_path, request):
    gs, ev = _store(tmp_path, request, with_events=False)
    link = gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.8, "r")
    gs.update_link(link.id, confidence=0.9)
    gs.hide_link(link.id)
    gs.hard_delete_link(link.id)  # 不得拋例外
    assert ev is None


def test_emit_failure_does_not_break_mutation(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    ev.close()  # 關掉 store → append 會炸;mutation 仍須成功
    link = gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.8, "r")
    assert link.id in {lk.id for lk in gs.all_links()}  # 圖譜寫入未受影響


def test_real_events_are_not_synthetic(tmp_path, request):
    gs, ev = _store(tmp_path, request)
    gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.8, "r")
    assert ev.query(synthetic=True) == []
    assert len(ev.query(synthetic=False)) == 1


class _CountingStore(GraphEventStore):
    """記錄 insert_many 被呼叫幾次,驗證 batch 操作只開一筆交易。"""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.insert_many_calls = 0

    def insert_many(self, drafts):  # noqa: ANN001
        self.insert_many_calls += 1
        return super().insert_many(drafts)


class _CountingSnapshotStore(GraphSnapshotStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.maybe_save_calls = 0

    def maybe_save_periodic(self, notebook_id, links, *, min_events_since_snapshot=None):  # noqa: ANN001
        self.maybe_save_calls += 1
        return super().maybe_save_periodic(
            notebook_id, links, min_events_since_snapshot=min_events_since_snapshot
        )


def test_batch_add_emits_single_transaction(tmp_path, request):
    ev = _CountingStore(tmp_path / "graph_events.db")
    snap = _CountingSnapshotStore(tmp_path / "graph_events.db")
    gs = GraphStore(
        links_path=tmp_path / "graph_default.json",
        candidates_path=tmp_path / "candidates_default.json",
        blocked_path=tmp_path / "blocked_default.json",
        event_store=ev, snapshot_store=snap, event_notebook_id="default",
    )
    _register_store_cleanup(request, gs, ev, snap)
    gs.batch_add_links([
        ("a", "b", LinkKind.SHARES_USAGE, 0.7, "r1"),
        ("c", "d", LinkKind.CONTRASTS_WITH, 0.6, "r2"),
        ("e", "f", LinkKind.SHARES_USAGE, 0.5, "r3"),
    ])
    assert ev.insert_many_calls == 1  # 不是逐 link 一筆交易
    assert snap.maybe_save_calls == 1
    assert len(ev.query(event_type=GraphEventType.LINK_ADDED)) == 3


def test_deprecate_emits_single_transaction(tmp_path, request):
    ev = _CountingStore(tmp_path / "graph_events.db")
    snap = _CountingSnapshotStore(tmp_path / "graph_events.db")
    gs = GraphStore(
        links_path=tmp_path / "graph_default.json",
        candidates_path=tmp_path / "candidates_default.json",
        blocked_path=tmp_path / "blocked_default.json",
        event_store=ev, snapshot_store=snap, event_notebook_id="default",
    )
    _register_store_cleanup(request, gs, ev, snap)
    gs.batch_add_links([
        ("a", "b", LinkKind.SHARES_USAGE, 0.7, "r1"),
        ("a", "c", LinkKind.SHARES_USAGE, 0.6, "r2"),
    ])
    before = ev.insert_many_calls
    snap_before = snap.maybe_save_calls
    gs.deprecate_links_for("a")
    assert ev.insert_many_calls == before + 1  # 兩條 deprecate 共一筆交易
    assert snap.maybe_save_calls == snap_before + 1
    assert len(ev.query(event_type=GraphEventType.LINK_DEPRECATED)) == 2


def test_event_store_provider_resolved_per_emit_survives_eviction(tmp_path, request):
    """GraphStore 透過 provider 取 event_store,故快取逐出後重建仍 emit 到 live store。"""
    db = tmp_path / "graph_events.db"
    holder = {"store": GraphEventStore(db)}
    gs = GraphStore(
        links_path=tmp_path / "graph_default.json",
        candidates_path=tmp_path / "candidates_default.json",
        blocked_path=tmp_path / "blocked_default.json",
        event_store_provider=lambda: holder["store"],
        event_notebook_id="default",
    )

    def cleanup() -> None:
        holder["store"].close()

    request.addfinalizer(cleanup)
    gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.8, "r")
    # 模擬 LRU 逐出:舊 store 關閉並由 cache 重建為新實例(同檔)
    holder["store"].close()
    holder["store"] = GraphEventStore(db)
    gs.add_link("c", "d", LinkKind.SHARES_USAGE, 0.7, "r2")  # 不得拋例外
    assert len(holder["store"].query(event_type=GraphEventType.LINK_ADDED)) == 2


def test_raising_provider_does_not_break_mutation(tmp_path):
    """provider 自己拋(開 SQLite 失敗)也不得打斷圖譜寫入。"""
    def _boom():
        raise RuntimeError("cannot open event store")

    gs = GraphStore(
        links_path=tmp_path / "graph_default.json",
        candidates_path=tmp_path / "candidates_default.json",
        blocked_path=tmp_path / "blocked_default.json",
        event_store_provider=_boom, event_notebook_id="default",
    )
    link = gs.add_link("a", "b", LinkKind.SHARES_USAGE, 0.8, "r")  # 不得拋例外
    assert link.id in {lk.id for lk in gs.all_links()}
