"""Stale GraphStore instance vs. a foreign writer (#2086).

The API keeps one long-lived ``GraphStore`` per notebook while ``ops-edit``
rewrites the same JSON files from another process. Each test pairs a stale
instance (``api``, the cached store) with a second instance (``ops``) that
loads fresh from disk and writes, exactly like the CLI process does.

Before the fix the stale snapshot won the flush merge for every id it held, so
a foreign delete was resurrected and a foreign update reverted on the stale
instance's next unrelated write.
"""

from __future__ import annotations

import json

import pytest

from kg.graph import GraphStore, LinkKind


def _new_store(tmp_path) -> GraphStore:
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
    )


def _disk_links(tmp_path) -> dict[str, dict]:
    return {row["id"]: row for row in json.loads((tmp_path / "links.json").read_text())}


def _disk_blocked(tmp_path) -> set[tuple[str, str]]:
    return {tuple(sorted(pair)) for pair in json.loads((tmp_path / "blocked.json").read_text())}


def test_foreign_delete_not_resurrected_by_unrelated_flush(tmp_path):
    api = _new_store(tmp_path)
    doomed = api.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")

    ops = _new_store(tmp_path)
    ops.hard_delete_link(doomed.id, source="ops")

    other = api.add_link("c", "d", LinkKind.SHARES_USAGE, 0.8, "unrelated")

    on_disk = _disk_links(tmp_path)
    assert doomed.id not in on_disk, "stale snapshot resurrected a link deleted by another process"
    assert other.id in on_disk
    assert api.get_link(doomed.id) is None, "stale instance still serves the foreign-deleted link"
    assert ("a", "b") in _disk_blocked(tmp_path)


def test_foreign_update_not_reverted_by_unrelated_flush(tmp_path):
    api = _new_store(tmp_path)
    target = api.add_link("a", "b", LinkKind.SHARES_USAGE, 0.3, "orig")

    ops = _new_store(tmp_path)
    ops.update_link(target.id, source="ops", confidence=0.95, reason="revised")

    api.add_link("c", "d", LinkKind.SHARES_USAGE, 0.8, "unrelated")

    row = _disk_links(tmp_path)[target.id]
    assert row["confidence"] == pytest.approx(0.95), "stale snapshot reverted a foreign link-update"
    assert row["reason"] == "revised"
    assert api.get_link(target.id).reason == "revised"


def test_foreign_delete_wins_over_stale_edit_of_same_link(tmp_path):
    """Editing a link another process deleted must not bring it back."""
    api = _new_store(tmp_path)
    doomed = api.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")

    ops = _new_store(tmp_path)
    ops.hard_delete_link(doomed.id, source="ops")

    with pytest.raises(KeyError):  # the mutator re-syncs first: the link is simply gone
        api.hide_link(doomed.id)

    assert doomed.id not in _disk_links(tmp_path)
    assert api.get_link(doomed.id) is None


def test_own_change_survives_foreign_write(tmp_path):
    """The stale instance's own edit still lands next to the foreign one."""
    api = _new_store(tmp_path)
    mine = api.add_link("a", "b", LinkKind.SHARES_USAGE, 0.3, "mine")

    ops = _new_store(tmp_path)
    foreign = ops.add_link("c", "d", LinkKind.SHARES_USAGE, 0.6, "foreign")

    api.update_link(mine.id, confidence=0.7)

    on_disk = _disk_links(tmp_path)
    assert on_disk[mine.id]["confidence"] == pytest.approx(0.7)
    assert foreign.id in on_disk
    assert api.get_link(foreign.id) is not None, "foreign link-add is adopted by the stale instance after its flush"


def test_foreign_unblock_not_resurrected_by_stale_blocked_flush(tmp_path):
    api = _new_store(tmp_path)
    first = api.add_link("x", "y", LinkKind.CONTRASTS_WITH, 0.9, "r")
    api.hard_delete_link(first.id)  # (x, y) blocked; api remembers it

    ops = _new_store(tmp_path)
    ops.unblock_pair("x", "y")

    second = api.add_link("p", "q", LinkKind.SHARES_USAGE, 0.8, "r2")
    api.hard_delete_link(second.id)  # flushes api's stale blocked snapshot

    blocked = _disk_blocked(tmp_path)
    assert ("x", "y") not in blocked, "stale blocked snapshot resurrected a foreign unblock"
    assert ("p", "q") in blocked
    assert not api.is_blocked("x", "y")


