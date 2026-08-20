"""Test that GraphStore mutation methods are thread-safe."""

from __future__ import annotations

import json
import threading

import pytest

from kg.graph import GraphStore, LinkKind


@pytest.fixture()
def store(tmp_path):
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
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

    def test_concurrent_reads_during_writes_no_error(self, store, monkeypatch):
        """Read methods must hold _lock — reading while a writer mutates _links
        must not raise `dictionary changed size during iteration` (all_links /
        link_count) or KeyError (get_links_for / find_link_between).

        The writer's disk I/O is mocked out: the test targets in-memory
        concurrency safety (lock coverage), not fsync throughput.  Without this
        the 300 add_link calls would spend ~50 s rewriting links.json under
        contention — a test-infrastructure cost, not a product concern."""
        n = 300
        writer_done = threading.Event()
        errors: list[Exception] = []

        # Disable disk flush so the test exercises lock behaviour, not O(n²)
        # file-system contention.
        monkeypatch.setattr(store, "_flush_links", lambda _snap: None)

        def writer():
            try:
                for i in range(n):
                    store.add_link(
                        "hub", f"to_{i}", LinkKind.CONTRASTS_WITH, 0.9, f"r{i}"
                    )
            except Exception as exc:  # writer errors are a separate concern
                errors.append(exc)
            finally:
                writer_done.set()

        def reader():
            try:
                while not writer_done.is_set():
                    # Each of these iterates shared dicts/index sets that the
                    # writer is concurrently mutating.
                    list(store.all_links())
                    store.link_count()
                    store.get_links_for("hub")
                    store.find_link_between("hub", "to_0")
            except Exception as exc:
                errors.append(exc)

        readers = [threading.Thread(target=reader) for _ in range(2)]
        w = threading.Thread(target=writer)
        w.start()
        for r in readers:
            r.start()
        w.join(timeout=30)
        for r in readers:
            r.join(timeout=10)

        assert writer_done.is_set(), "writer did not finish within timeout"
        assert not errors, f"Concurrent read/write raised: {errors}"
        assert store.link_count() == n

    def test_all_links_returns_materialized_snapshot(self, store):
        """all_links() must return a concrete sequence (snapshot taken under the
        lock), not a lazy view over the live dict."""
        for i in range(5):
            store.add_link("a", f"b_{i}", LinkKind.SHARES_USAGE, 0.8, f"r{i}")
        # Materialized: mutating the store afterwards must not change the snapshot.
        before = len(store.all_links())
        snapshot = list(store.all_links())
        store.add_link("a", "b_new", LinkKind.SHARES_USAGE, 0.8, "rn")
        assert len(snapshot) == before
        assert len(list(store.all_links())) == before + 1

    def test_stale_link_snapshot_cannot_erase_newer_flush(
        self, store, monkeypatch
    ):
        """A delayed older flush must not overwrite a newer durable snapshot."""
        original_flush = store._flush_links
        first_flush_started = threading.Event()
        allow_first_flush = threading.Event()
        errors: list[Exception] = []

        def controlled_flush(snapshot):
            if len(snapshot) == 1:
                first_flush_started.set()
                if not allow_first_flush.wait(timeout=5):
                    raise TimeoutError("timed out waiting to release first flush")
            original_flush(snapshot)

        monkeypatch.setattr(store, "_flush_links", controlled_flush)

        def add_link(from_id: str, to_id: str):
            try:
                store.add_link(from_id, to_id, LinkKind.CONTRASTS_WITH, 0.9, "race")
            except Exception as exc:  # pragma: no cover - assertion below reports it
                errors.append(exc)

        first = threading.Thread(target=add_link, args=("a", "b"))
        second = threading.Thread(target=add_link, args=("c", "d"))
        first.start()
        assert first_flush_started.wait(timeout=5)
        second.start()
        second.join(timeout=10)
        allow_first_flush.set()
        first.join(timeout=10)

        assert not errors, f"Worker errors: {errors}"
        assert not first.is_alive() and not second.is_alive()
        assert len(store._links) == 2

        durable = json.loads(store.links_path.read_text())
        reloaded = GraphStore(
            links_path=store.links_path,
            candidates_path=store.candidates_path,
            blocked_path=store.blocked_path,
        )
        expected_ids = set(store._links)
        assert {row["id"] for row in durable} == expected_ids
        assert {link.id for link in reloaded.all_links()} == expected_ids
