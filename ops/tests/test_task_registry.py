from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

OPS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS_ROOT))

from lib import streaming_command  # noqa: E402
from lib.streaming_command import CommandCancelled, run_streamed_command  # noqa: E402
from task_registry import (  # noqa: E402
    TaskRegistry,
    command_identity,
    process_start_identity,
)


def _sleep_command(seconds: float = 0.35) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


def _old_timestamp() -> str:
    return "2000-01-01T00:00:00+00:00"


class _TrackedPipe:
    def __init__(self, pipe: object) -> None:
        self._pipe = pipe
        self.closed = False

    def read1(self, size: int) -> bytes:
        return self._pipe.read1(size)  # type: ignore[attr-defined]

    def close(self) -> None:
        self.closed = True
        self._pipe.close()  # type: ignore[attr-defined]


def _track_owned_pipes(monkeypatch: pytest.MonkeyPatch) -> list[_TrackedPipe]:
    tracked: list[_TrackedPipe] = []
    real_popen = subprocess.Popen

    def tracked_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        proc = real_popen(*args, **kwargs)
        for stream_name in ("stdout", "stderr"):
            pipe = getattr(proc, stream_name)
            if pipe is None:
                continue
            owned_pipe = _TrackedPipe(pipe)
            setattr(proc, stream_name, owned_pipe)
            tracked.append(owned_pipe)
        return proc

    monkeypatch.setattr(
        streaming_command,
        "subprocess",
        SimpleNamespace(
            CompletedProcess=subprocess.CompletedProcess,
            PIPE=subprocess.PIPE,
            Popen=tracked_popen,
            STDOUT=subprocess.STDOUT,
        ),
    )
    return tracked


def _assert_all_pipes_closed(tracked: list[_TrackedPipe]) -> None:
    assert len(tracked) == 2
    assert all(pipe.closed for pipe in tracked)


