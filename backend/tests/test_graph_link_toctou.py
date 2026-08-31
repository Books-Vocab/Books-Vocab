"""Regression: add_link must dedup the same pair across store boundaries (TOCTOU).

create_manual_link does check-then-act: find_link_between (None) → judge.evaluate
(LLM, seconds, no lock held) → add_link. Two concurrent manual-link requests for
the same pair both see None, both reach add_link, and -- because add_link did not
re-check existence under _lock -- both inserted, yielding two active links for one
pair. The fix makes add_link idempotent: under _lock and the persisted link file
lock, if an active/hidden link for the pair already exists, return it instead of
inserting a duplicate.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from kg.graph import GraphStore, LinkKind


@pytest.fixture()
def store(tmp_path):
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
    )


def _active_links_for_pair(store, a, b):
    return [lk for lk in store.all_links() if lk.status == "active" and {lk.from_id, lk.to_id} == {a, b}]


def test_add_link_same_pair_is_idempotent(store):
    """Sequential add_link for the same pair must not create a duplicate.

    This models the check-then-act gap: the first add commits, then a second
    request (which read find_link_between == None before the first committed)
    calls add_link again for the same pair.
    """
    first = store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 1.0, "r1")
    second = store.add_link("card_a", "card_b", LinkKind.SHARES_USAGE, 1.0, "r2")

    actives = _active_links_for_pair(store, "card_a", "card_b")
    assert len(actives) == 1, f"expected 1 active link, got {len(actives)}"
    # Idempotent: returns the existing link, not a fresh duplicate.
    assert second.id == first.id


def test_add_link_idempotent_reversed_direction(store):
    """Dedup is bidirectional: (a,b) then (b,a) must collapse to one link."""
    first = store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 1.0, "r1")
    second = store.add_link("card_b", "card_a", LinkKind.CONTRASTS_WITH, 1.0, "r2")

    actives = _active_links_for_pair(store, "card_a", "card_b")
    assert len(actives) == 1
    assert second.id == first.id


def test_concurrent_add_link_same_pair_no_duplicate(store):
    """Two concurrent add_link for the SAME pair must yield exactly one link."""
    n_threads = 16
    barrier = threading.Barrier(n_threads)
    errors: list[Exception] = []

    def worker(i: int):
        try:
            barrier.wait(timeout=5)
            store.add_link("card_a", "card_b", LinkKind.CONTRASTS_WITH, 1.0, f"r{i}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Worker errors: {errors}"
    actives = _active_links_for_pair(store, "card_a", "card_b")
    assert len(actives) == 1, (
        f"TOCTOU: {n_threads} concurrent add_link produced {len(actives)} active links for one pair"
    )


def test_concurrent_add_link_across_instances_is_idempotent(tmp_path: Path):
    """Separate GraphStore instances must dedup the same persisted pair."""
    first = GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
    )
    second = GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
    )
    barrier = threading.Barrier(2)
    result_ids: list[str] = []
    errors: list[Exception] = []
    result_lock = threading.Lock()

    def add_link(graph: GraphStore) -> None:
        try:
            barrier.wait(timeout=5)
            link = graph.add_link(
                "card_a",
                "card_b",
                LinkKind.SHARES_USAGE,
                0.9,
                "cross-instance race",
            )
            with result_lock:
                result_ids.append(link.id)
        except Exception as exc:  # pragma: no cover - failure is asserted below
            with result_lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=add_link, args=(first,)),
        threading.Thread(target=add_link, args=(second,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert len(result_ids) == 2

    reloaded = GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
    )
    active_links = _active_links_for_pair(reloaded, "card_a", "card_b")
    assert len(active_links) == 1
    assert set(result_ids) == {active_links[0].id}
