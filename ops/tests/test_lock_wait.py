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
    machine_output = io.StringIO()

    with contextlib.redirect_stdout(machine_output), contextlib.redirect_stderr(progress):
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
    assert machine_output.getvalue() == ""


def test_fail_closed_turns_non_contention_error_into_named_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_fd: int, _operation: int) -> None:
        raise OSError(errno.EPERM, "not permitted")

    monkeypatch.setattr(lock_wait.fcntl, "flock", fail)

    with pytest.raises(lock_wait.LockUnavailable, match="test-queue"):
        with lock_wait.exclusive_lock(tmp_path / "queue.lock", label="test-queue"):
            pass


def test_backoff_cannot_sleep_past_heartbeat_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def fake_flock(_fd: int, operation: int) -> None:
        nonlocal attempts
        if operation & lock_wait.fcntl.LOCK_UN:
            return
        attempts += 1
        if attempts == 1:
            raise BlockingIOError(errno.EAGAIN, "busy")

    monkeypatch.setattr(lock_wait.fcntl, "flock", fake_flock)
    monkeypatch.setattr(lock_wait.time, "sleep", sleeps.append)

    with lock_wait.exclusive_lock(
        tmp_path / "ceiling.lock",
        label="ceiling",
        initial_delay=40.0,
        max_delay=60.0,
        heartbeat_interval=20.0,
    ):
        pass

    assert sleeps == [20.0]


@pytest.mark.parametrize("heartbeat_interval", [-1.0, float("nan"), float("inf")])
def test_heartbeat_interval_rejects_undefined_values(
    tmp_path: Path, heartbeat_interval: float
) -> None:
    with pytest.raises(ValueError, match="heartbeat_interval"):
        with lock_wait.exclusive_lock(
            tmp_path / "invalid.lock", label="invalid", heartbeat_interval=heartbeat_interval
        ):
            pass


def test_heartbeat_interval_above_ceiling_is_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def fake_flock(_fd: int, operation: int) -> None:
        nonlocal attempts
        if operation & lock_wait.fcntl.LOCK_UN:
            return
        attempts += 1
        if attempts == 1:
            raise BlockingIOError(errno.EAGAIN, "busy")

    monkeypatch.setattr(lock_wait.fcntl, "flock", fake_flock)
    monkeypatch.setattr(lock_wait.time, "sleep", sleeps.append)

    with lock_wait.exclusive_lock(
        tmp_path / "large-heartbeat.lock",
        label="large-heartbeat",
        initial_delay=60.0,
        max_delay=60.0,
        heartbeat_interval=60.0,
    ):
        pass

    assert sleeps == [20.0]


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
