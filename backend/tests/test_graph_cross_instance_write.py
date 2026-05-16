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


class TestUnblockNotResurrected:
    """unblock_pair / remove_blocked_pairs_for must survive a stale flush.

    A naive union merge in ``_flush_blocked`` would resurrect a pair the
    user explicitly unblocked: memory has discarded it, disk still has it,
    and the union adds it back. ``_known_blocked_pairs`` makes the unblock
    authoritative while still preserving pairs blocked by other instances.
    """

    def test_unblock_not_resurrected_by_stale_instance(self, tmp_path):
        """A unblocks; stale B flushes -- the pair must stay unblocked."""
        a = _new_store(tmp_path)
        lk = a.add_link("x", "y", LinkKind.CONTRASTS_WITH, 0.9, "r")
        a.hard_delete_link(lk.id)  # (x, y) is now blocked on disk

        # B loads AFTER the block: it knows (x, y) as blocked.
        b = _new_store(tmp_path)
        assert b.is_blocked("x", "y")

        # User unblocks on A.
        a.unblock_pair("x", "y")
        assert not a.is_blocked("x", "y")

        # Stale B (snapshot still has the pair) flushes via an unrelated op.
        b.add_link("p", "q", LinkKind.SHARES_USAGE, 0.8, "r2")

        reloaded = _new_store(tmp_path)
        assert not reloaded.is_blocked("x", "y"), (
            "unblock resurrected: B's stale snapshot re-added the pair"
        )

    def test_unblock_then_self_flush_not_resurrected(self, tmp_path):
        """unblock_pair's own flush must not union the pair back from disk."""
        store = _new_store(tmp_path)
        lk = store.add_link("x", "y", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.hard_delete_link(lk.id)
        assert store.is_blocked("x", "y")

        store.unblock_pair("x", "y")

        reloaded = _new_store(tmp_path)
        assert not reloaded.is_blocked("x", "y"), (
            "unblock_pair's merge resurrected the pair from its own disk file"
        )

    def test_remove_blocked_pairs_for_not_resurrected(self, tmp_path):
        """remove_blocked_pairs_for must survive a stale instance flush."""
        a = _new_store(tmp_path)
        lk1 = a.add_link("c", "d", LinkKind.CONTRASTS_WITH, 0.9, "r1")
        lk2 = a.add_link("c", "e", LinkKind.SHARES_USAGE, 0.8, "r2")
        a.hard_delete_link(lk1.id)  # blocks (c, d)
        a.hard_delete_link(lk2.id)  # blocks (c, e)

        b = _new_store(tmp_path)  # B sees both blocked pairs
        assert b.is_blocked("c", "d") and b.is_blocked("c", "e")

        # Remove every blocked pair touching card "c" on A.
        a.remove_blocked_pairs_for("c")
        assert not a.is_blocked("c", "d")
        assert not a.is_blocked("c", "e")

        # Stale B flushes.
        b.add_link("p", "q", LinkKind.SHARES_USAGE, 0.8, "r3")

        reloaded = _new_store(tmp_path)
        assert not reloaded.is_blocked("c", "d"), "remove_blocked_pairs_for resurrected (c,d)"
        assert not reloaded.is_blocked("c", "e"), "remove_blocked_pairs_for resurrected (c,e)"

    def test_foreign_blocked_pair_preserved_through_unblock(self, tmp_path):
        """A pair blocked by another instance must survive A's unblock flush."""
        a = _new_store(tmp_path)
        lk = a.add_link("x", "y", LinkKind.CONTRASTS_WITH, 0.9, "r")
        a.hard_delete_link(lk.id)  # A blocks (x, y)

        # B blocks (m, n) -- A never sees this pair.
        b = _new_store(tmp_path)
        lk_b = b.add_link("m", "n", LinkKind.SHARES_USAGE, 0.8, "rb")
        b.hard_delete_link(lk_b.id)

        # A unblocks its own pair; its flush must not drop B's foreign pair.
        a.unblock_pair("x", "y")

        reloaded = _new_store(tmp_path)
        assert not reloaded.is_blocked("x", "y"), "A's unblock did not take effect"
        assert reloaded.is_blocked("m", "n"), (
            "foreign blocked pair from B was dropped by A's unblock flush"
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