def test_refresh_if_stale_adopts_foreign_write_and_keeps_unflushed_edit(tmp_path, monkeypatch):
    api = _new_store(tmp_path)
    doomed = api.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
    assert api.refresh_if_stale() is False  # own write: nothing to re-read

    ops = _new_store(tmp_path)
    ops.hard_delete_link(doomed.id, source="ops")
    foreign = ops.add_link("c", "d", LinkKind.SHARES_USAGE, 0.6, "foreign")

    # An edit whose flush has not landed yet must survive the re-sync.
    monkeypatch.setattr(api, "_flush_links", lambda _snapshot: None)
    monkeypatch.setattr(api, "_reconcile_persisted_pairs", lambda *_a, **_k: None)
    pending = api.add_link("e", "f", LinkKind.SHARES_USAGE, 0.5, "unflushed")

    assert api.refresh_if_stale() is True
    assert api.get_link(doomed.id) is None
    assert api.is_blocked("a", "b")
    assert api.get_link(foreign.id) is not None
    assert api.get_link(pending.id) is pending
    assert api.refresh_if_stale() is False


def test_refresh_between_snapshot_and_flush_does_not_resurrect_foreign_delete(tmp_path, monkeypatch):
    """A refresh (every API request) landing inside an edit's snapshot -> flush window.

    Adopting the foreign state must not make the in-flight edit of a
    foreign-deleted link look like a link created here.
    """
    api = _new_store(tmp_path)
    doomed = api.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")

    ops = _new_store(tmp_path)
    ops.hard_delete_link(doomed.id, source="ops")

    captured: list = []
    monkeypatch.setattr(api, "_flush_links", captured.append)
    monkeypatch.setattr(api, "_reconcile_persisted_pairs", lambda *_a, **_k: None)
    monkeypatch.setattr(api, "refresh_if_stale", lambda: False)  # the edit starts before any refresh
    api.update_link(doomed.id, confidence=0.4)
    assert len(captured) == 1
    monkeypatch.undo()

    assert api.refresh_if_stale() is True  # a concurrent request re-syncs
    GraphStore._flush_links(api, captured[0])  # the deferred flush finally lands

    assert doomed.id not in _disk_links(tmp_path), "in-flight edit resurrected a foreign-deleted link"
    assert api.get_link(doomed.id) is None


def test_edit_of_link_foreign_updated_keeps_foreign_fields(tmp_path):
    """Row-level last-writer-wins must not revert a foreign update of the same link."""
    api = _new_store(tmp_path)
    target = api.add_link("a", "b", LinkKind.SHARES_USAGE, 0.3, "orig")

    ops = _new_store(tmp_path)
    ops.update_link(target.id, source="ops", confidence=0.95, reason="revised")

    api.hide_link(target.id)

    row = _disk_links(tmp_path)[target.id]
    assert row["status"] == "hidden"
    assert row["confidence"] == pytest.approx(0.95), "stale row reverted a foreign update of the same link"
    assert row["reason"] == "revised"


def test_refresh_survives_malformed_foreign_row(tmp_path):
    """One bad foreign row must not make every request fail; it is skipped, not served."""
    api = _new_store(tmp_path)
    keep = api.add_link("a", "b", LinkKind.SHARES_USAGE, 0.5, "keep")
    bad = api.add_link("c", "d", LinkKind.SHARES_USAGE, 0.5, "bad")

    rows = json.loads((tmp_path / "links.json").read_text())
    for row in rows:
        if row["id"] == bad.id:
            row["confidence"] = "not-a-number"
    (tmp_path / "links.json").write_text(json.dumps(rows))

    api.refresh_if_stale()  # must not raise

    assert api.get_link(keep.id) is not None
    assert api.get_link(bad.id) is None
    assert api.refresh_if_stale() is False


def test_refresh_keeps_cached_view_when_file_unreadable(tmp_path):
    """A corrupt file without a usable .bak is not an empty graph."""
    api = _new_store(tmp_path)
    link = api.add_link("a", "b", LinkKind.SHARES_USAGE, 0.5, "r")
    (tmp_path / "links.json.bak").unlink(missing_ok=True)
    (tmp_path / "links.json").write_text("{not json")

    api.refresh_if_stale()

    assert api.get_link(link.id) is not None, "corrupt file wiped the cached graph"

    # The next flush regenerates the file from the instance's full view.
    other = api.add_link("c", "d", LinkKind.SHARES_USAGE, 0.5, "next")
    assert {link.id, other.id} <= set(_disk_links(tmp_path))
