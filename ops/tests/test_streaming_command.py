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

    def _pids_written() -> dict[str, int] | None:
        """Parsed contents, or None. EXISTENCE is not the signal.

        The child does `open(path,'w').write(...)`, and `open(..., 'w')` creates the
        file before anything is written to it — so `pid_file.exists()` goes true with
        the file still empty, and the `json.loads` after the interrupt gets `''`.
        Measured: green in isolation, red under full-suite load, which is the window
        widening rather than a different bug.
        """
        try:
            return json.loads(pid_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    class InterruptOnSpawned(io.StringIO):
        def write(self, value: str) -> int:
            if "phase=spawned" in value:
                deadline = time.monotonic() + 3
                while _pids_written() is None and time.monotonic() < deadline:
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


def test_timeout_terminates_child_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "timeout-pids.json"
    child_script = (
        "import json,os,subprocess,sys,time; "
        "grandchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(json.dumps({'child':os.getpid(),'grandchild':grandchild.pid})); "
        "time.sleep(60)"
    )
    pids: dict[str, int] = {}
    try:
        completed = run_streamed_command(
            [sys.executable, "-c", child_script, str(pid_file)],
            cwd=tmp_path,
            label_key="source",
            label="timeout-test",
            progress_prefix="[test]",
            heartbeat_interval=0.02,
            # 這個預算不能貼著跑：下面 assert 之前要先讀 pid_file，而那要求 child 在
            # timeout 開火**之前**已經生出 grandchild 直譯器並寫完檔。實測那段要
            # 92-97ms（load average 20 的機器上，2026-08-06），原本的 0.1s 只剩
            # 3-8ms 餘裕 = 擲硬幣：機器閒時綠、有負載時 FileNotFoundError。
            # child 寫完後 sleep(60)，所以放寬預算不會讓 timeout 失去意義——它照樣
            # 在行程還活著時開火，被斷言的契約（逾時殺整個 process group）一字未改。
            timeout_seconds=1.5,
        )
        assert completed.returncode == 124
        pids = json.loads(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 2
        while any(_process_is_live(pid) for pid in pids.values()) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not any(_process_is_live(pid) for pid in pids.values())
    finally:
        for pid in pids.values():
            if _process_is_live(pid):
                os.kill(pid, signal.SIGKILL)


def test_timeout_kills_grandchild_after_group_leader_exits(tmp_path: Path) -> None:
    pid_file = tmp_path / "leader-exited-grandchild.pid"
    child_script = (
        "import subprocess,sys; "
        "grandchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(str(grandchild.pid))"
    )
    grandchild_pid = 0
    try:
        started = time.monotonic()
        completed = run_streamed_command(
            [sys.executable, "-c", child_script, str(pid_file)],
            cwd=tmp_path,
            label_key="source",
            label="leader-exited-timeout-test",
            progress_prefix="[test]",
            heartbeat_interval=0.02,
            # 同上：child 要先 spawn grandchild 並寫檔（實測 92-97ms）才輪得到下面
            # 讀 pid_file，0.1s 沒有餘裕。grandchild sleep(60)，所以 timeout 照樣
            # 在它活著時開火。
            timeout_seconds=1.5,
        )
        elapsed = time.monotonic() - started
        assert completed.returncode == 124
        # 界線跟著預算走：這條要擋的是「等完 grandchild 的 60s 才回來」，不是
        # 卡死一個特定毫秒數。1.5s 預算 + 收屍時間仍遠低於 5s。
        assert elapsed < 5
        grandchild_pid = int(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 2
        while _process_is_live(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _process_is_live(grandchild_pid)
    finally:
        if grandchild_pid and _process_is_live(grandchild_pid):
            os.kill(grandchild_pid, signal.SIGKILL)
