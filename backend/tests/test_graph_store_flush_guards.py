from __future__ import annotations

import json
from pathlib import Path

import pytest

from kg.graph.models import LinkKind
from kg.graph.store import GraphStore


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    links = tmp_path / "links.json"
    cands = tmp_path / "candidates.json"
    blocked = tmp_path / "blocked.json"
    links.write_text("[]", encoding="utf-8")
    cands.write_text("[]", encoding="utf-8")
    return links, cands, blocked


def _pairs(path: Path) -> set[tuple[str, str]]:
    return {tuple(p) for p in json.loads(path.read_text(encoding="utf-8"))}


def test_out_of_order_blocked_flush_keeps_newer_pair(tmp_path: Path) -> None:
    links, cands, blocked = _paths(tmp_path)
    store = GraphStore(links, cands, blocked_path=blocked)
    p, q = ("a", "b"), ("c", "d")
    with store._lock:
        store._blocked_pairs.add(p)
        store._known_blocked_pairs.add(p)
        store._touch_blocked((p,))
        older = store._blocked_to_serializable()
        store._blocked_pairs.add(q)
        store._known_blocked_pairs.add(q)
        store._touch_blocked((q,))
        newer = store._blocked_to_serializable()

    store._flush_blocked(newer)
    store._flush_blocked(older)

    assert _pairs(blocked) == {p, q}
    assert store.is_blocked(*q)
    fresh = GraphStore(links, cands, blocked_path=blocked)
    assert fresh.is_blocked(*p) and fresh.is_blocked(*q)


def _legacy_rows() -> list[dict]:
    base = {
        "confidence": 0.8,
        "reason": "r",
        "created_at": "2026-01-01T00:00:00Z",
    }
    return [
        {**base, "id": "rej", "from_id": "a", "to_id": "b", "kind": "shares_usage", "status": "rejected"},
        {**base, "id": "conf", "from_id": "c", "to_id": "d", "kind": "confusable", "status": "active"},
    ]


def test_migrated_legacy_rows_are_removed_from_disk(tmp_path: Path) -> None:
    links, cands, blocked = _paths(tmp_path)
    links.write_text(json.dumps(_legacy_rows()), encoding="utf-8")

    GraphStore(links, cands, blocked_path=blocked)
    GraphStore(links, cands, blocked_path=blocked)

    assert json.loads(links.read_text(encoding="utf-8")) == []


def test_unblocked_migrated_pair_is_not_reblocked_by_fresh_store(tmp_path: Path) -> None:
    links, cands, blocked = _paths(tmp_path)
    links.write_text(json.dumps(_legacy_rows()), encoding="utf-8")

    store = GraphStore(links, cands, blocked_path=blocked)
    assert store.is_blocked("a", "b")
    store.unblock_pair("a", "b")

    fresh = GraphStore(links, cands, blocked_path=blocked)
    assert not fresh.is_blocked("a", "b")


def _linked_store(tmp_path: Path) -> GraphStore:
    links, cands, blocked = _paths(tmp_path)
    store = GraphStore(links, cands, blocked_path=blocked)
    store.add_link("a", "b", LinkKind.SHARES_USAGE, 0.8, "r")
    return store


def test_cleanup_for_card_failure_leaves_links_active(tmp_path: Path, monkeypatch) -> None:
    """#2690: 後續步驟失敗時,已 deprecate 的 link 必須回滾。"""
    store = _linked_store(tmp_path)

    def boom(card_id: str) -> None:
        raise OSError("blocked write failed")

    monkeypatch.setattr(store, "remove_blocked_pairs_for", boom)
    with pytest.raises(OSError):
        store.cleanup_for_card("a", remove_blocked=True, source="manual")
    assert [lk.status for lk in store.all_links()] == ["active"]
    assert len(store.get_links_for("a")) == 1
    fresh = GraphStore(tmp_path / "links.json", tmp_path / "candidates.json", blocked_path=tmp_path / "blocked.json")
    assert [lk.status for lk in fresh.all_links()] == ["active"]


def test_hard_delete_link_blocked_flush_failure_is_retryable(tmp_path: Path, monkeypatch) -> None:
    """#2690: blocked 寫入失敗不得讓 link 先消失;重試要成功且 block 落盤。"""
    store = _linked_store(tmp_path)
    link_id = store.all_links()[0].id
    real = store._flush_blocked
    calls = {"n": 0}

    def flaky(snapshot):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real(snapshot)

    monkeypatch.setattr(store, "_flush_blocked", flaky)
    with pytest.raises(OSError):
        store.hard_delete_link(link_id)
    assert store.get_link(link_id) is not None
    assert not store.is_blocked("a", "b")
    assert store.hard_delete_link(link_id) == ("a", "b")
    assert store.get_link(link_id) is None
    assert _pairs(tmp_path / "blocked.json") == {("a", "b")}


def test_update_link_invalid_input_leaves_link_unchanged(tmp_path: Path) -> None:
    """#2690: 壞 key / 超界 confidence 須在任何 setattr 之前拒絕,且不 emit。"""
    store = _linked_store(tmp_path)
    link_id = store.all_links()[0].id
    emitted: list[str] = []
    store._emit_graph_event = lambda event_type, **kw: emitted.append(event_type)  # type: ignore[method-assign]
    with pytest.raises(ValueError):
        store.update_link(link_id, status="hidden", bogus=1)
    with pytest.raises(ValueError):
        store.update_link(link_id, status="hidden", confidence=1.5)
    lk = store.get_link(link_id)
    assert (lk.status, lk.confidence) == ("active", 0.8)
    assert emitted == []