def test_parallel_registry_writes_preserve_two_lifecycles(tmp_path: Path) -> None:
    state_path = tmp_path / "task-registry.json"
    identity = process_start_identity(os.getpid())
    assert identity

    def worker(index: int) -> str:
        registry = TaskRegistry(
            state_path,
            session_id="session-parallel",
            worktree=tmp_path,
        )
        task = registry.start(
            command=["python", "--token", "sensitive-value", str(index)],
            log_path=tmp_path / f"task-{index}.log",
        )
        registry.bind_process(
            task["task_id"],
            pid=os.getpid(),
            pgid=os.getpgid(os.getpid()),
            start_identity=identity,
        )
        registry.heartbeat(task["task_id"], phase="heartbeat")
        registry.finish(task["task_id"], returncode=0)
        return task["task_id"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        task_ids = list(pool.map(worker, (1, 2)))

    records = TaskRegistry.load(state_path)["records"]
    assert {record["task_id"] for record in records} == set(task_ids)
    assert all(record["status"] == "finished" for record in records)
    assert all(record["heartbeat_at"] for record in records)
    assert all(record["finished_at"] for record in records)


def test_command_identity_is_non_sensitive() -> None:
    identity = command_identity(
        ["/usr/bin/python3", "-c", "--api-token", "super-secret-value"]
    )

    rendered = json.dumps(identity, sort_keys=True)
    assert identity["basename"] == "python3"
    assert identity["arg_count"] == 4
    assert len(identity["argv_sha256"]) == 64
    assert "super-secret-value" not in rendered
    assert "api-token" not in rendered


def test_streaming_command_records_start_heartbeat_finish_without_raw_argv(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "task-registry.json"
    completed = run_streamed_command(
        [sys.executable, "-c", "import time; print('ok'); time.sleep(.12)"],
        cwd=tmp_path,
        label_key="gate",
        label="registry-test",
        progress_prefix="[test]",
        heartbeat_interval=0.03,
        task_registry_path=state_path,
        task_session_id="session-streaming",
        task_log_path=tmp_path / "stream.log",
    )

    assert completed.returncode == 0
    records = TaskRegistry.load(state_path)["records"]
    assert len(records) == 1
    record = records[0]
    assert record["session_id"] == "session-streaming"
    assert record["worktree"] == str(tmp_path.resolve())
    assert record["pid"] > 0
    assert record["pgid"] > 0
    assert record["start_identity"]
    assert record["phase"] == "finished"
    assert record["status"] == "finished"
    assert record["heartbeat_at"]
    assert record["finished_at"]
    assert record["log_path"] == str((tmp_path / "stream.log").resolve())
    assert "import time" not in json.dumps(record["command_identity"])


def test_streaming_command_spawn_failure_has_terminal_outcome(tmp_path: Path) -> None:
    state_path = tmp_path / "task-registry.json"
    with pytest.raises(FileNotFoundError):
        run_streamed_command(
            [str(tmp_path / "does-not-exist"), "secret-argv"],
            cwd=tmp_path,
            label_key="gate",
            label="spawn-failure",
            progress_prefix="[test]",
            task_registry_path=state_path,
            task_session_id="session-spawn-failure",
        )

    record = TaskRegistry.load(state_path)["records"][0]
    assert record["status"] == "finished"
    assert record["phase"] == "finished"
    assert record["terminal_outcome"] == "spawn-failed:FileNotFoundError"


@pytest.mark.parametrize(
    ("command", "expected_returncode"),
    [
        ([sys.executable, "-c", "print('normal')"], 0),
        (
            [
                sys.executable,
                "-c",
                "import sys; print('failure', file=sys.stderr); raise SystemExit(7)",
            ],
            7,
        ),
    ],
    ids=("normal", "failure"),
)
def test_streaming_command_closes_owned_pipes_after_terminal_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
    expected_returncode: int,
) -> None:
    tracked = _track_owned_pipes(monkeypatch)
    result = run_streamed_command(
        command,
        cwd=tmp_path,
        label_key="gate",
        label="terminal-exit",
        progress_prefix="[test]",
        heartbeat_interval=0.03,
        task_registry_path=tmp_path / "task-registry.json",
    )

    assert result.returncode == expected_returncode
    _assert_all_pipes_closed(tracked)


def test_streaming_command_closes_owned_pipes_after_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracked = _track_owned_pipes(monkeypatch)
    result = run_streamed_command(
        _sleep_command(5),
        cwd=tmp_path,
        label_key="gate",
        label="timeout",
        progress_prefix="[test]",
        heartbeat_interval=0.03,
        timeout_seconds=0.12,
        task_registry_path=tmp_path / "task-registry.json",
    )

    assert result.returncode == 124
    assert result.timed_out is True
    _assert_all_pipes_closed(tracked)


def test_streaming_command_closes_owned_pipes_after_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracked = _track_owned_pipes(monkeypatch)
    cancel_event = threading.Event()
    outcome: list[BaseException] = []

    def invoke() -> None:
        try:
            run_streamed_command(
                _sleep_command(5),
                cwd=tmp_path,
                label_key="gate",
                label="cancel",
                progress_prefix="[test]",
                heartbeat_interval=0.03,
                task_registry_path=tmp_path / "task-registry.json",
                cancel_event=cancel_event,
            )
        except BaseException as error:
            outcome.append(error)

    runner = threading.Thread(target=invoke)
    runner.start()
    deadline = time.monotonic() + 2
    while len(tracked) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(tracked) == 2
    cancel_event.set()
    runner.join(timeout=7)

    assert not runner.is_alive()
    assert len(outcome) == 1
    assert isinstance(outcome[0], CommandCancelled)
    _assert_all_pipes_closed(tracked)


def test_cleanup_rejects_every_unsafe_shape_without_signalling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "task-registry.json"
    registry = TaskRegistry(
        state_path,
        session_id="owner-session",
        worktree=tmp_path,
    )
    identity = process_start_identity(os.getpid())
    assert identity
    task = registry.start(command=["python", "safe"])
    pid = os.getpid()
    pgid = os.getpgid(pid)
    registry.bind_process(task["task_id"], pid=pid, pgid=pgid, start_identity=identity)

    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "task_registry.os.killpg",
        lambda group, sig: signals.append((group, sig)),
    )

    cases = [
        ("live-heartbeat", dict(now=None, heartbeat_at=None)),
        ("different-session", dict(session_id="other-session")),
        ("pid-reuse", dict(expected_start_identity="different-start")),
        ("pgid-mismatch", dict(expected_pgid=pgid + 1)),
    ]
    for reason, overrides in cases:
        if reason == "live-heartbeat":
            result = registry.cleanup(
                task["task_id"],
                owner_session="owner-session",
                owner_worktree=tmp_path,
                expected_pid=pid,
                expected_pgid=pgid,
                expected_start_identity=identity,
                stale_after=3600,
                dry_run=False,
            )
        else:
            result = registry.cleanup(
                task["task_id"],
                owner_session=overrides.get("session_id", "owner-session"),
                owner_worktree=tmp_path,
                expected_pid=pid,
                expected_pgid=overrides.get("expected_pgid", pgid),
                expected_start_identity=overrides.get(
                    "expected_start_identity", identity
                ),
                stale_after=0,
                dry_run=False,
            )
        assert result["allowed"] is False, reason
        assert result["reason"] == reason, result

    unknown = registry.cleanup(
        "missing-task",
        owner_session="owner-session",
        owner_worktree=tmp_path,
        expected_pid=pid,
        expected_pgid=pgid,
        expected_start_identity=identity,
        stale_after=0,
        dry_run=False,
    )
    assert unknown["reason"] == "unknown-task"

    registry.finish(task["task_id"], returncode=0)
    finished = registry.cleanup(
        task["task_id"],
        owner_session="owner-session",
        owner_worktree=tmp_path,
        expected_pid=pid,
        expected_pgid=pgid,
        expected_start_identity=identity,
        stale_after=0,
        dry_run=False,
    )
    assert finished["reason"] == "finished-task"
    assert signals == []


