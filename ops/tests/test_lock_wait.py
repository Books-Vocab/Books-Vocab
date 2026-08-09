"""Contracts for the shared coordination-lock wait primitive."""

from __future__ import annotations

import contextlib
import errno
import io
import sys
from pathlib import Path

import pytest

OPS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS_ROOT))
from lib import lock_wait


def test_contended_lock_uses_exponential_backoff_and_stderr_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def fake_flock(_fd: int, operation: int) -> None:
        nonlocal attempts
        if operation & lock_wait.fcntl.LOCK_UN:
            return
        attempts += 1
        if attempts <= 4:
            raise BlockingIOError(errno.EAGAIN, "busy")

    monkeypatch.setattr(lock_wait.fcntl, "flock", fake_flock)
    monkeypatch.setattr(lock_wait.time, "sleep", sleeps.append)
    progress = io.StringIO()

    with contextlib.redirect_stderr(progress):
        with lock_wait.exclusive_lock(
            tmp_path / "ledger.lock",
            label="test-ledger",
            initial_delay=0.25,
            max_delay=1.0,
            heartbeat_interval=0.0,
        ) as held:
            assert held is True

    assert sleeps == [0.25, 0.5, 1.0, 1.0]
    output = progress.getvalue()
    assert "label=test-ledger phase=waiting" in output
    assert "label=test-ledger phase=acquired" in output


def test_fail_closed_turns_non_contention_error_into_named_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_fd: int, _operation: int) -> None:
        raise OSError(errno.EPERM, "not permitted")

    monkeypatch.setattr(lock_wait.fcntl, "flock", fail)

    with pytest.raises(lock_wait.LockUnavailable, match="test-queue"):
        with lock_wait.exclusive_lock(tmp_path / "queue.lock", label="test-queue"):
            pass


def test_fail_open_only_applies_to_non_contention_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_fd: int, _operation: int) -> None:
        raise OSError(errno.EPERM, "not permitted")

    monkeypatch.setattr(lock_wait.fcntl, "flock", fail)

    with lock_wait.exclusive_lock(
        tmp_path / "view.lock", label="test-view", fail_closed=False
    ) as held:
        assert held is False
