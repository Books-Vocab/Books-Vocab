from __future__ import annotations

import json
from pathlib import Path

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
