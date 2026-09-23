from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("env_drift", ROOT / "ops" / "env_drift.py")
assert SPEC and SPEC.loader
env_drift = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(env_drift)


def test_read_remote_quotes_untrusted_path_and_preserves_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["command"] = command
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="TOKEN=stable\n", stderr="")

    monkeypatch.setattr(env_drift.subprocess, "run", fake_run)

    path = "/srv/app/.env; printf pwned > /tmp/pwned #"
    assert env_drift._read_remote(path, "standby") == {"TOKEN": "stable"}
    assert calls["command"] == [
        "ssh",
        "-T",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=yes",
        "standby",
        "cat -- '/srv/app/.env; printf pwned > /tmp/pwned #'",
    ]
    assert calls["kwargs"] == {
        "capture_output": True,
        "text": True,
        "check": False,
    }


def test_read_remote_preserves_paths_with_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="TOKEN=stable\n", stderr="")

    monkeypatch.setattr(env_drift.subprocess, "run", fake_run)

    assert env_drift._read_remote("/srv/remote env/.env", "standby") == {"TOKEN": "stable"}
    assert calls["command"][-1] == "cat -- '/srv/remote env/.env'"


def test_read_remote_preserves_remote_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 255, stdout="", stderr="permission denied\n")

    monkeypatch.setattr(env_drift.subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match=r"無法讀取遠端 \.env：permission denied"):
        env_drift._read_remote("/srv/app/.env", "standby")
