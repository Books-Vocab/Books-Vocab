"""Tests for JobTracker workspace-busy atomic guard (TOCTOU race fix).

Run:
    cd lab/podcast && uv run --with pytest python -m pytest monitor/test_jobs.py -v
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import jobs as jobs_mod  # noqa: E402
from jobs import JobTracker, WorkspaceBusyError  # noqa: E402


# A command that blocks long enough for the second spawn to race it, without
# depending on `uv`/`pipeline.py`. `sleep` is POSIX-portable.
_BLOCK = ["sleep", "5"]


@pytest.fixture
def tracker(monkeypatch, tmp_path):
    """Fresh tracker with an isolated .jobs dir so tests don't share state."""
    monkeypatch.setattr(jobs_mod, "JOBS_DIR", tmp_path)
    t = JobTracker()
    yield t
    # Clean up any still-running children.
    for jid in list(t._procs):
        t.kill(jid)


def test_same_workspace_second_spawn_rejected(tracker):
    """Two spawns for the same workspace: the second must be refused while the
    first is still running."""
    j1 = tracker.spawn(_BLOCK, label="a", kind="rerun", workspace="ws_alpha")
    assert j1.status == "running"
    with pytest.raises(WorkspaceBusyError):
        tracker.spawn(_BLOCK, label="b", kind="rerun", workspace="ws_alpha")
    # Only one job is tracked as active for that workspace.
    running = [j for j in tracker.list() if j.status == "running"]
    assert len(running) == 1


def test_different_workspaces_both_spawn(tracker):
    """Distinct workspaces are independent — both spawns succeed."""
    j1 = tracker.spawn(_BLOCK, label="a", kind="rerun", workspace="ws_alpha")
    j2 = tracker.spawn(_BLOCK, label="b", kind="rerun", workspace="ws_beta")
    assert j1.status == "running"
    assert j2.status == "running"


def test_no_workspace_unguarded(tracker):
    """workspace=None (e.g. full-pipeline whose ws is unknown at spawn) is not
    workspace-guarded — two such spawns both proceed."""
    j1 = tracker.spawn(_BLOCK, label="a", kind="pipeline")
    j2 = tracker.spawn(_BLOCK, label="b", kind="pipeline")
    assert j1.status == "running"
    assert j2.status == "running"


def test_concurrent_same_workspace_only_one_wins(tracker):
    """Hammer spawn() from many threads for one workspace; exactly one job ends
    up running, the rest raise WorkspaceBusyError. This is the actual TOCTOU
    the precheck-then-spawn pattern in server.py could not close."""
    errors: list[Exception] = []
    successes: list[object] = []
    barrier = threading.Barrier(8)

    def worker(i: int):
        barrier.wait()  # maximize overlap
        try:
            successes.append(
                tracker.spawn(_BLOCK, label=f"w{i}", kind="rerun", workspace="ws_race")
            )
        except WorkspaceBusyError as exc:
            errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert len(successes) == 1, f"expected 1 winner, got {len(successes)}"
    assert len(errors) == 7
    running = [j for j in tracker.list() if j.status == "running"]
    assert len(running) == 1


def test_finished_workspace_job_does_not_block(tracker):
    """Once the first job is no longer running, the same workspace can spawn
    again."""
    j1 = tracker.spawn(["true"], label="a", kind="rerun", workspace="ws_done")
    # Wait for the reaper to flip it off "running".
    proc = tracker._procs.get(j1.id)
    if proc:
        proc.wait()
    # Give the reaper thread a beat to update status.
    for _ in range(200):
        if tracker.get(j1.id).status != "running":
            break
        threading.Event().wait(0.01)
    j2 = tracker.spawn(_BLOCK, label="b", kind="rerun", workspace="ws_done")
    assert j2.status == "running"


# ─── dedup_key generalization (EPUB content-hash upload dedup) ───────────────


def test_same_dedup_key_second_spawn_rejected(tracker):
    """Two spawns sharing a dedup_key (e.g. same EPUB content-hash) must collide:
    the second is refused while the first is still running. workspace= is just a
    specialization of dedup_key, so the same guard applies to upload paths whose
    workspace name isn't known at spawn time."""
    j1 = tracker.spawn(_BLOCK, label="a", kind="pipeline", dedup_key="epub:deadbeef")
    assert j1.status == "running"
    with pytest.raises(WorkspaceBusyError):
        tracker.spawn(_BLOCK, label="b", kind="pipeline", dedup_key="epub:deadbeef")
    running = [j for j in tracker.list() if j.status == "running"]
    assert len(running) == 1


def test_different_dedup_keys_both_spawn(tracker):
    """Distinct EPUB hashes are independent — both uploads proceed."""
    j1 = tracker.spawn(_BLOCK, label="a", kind="pipeline", dedup_key="epub:aaaa")
    j2 = tracker.spawn(_BLOCK, label="b", kind="pipeline", dedup_key="epub:bbbb")
    assert j1.status == "running"
    assert j2.status == "running"


def test_workspace_and_dedup_key_share_namespace(tracker):
    """A workspace= job and a dedup_key= job collide iff the keys are equal —
    they live in one namespace. Passing both is rejected as a programming error."""
    # workspace="ws_x" reserves the key "ws_x"; a later dedup_key="ws_x" collides.
    j1 = tracker.spawn(_BLOCK, label="a", kind="rerun", workspace="ws_x")
    assert j1.status == "running"
    with pytest.raises(WorkspaceBusyError):
        tracker.spawn(_BLOCK, label="b", kind="pipeline", dedup_key="ws_x")
    with pytest.raises(ValueError):
        tracker.spawn(_BLOCK, label="c", kind="rerun", workspace="w", dedup_key="d")


def test_concurrent_same_dedup_key_only_one_wins(tracker):
    """Hammer spawn() from many threads for one dedup_key; exactly one wins. This
    is the upload-path TOCTOU: two concurrent POST /api/pipeline/start of the same
    EPUB bytes both reach spawn before either reserves."""
    errors: list[Exception] = []
    successes: list[object] = []
    barrier = threading.Barrier(8)

    def worker(i: int):
        barrier.wait()
        try:
            successes.append(
                tracker.spawn(_BLOCK, label=f"w{i}", kind="pipeline", dedup_key="epub:race")
            )
        except WorkspaceBusyError as exc:
            errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert len(successes) == 1, f"expected 1 winner, got {len(successes)}"
    assert len(errors) == 7
    running = [j for j in tracker.list() if j.status == "running"]
    assert len(running) == 1
