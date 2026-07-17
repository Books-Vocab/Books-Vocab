from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

OPS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS_ROOT))
from lib import streaming_command  # noqa: E402
from lib.streaming_command import run_streamed_command  # noqa: E402


def _process_is_live(pid: int) -> bool:
    completed = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    state = completed.stdout.strip()
    return completed.returncode == 0 and bool(state) and not state.startswith("Z")


def test_progress_contract_and_separate_streams(tmp_path: Path) -> None:
    parent_stdout = io.StringIO()
    parent_stderr = io.StringIO()

    with redirect_stdout(parent_stdout), redirect_stderr(parent_stderr):
        completed = run_streamed_command(
            [
                sys.executable,
                "-c",
                "import sys,time; print('json'); print('diagnostic', file=sys.stderr); time.sleep(.06)",
            ],
            cwd=tmp_path,
            label_key="producer",
            label="contract-test",
            progress_prefix="[test]",
            heartbeat_interval=0.02,
        )

    assert parent_stdout.getvalue() == ""
    assert completed.stdout == "json\n"
    assert completed.stderr == "diagnostic\n"
    progress_lines = parent_stderr.getvalue().splitlines()
    phases = [line.split("phase=", 1)[1].split()[0] for line in progress_lines]
    assert phases[0:2] == ["start", "spawned"]
    assert "heartbeat" in phases
    assert phases[-1] == "done"
    for line in progress_lines:
        assert "elapsed=" in line
        assert "pid=" in line
        assert "alive=" in line


def test_large_dual_stream_output_is_drained_and_bounded(tmp_path: Path) -> None:
    completed = run_streamed_command(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'o'*200000); sys.stderr.buffer.write(b'e'*200000)",
        ],
        cwd=tmp_path,
        label_key="producer",
        label="large-output",
        progress_prefix="[test]",
        heartbeat_interval=0.02,
        capture_limit=4096,
    )

    assert completed.returncode == 0
    assert completed.stdout == "o" * 4096
    assert completed.stderr == "e" * 4096


def test_signal_return_code_is_preserved(tmp_path: Path) -> None:
    completed = run_streamed_command(
        [
            sys.executable,
            "-c",
            "import os,signal; os.kill(os.getpid(), signal.SIGTERM)",
        ],
        cwd=tmp_path,
        label_key="gate",
        label="signal-test",
        progress_prefix="[test]",
        heartbeat_interval=0.02,
    )

    assert completed.returncode == -signal.SIGTERM
    assert os.WTERMSIG(-completed.returncode) == signal.SIGTERM


def test_progress_never_logs_raw_command_arguments(tmp_path: Path) -> None:
    secret = "password=SECRET-CANARY-9d61"
    progress = io.StringIO()

    with redirect_stderr(progress):
        completed = run_streamed_command(
            [sys.executable, "-c", "print('ok')", secret],
            cwd=tmp_path,
            label_key="producer",
            label="redaction-test",
            progress_prefix="[test]",
            heartbeat_interval=0.02,
        )

    assert completed.returncode == 0
    assert secret not in progress.getvalue()
    assert "SECRET-CANARY" not in progress.getvalue()


def test_interrupt_terminates_child_process_group(tmp_path: Path, monkeypatch) -> None:
    pid_file = tmp_path / "pids.json"
    child_script = (
        "import json,os,subprocess,sys,time; "
        "grandchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(json.dumps({'child':os.getpid(),'grandchild':grandchild.pid})); "
        "time.sleep(60)"
    )
    original_get = streaming_command.queue.Queue.get

    def interrupt_after_grandchild_started(self, timeout=None):
        deadline = time.monotonic() + 3
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not pid_file.exists():
            return original_get(self, timeout=timeout)
        raise KeyboardInterrupt

    monkeypatch.setattr(streaming_command.queue.Queue, "get", interrupt_after_grandchild_started)
    pids: dict[str, int] = {}
    try:
        with pytest.raises(KeyboardInterrupt):
            run_streamed_command(
                [sys.executable, "-c", child_script, str(pid_file)],
                cwd=tmp_path,
                label_key="gate",
                label="interrupt-test",
                progress_prefix="[test]",
                heartbeat_interval=0.02,
            )
        pids = json.loads(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 2
        while any(_process_is_live(pid) for pid in pids.values()) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not any(_process_is_live(pid) for pid in pids.values())
    finally:
        for pid in pids.values():
            if _process_is_live(pid):
                os.kill(pid, signal.SIGKILL)


def test_interrupt_during_spawned_progress_terminates_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "early-pids.json"
    child_script = (
        "import json,os,subprocess,sys,time; "
        "grandchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(json.dumps({'child':os.getpid(),'grandchild':grandchild.pid})); "
        "time.sleep(60)"
    )

    class InterruptOnSpawned(io.StringIO):
        def write(self, value: str) -> int:
            if "phase=spawned" in value:
                deadline = time.monotonic() + 3
                while not pid_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                raise KeyboardInterrupt
            return super().write(value)

    pids: dict[str, int] = {}
    try:
        with redirect_stderr(InterruptOnSpawned()), pytest.raises(KeyboardInterrupt):
            run_streamed_command(
                [sys.executable, "-c", child_script, str(pid_file)],
                cwd=tmp_path,
                label_key="gate",
                label="early-interrupt-test",
                progress_prefix="[test]",
                heartbeat_interval=0.02,
            )
        pids = json.loads(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 2
        while any(_process_is_live(pid) for pid in pids.values()) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not any(_process_is_live(pid) for pid in pids.values())
    finally:
        if pids and any(_process_is_live(pid) for pid in pids.values()):
            try:
                os.killpg(pids["child"], signal.SIGKILL)
            except ProcessLookupError:
                pass
