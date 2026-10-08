"""Link mutations reconcile only the mutated pair, in O(L) (#2246)."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from kg.graph import GraphStore, LinkKind


def _new_store(tmp_path) -> GraphStore:
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
    )


def _seed(store: GraphStore, n: int):
    for i in range(n):
        store.add_link(f"u{i}a", f"u{i}b", LinkKind.SHARES_USAGE, 0.5, "x")
    return store.add_link("m1", "m2", LinkKind.CONTRASTS_WITH, 0.9, "target")


def _spy_pairs(store: GraphStore, monkeypatch) -> list[set]:
    seen: list[set] = []
    original = store._reconcile_persisted_pairs

    def spy(snapshot, pairs, **kw):
        seen.append(set(pairs))
        return original(snapshot, pairs, **kw)

    monkeypatch.setattr(store, "_reconcile_persisted_pairs", spy)
    return seen


MUTATIONS: dict[str, Callable[[GraphStore, str], object]] = {
    "update": lambda s, i: s.update_link(i, confidence=0.7),
    "hide": lambda s, i: s.hide_link(i),
    "unhide": lambda s, i: s.unhide_link(i),
    "hard_delete": lambda s, i: s.hard_delete_link(i),
}


@pytest.mark.parametrize("name", list(MUTATIONS))
def test_mutation_reconciles_only_mutated_pair(tmp_path, monkeypatch, name):
    store = _new_store(tmp_path)
    target = _seed(store, 50)
    seen = _spy_pairs(store, monkeypatch)
    MUTATIONS[name](store, target.id)
    assert seen, "reconcile never ran"
    assert all(pairs == {("m1", "m2")} for pairs in seen), seen


def test_hide_normalize_calls_are_linear(tmp_path, monkeypatch):
    store = _new_store(tmp_path)
    target = _seed(store, 400)
    total = len(store._links)
    calls = 0
    original = GraphStore._normalize_pair

    def counting(a, b):
        nonlocal calls
        calls += 1
        return original(a, b)

    monkeypatch.setattr(GraphStore, "_normalize_pair", staticmethod(counting))
    store.hide_link(target.id)
    assert calls <= 8 * total, (calls, total)


def test_foreign_duplicate_of_mutated_pair_still_collapsed(tmp_path):
    api = _new_store(tmp_path)
    target = api.add_link("a", "b", LinkKind.SHARES_USAGE, 0.5, "x")
    path = tmp_path / "links.json"
    rows = json.loads(path.read_text())
    dup = dict(rows[0], id="foreign-dup", from_id="b", to_id="a")
    path.write_text(json.dumps([*rows, dup]))

    api.update_link(target.id, confidence=0.8)

    on_disk = json.loads(path.read_text())
    assert [r["id"] for r in on_disk if {r["from_id"], r["to_id"]} == {"a", "b"}] == [target.id]