def test_dry_run_stale_cleanup_does_not_signal_or_finish(tmp_path: Path) -> None:
    state_path = tmp_path / "task-registry.json"
    registry = TaskRegistry(
        state_path,
        session_id="owner-session",
        worktree=tmp_path,
    )
    child = subprocess.Popen(_sleep_command(5), start_new_session=True)
    try:
        identity = process_start_identity(child.pid)
        assert identity
        task = registry.start(command=["python", "sleep"], log_path=tmp_path / "x.log")
        registry.bind_process(
            task["task_id"],
            pid=child.pid,
            pgid=os.getpgid(child.pid),
            start_identity=identity,
        )
        registry.heartbeat(task["task_id"], phase="heartbeat", at=_old_timestamp())

        result = registry.cleanup(
            task["task_id"],
            owner_session="owner-session",
            owner_worktree=tmp_path,
            expected_pid=child.pid,
            expected_pgid=os.getpgid(child.pid),
            expected_start_identity=identity,
            stale_after=1,
            dry_run=True,
            now="2020-01-01T00:00:00+00:00",
        )
        assert result["allowed"] is True
        assert result["dry_run"] is True
        assert result["signals"] == []
        assert child.poll() is None
        assert TaskRegistry.load(state_path)["records"][0]["status"] == "active"
    finally:
        child.terminate()
        child.wait(timeout=2)


def test_stale_owned_cleanup_only_terminates_named_group_and_records_outcome(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "task-registry.json"
    registry = TaskRegistry(
        state_path,
        session_id="owner-session",
        worktree=tmp_path,
    )
    owner = subprocess.Popen(_sleep_command(5), start_new_session=True)
    unrelated = subprocess.Popen(_sleep_command(5), start_new_session=True)
    try:
        owner_identity = process_start_identity(owner.pid)
        assert owner_identity
        owner_pgid = os.getpgid(owner.pid)
        task = registry.start(command=["python", "owner-task"])
        registry.bind_process(
            task["task_id"],
            pid=owner.pid,
            pgid=owner_pgid,
            start_identity=owner_identity,
        )
        registry.heartbeat(task["task_id"], phase="heartbeat", at=_old_timestamp())

        result = registry.cleanup(
            task["task_id"],
            owner_session="owner-session",
            owner_worktree=tmp_path,
            expected_pid=owner.pid,
            expected_pgid=owner_pgid,
            expected_start_identity=owner_identity,
            stale_after=1,
            dry_run=False,
            now="2020-01-01T00:00:00+00:00",
            term_timeout=0.5,
        )
        assert result["allowed"] is True
        assert result["dry_run"] is False
        assert result["signals"] == ["TERM"]
        assert owner.wait(timeout=2) is not None
        assert unrelated.poll() is None

        record = TaskRegistry.load(state_path)["records"][0]
        assert record["status"] == "finished"
        assert record["phase"] == "finished"
        assert record["terminal_outcome"] == "stale-cleanup:TERM"
        assert record["cleanup"]["pgid"] == owner_pgid
    finally:
        if owner.poll() is None:
            owner.kill()
        if unrelated.poll() is None:
            unrelated.kill()
        owner.wait(timeout=2)
        unrelated.wait(timeout=2)


def test_two_parallel_streaming_commands_finish_without_lost_ledger_rows(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "task-registry.json"

    def run(index: int) -> int:
        result = run_streamed_command(
            [
                sys.executable,
                "-c",
                "import sys,time; print('tick'); sys.stdout.flush(); time.sleep(.18)",
            ],
            cwd=tmp_path,
            label_key="gate",
            label=f"parallel-{index}",
            progress_prefix="[test]",
            heartbeat_interval=0.04,
            task_registry_path=state_path,
            task_session_id="parallel-session",
        )
        return result.returncode

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, (1, 2))) == [0, 0]

    records = TaskRegistry.load(state_path)["records"]
    assert len(records) == 2
    assert all(record["status"] == "finished" for record in records)
    assert all(record["heartbeat_at"] != record["started_at"] for record in records)
