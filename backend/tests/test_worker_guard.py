"""Phase 3: fail-loud guard that the API runs as a single Uvicorn worker.

quota_service._reservations, translate_service._INFLIGHT and pipeline_log's
startup interrupt-marking are all process-local — they are only correct
under `--workers 1`. The Dockerfile pins that, but nothing *enforced* it.
These tests pin the guard that makes a second worker refuse to start.
"""

from __future__ import annotations

import fcntl
import os

import pytest


def _release_guard() -> None:
    from kg import worker_guard

    if worker_guard._lock_fd is not None:
        os.close(worker_guard._lock_fd)
        worker_guard._lock_fd = None


@pytest.fixture(autouse=True)
def _reset_guard():
    """Each test must start with no lock held. Reset on BOTH ends: another
    test (e.g. a TestClient lifespan) may have acquired the process-global
    lock before this test runs — without a setup-side reset, our calls
    would hit the idempotent early-return and never touch the lock file."""
    _release_guard()
    yield
    _release_guard()


def test_first_worker_acquires_lock(tmp_path):
    from kg import worker_guard

    lock = tmp_path / ".worker.lock"
    worker_guard.assert_single_worker(lock)
    assert worker_guard._lock_fd is not None
    assert lock.exists()


def test_second_worker_raises(tmp_path):
    """With the lock already held (simulating worker #1 in another
    process), assert_single_worker must raise — not silently pass."""
    from kg import worker_guard

    lock = tmp_path / ".worker.lock"
    other_fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(other_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(worker_guard.MultipleWorkersError):
            worker_guard.assert_single_worker(lock)
        # The failed attempt must not leave a dangling held fd.
        assert worker_guard._lock_fd is None
    finally:
        fcntl.flock(other_fd, fcntl.LOCK_UN)
        os.close(other_fd)


def test_idempotent_within_process(tmp_path):
    """A repeat call within the same process is a no-op — the lock is
    already held, so it must not re-open a second fd or raise."""
    from kg import worker_guard

    lock = tmp_path / ".worker.lock"
    worker_guard.assert_single_worker(lock)
    fd1 = worker_guard._lock_fd
    worker_guard.assert_single_worker(lock)
    assert worker_guard._lock_fd is fd1


def test_lock_released_allows_reacquire(tmp_path):
    """Once worker #1 releases the lock, a fresh acquire succeeds — the
    guard does not permanently poison the lock file."""
    from kg import worker_guard

    lock = tmp_path / ".worker.lock"
    other_fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(other_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(worker_guard.MultipleWorkersError):
        worker_guard.assert_single_worker(lock)
    fcntl.flock(other_fd, fcntl.LOCK_UN)
    os.close(other_fd)

    worker_guard.assert_single_worker(lock)
    assert worker_guard._lock_fd is not None
