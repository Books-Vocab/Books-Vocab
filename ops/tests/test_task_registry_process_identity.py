from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

OPS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS_ROOT))

import task_registry


def _lstart(pid: int) -> str:
    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
    process.wait(timeout=2)


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin process API regression")
def test_darwin_identity_distinguishes_same_second_process_starts() -> None:
    for _ in range(20):
        first = subprocess.Popen(["sleep", "5"])
        second = subprocess.Popen(["sleep", "5"])
        if _lstart(first.pid) == _lstart(second.pid):
            break
        _stop(first)
        _stop(second)
    else:
        pytest.fail("could not start two sleep processes in the same ps lstart second")

    try:
        first_identity = task_registry.process_start_identity(first.pid)
        second_identity = task_registry.process_start_identity(second.pid)

        assert first_identity
        assert second_identity
        assert first_identity != second_identity
    finally:
        _stop(first)
        _stop(second)


def test_identity_fails_closed_when_only_second_precision_ps_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(task_registry, "_proc_stat_start_identity", lambda pid: None)
    monkeypatch.setattr(task_registry.sys, "platform", "unsupported")

    def fake_ps(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args,
            0,
            stdout="Thu Aug 21 17:30:09 2026\n",
            stderr="",
        )

    monkeypatch.setattr(task_registry.subprocess, "run", fake_ps)

    assert task_registry.process_start_identity(12345) is None
