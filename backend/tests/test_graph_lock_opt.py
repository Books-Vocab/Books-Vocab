"""Tests for GraphStore lock contention optimisation.

Verifies:
1. _candidate_set exists for O(1) duplicate checks in add_candidate
2. Disk I/O (_flush_links/_flush_candidates) happens outside the lock
3. All write methods maintain correctness after the refactor
4. batch_* methods also write outside the lock
"""

from __future__ import annotations

import threading
import unittest.mock as mock

import pytest

from kg.graph import GraphStore, LinkKind


@pytest.fixture()
def store(tmp_path):
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
    )


# ---------------------------------------------------------------------------
# 1. _candidate_set O(1) structure
# ---------------------------------------------------------------------------

class TestCandidateSet:
    """GraphStore must maintain _candidate_set for O(1) duplicate detection."""

    def test_candidate_set_attribute_exists(self, store):
        assert hasattr(store, "_candidate_set"), (
            "GraphStore must expose _candidate_set: set[tuple[str,str]]"
        )

    def test_candidate_set_is_set(self, store):
        assert isinstance(store._candidate_set, set)

    def test_candidate_set_populated_on_add(self, store):
        store.add_candidate("a", "b", 0.9)
        assert ("a", "b") in store._candidate_set or ("b", "a") in store._candidate_set

    def test_candidate_set_prevents_duplicate(self, store):
        store.add_candidate("x", "y", 0.8)
        store.add_candidate("y", "x", 0.8)  # reverse order — same pair
        assert store.candidate_count() == 1

    def test_candidate_set_cleared_on_pop(self, store):
        store.add_candidate("c", "d", 0.7)
        store.pop_candidates()
        assert len(store._candidate_set) == 0

    def test_candidate_set_loaded_from_disk(self, tmp_path):
        """_candidate_set must be rebuilt when loading existing candidates file."""
        s1 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
        )
        s1.add_candidate("p", "q", 0.6)

        # Reload from same files
        s2 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
        )
        assert ("p", "q") in s2._candidate_set or ("q", "p") in s2._candidate_set

    def test_remove_candidates_for_updates_set(self, store):
        store.add_candidate("e", "f", 0.5)
        store.remove_candidates_for("e")
        assert ("e", "f") not in store._candidate_set
        assert ("f", "e") not in store._candidate_set

    def test_requeue_candidates_updates_set(self, store):
        store.add_candidate("g", "h", 0.5)
        candidates = store.pop_candidates()
        assert len(store._candidate_set) == 0
        store.requeue_candidates(candidates)
        assert ("g", "h") in store._candidate_set or ("h", "g") in store._candidate_set


# ---------------------------------------------------------------------------
# 2. Disk I/O outside lock
# ---------------------------------------------------------------------------

def _make_flush_spy(store: GraphStore, method_name: str):
    """Return (held_flags, patched_method).

    held_flags: list of bool, True if _lock was held when flush was called.
    Wraps the *instance* flush method so we can check _lock.locked().
    """
    held_flags: list[bool] = []
    orig = getattr(type(store), method_name)

    def spy(self_inner, *args, **kw):
        held_flags.append(self_inner._lock.locked())
        return orig(self_inner, *args, **kw)

    return held_flags, spy


class TestDiskWriteOutsideLock:
    """Flush helpers must NOT be called while _lock is held."""

    def test_add_link_writes_outside_lock(self, store):
        held_flags, spy = _make_flush_spy(store, "_flush_links")
        with mock.patch.object(type(store), "_flush_links", spy):
            store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        assert held_flags, "_flush_links was never called"
        assert not any(held_flags), f"_flush_links called while lock held: {held_flags}"

    def test_add_candidate_writes_outside_lock(self, store):
        held_flags, spy = _make_flush_spy(store, "_flush_candidates")
        with mock.patch.object(type(store), "_flush_candidates", spy):
            store.add_candidate("x", "y", 0.7)
        assert held_flags, "_flush_candidates was never called"
        assert not any(held_flags)

    def test_batch_add_links_writes_outside_lock(self, store):
        held_flags, spy = _make_flush_spy(store, "_flush_links")
        with mock.patch.object(type(store), "_flush_links", spy):
            store.batch_add_links([
                ("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r1"),
                ("c", "d", LinkKind.SHARES_USAGE, 0.8, "r2"),
            ])
        assert held_flags
        assert not any(held_flags)

    def test_batch_add_candidates_writes_outside_lock(self, store):
        held_flags, spy = _make_flush_spy(store, "_flush_candidates")
        with mock.patch.object(type(store), "_flush_candidates", spy):
            store.batch_add_candidates([("p", "q", 0.6), ("r", "s", 0.5)])
        assert held_flags
        assert not any(held_flags)

    def test_hide_link_writes_outside_lock(self, store):
        link = store.add_link("u", "v", LinkKind.CONTRASTS_WITH, 0.9, "r")
        held_flags, spy = _make_flush_spy(store, "_flush_links")
        with mock.patch.object(type(store), "_flush_links", spy):
            store.hide_link(link.id)
        assert held_flags
        assert not any(held_flags)

    def test_unhide_link_writes_outside_lock(self, store):
        link = store.add_link("u2", "v2", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hide_link(link.id)
        held_flags, spy = _make_flush_spy(store, "_flush_links")
        with mock.patch.object(type(store), "_flush_links", spy):
            store.unhide_link(link.id)
        assert held_flags
        assert not any(held_flags)

    def test_hard_delete_link_writes_outside_lock(self, store):
        link = store.add_link("m", "n", LinkKind.CONTRASTS_WITH, 0.9, "r")
        held_flags, spy = _make_flush_spy(store, "_flush_links")
        with mock.patch.object(type(store), "_flush_links", spy):
            store.hard_delete_link(link.id)
        assert held_flags
        assert not any(held_flags)


# ---------------------------------------------------------------------------
# 3. Correctness after refactor — data integrity
# ---------------------------------------------------------------------------

class TestCorrectnessAfterRefactor:
    """All write ops must produce the same observable results as before."""

    def test_add_link_persisted_to_disk(self, tmp_path):
        s1 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
        )
        s1.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "reason")

        s2 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
        )
        assert s2.find_link_between("a", "b") is not None

    def test_add_candidate_persisted(self, tmp_path):
        s1 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
        )
        s1.add_candidate("c", "d", 0.6)

        s2 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
        )
        assert s2.candidate_count() == 1

    def test_hide_link_persisted(self, tmp_path):
        s1 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
        )
        lk = s1.add_link("e", "f", LinkKind.SHARES_USAGE, 0.8, "r")
        s1.hide_link(lk.id)

        s2 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
        )
        found = s2.get_link(lk.id)
        assert found is not None and found.status == "hidden"

    def test_concurrent_add_link_all_written_to_disk(self, tmp_path):
        """After concurrent add_link, all links must be present when store is reloaded."""
        n = 20
        s1 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
        )
        barrier = threading.Barrier(n)
        errors: list[Exception] = []

        def worker(i):
            try:
                barrier.wait(timeout=5)
                s1.add_link(f"from_{i}", f"to_{i}", LinkKind.CONTRASTS_WITH, 0.9, f"r{i}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors

        s2 = GraphStore(
            links_path=tmp_path / "links.json",
            candidates_path=tmp_path / "candidates.json",
            blocked_path=tmp_path / "blocked.json",
        )
        assert len(list(s2.all_links())) == n
