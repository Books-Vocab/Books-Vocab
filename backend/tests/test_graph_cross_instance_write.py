"""Cross-instance lost-update regression tests for GraphStore.

Two GraphStore instances pointing at the *same* files (e.g. pipeline run +
API request after an LRU eviction, or two uvicorn workers) each hold an
independent in-memory ``_links`` snapshot and an independent ``threading.Lock``.

A whole-file flush from in-memory state is *destructive*: if instance B was
constructed before instance A added a link, B's flush overwrites A's link
with B's stale snapshot. The fix makes flushes additive across instances by
re-reading the on-disk file under a process-level ``fcntl`` file lock and
merging before writing.
"""

from __future__ import annotations

import json
import threading

import pytest

from kg.graph import GraphStore, LinkKind


def _new_store(tmp_path):
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
    )


class TestCrossInstanceLinks:
    """Two independent GraphStore instances must not lose each other's links."""

    def test_sequential_two_instances_no_lost_update(self, tmp_path):
        """B constructed first, A writes, then B writes: A's link must survive."""
        a = _new_store(tmp_path)
        b = _new_store(tmp_path)  # B's snapshot is empty at this point

        link_a = a.add_link("a_from", "a_to", LinkKind.CONTRASTS_WITH, 0.9, "ra")
        link_b = b.add_link("b_from", "b_to", LinkKind.SHARES_USAGE, 0.8, "rb")

        # Reload from disk: both links must be present.
        reloaded = _new_store(tmp_path)
        ids = {lk.id for lk in reloaded.all_links()}
        assert link_a.id in ids, "link from instance A was lost (overwritten by B)"
        assert link_b.id in ids, "link from instance B was lost"

    def test_interleaved_two_instances_no_lost_update(self, tmp_path):
        """Concurrent writes across two instances: every link must survive."""
        a = _new_store(tmp_path)
        b = _new_store(tmp_path)
        n = 30
        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def writer(store: GraphStore, prefix: str):
            try:
                barrier.wait(timeout=5)
                for i in range(n):
                    store.add_link(
                        f"{prefix}_from_{i}", f"{prefix}_to_{i}",
                        LinkKind.CONTRASTS_WITH, 0.9, f"{prefix}{i}",
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        t1 = threading.Thread(target=writer, args=(a, "A"))
        t2 = threading.Thread(target=writer, args=(b, "B"))
        t1.start()
        t2.start()
        t1.join(timeout=20)
        t2.join(timeout=20)

        assert not errors, f"writer errors: {errors}"

        reloaded = _new_store(tmp_path)
        ids = {lk.id for lk in reloaded.all_links()}
        assert len(ids) == 2 * n, (
            f"expected {2 * n} links on disk, found {len(ids)} "
            "-- cross-instance lost update"
        )

    def test_blocked_pairs_not_lost_across_instances(self, tmp_path):
        """hard_delete on one instance must not be erased by another's flush."""
        a = _new_store(tmp_path)
        b = _new_store(tmp_path)

        lk = a.add_link("x", "y", LinkKind.CONTRASTS_WITH, 0.9, "r")
        a.hard_delete_link(lk.id)  # adds (x, y) to blocked pairs on disk

        # B (stale, no blocked pairs) writes an unrelated link.
        b.add_link("p", "q", LinkKind.SHARES_USAGE, 0.8, "r2")

        reloaded = _new_store(tmp_path)
        assert reloaded.is_blocked("x", "y"), (
            "blocked pair lost: B's stale blocked snapshot overwrote A's delete"
        )


class TestDiskMergeBehaviour:
    """A flush must merge with current on-disk state, not blindly overwrite."""

    def test_flush_preserves_externally_added_link(self, tmp_path):
        """A link written to disk after the store loaded must survive a flush."""
        store = _new_store(tmp_path)

        # Simulate another writer appending a link directly to the file.
        external = {
            "id": "ext_link_0001",
            "from_id": "ext_a",
            "to_id": "ext_b",
            "kind": "shares_usage",
            "confidence": 0.7,
            "reason": "external",
            "created_at": "2024-01-01T00:00:00+00:00",
            "status": "active",
        }
        (tmp_path / "links.json").write_text(json.dumps([external]))

        # This store knows nothing about ext_link_0001; its flush must not drop it.
        store.add_link("own_a", "own_b", LinkKind.CONTRASTS_WITH, 0.9, "own")

        on_disk = json.loads((tmp_path / "links.json").read_text())
        disk_ids = {row["id"] for row in on_disk}
        assert "ext_link_0001" in disk_ids, (
            "flush overwrote an externally-added link with a stale snapshot"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
