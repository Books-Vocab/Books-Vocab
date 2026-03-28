"""Test that GraphStore mutation methods are thread-safe."""

from __future__ import annotations

import threading

import pytest

from kg.graph import GraphStore, LinkKind


@pytest.fixture()
def store(tmp_path):
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
    )


class TestGraphStoreLocking:
    """GraphStore must use a lock to serialise mutations."""

    def test_has_lock_attribute(self, store):
        assert hasattr(store, "_lock"), "GraphStore must have a _lock attribute"
        assert isinstance(store._lock, type(threading.Lock()))

    def test_concurrent_add_link_no_data_loss(self, store):
        """Parallel add_link calls must not lose entries."""
        n_threads = 20
        barrier = threading.Barrier(n_threads)
        errors: list[Exception] = []

        def worker(i: int):
            try:
                barrier.wait(timeout=5)
                store.add_link(
                    f"from_{i}", f"to_{i}", LinkKind.CONTRASTS_WITH, 0.9, f"r{i}"
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Worker errors: {errors}"
        assert len(store._links) == n_threads

    def test_concurrent_add_candidate_no_data_loss(self, store):
        """Parallel add_candidate calls must not lose entries."""
        n_threads = 20
        barrier = threading.Barrier(n_threads)
        errors: list[Exception] = []

        def worker(i: int):
            try:
                barrier.wait(timeout=5)
                store.add_candidate(f"from_{i}", f"to_{i}", 0.5 + i * 0.01)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Worker errors: {errors}"
        assert store.candidate_count() == n_threads

    def test_concurrent_deprecate_and_add(self, store):
        """Deprecate and add running concurrently must not corrupt state."""
        # Pre-populate
        for i in range(10):
            store.add_link("shared", f"to_{i}", LinkKind.CONTRASTS_WITH, 0.9, f"r{i}")

        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def deprecator():
            try:
                barrier.wait(timeout=5)
                store.deprecate_links_for("shared")
            except Exception as exc:
                errors.append(exc)

        def adder():
            try:
                barrier.wait(timeout=5)
                store.add_link("new_a", "new_b", LinkKind.SHARES_USAGE, 0.8, "new")
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=deprecator)
        t2 = threading.Thread(target=adder)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors
        # The new link must exist
        assert store.has_link("new_a", "new_b")
