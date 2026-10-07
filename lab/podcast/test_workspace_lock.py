#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "boto3",
#     "pytest",
# ]
# ///
"""One pipeline per workspace, enforced by the pipeline itself (#2099).

The dashboard's one-job-per-workspace guard lived only in its in-memory job map,
and jobs are spawned in their own session so they outlive a server restart: after
a restart (or from the CLI) a second `pipeline.py` could start on a workspace a
first one was still writing, colliding on markers, scripts/.cache, events.jsonl
and the fixed `.part` / `.tmp` temp names. `pipeline.py` now holds an exclusive
flock on `<ws>/.pipeline.lock` (recording its PID in the file) for its whole run.

The holder here is a separate process taking a raw flock — the on-disk protocol
the dashboard probes — not the implementation under test.

Run:
    cd lab/podcast && uv run test_workspace_lock.py
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import subprocess
import sys
from pathlib import Path

import pytest

import pipeline

_HOLDER = """
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)
fcntl.flock(fd, fcntl.LOCK_EX)
os.ftruncate(fd, 0)
os.write(fd, f"{os.getpid()}\\n".encode())
print("locked", flush=True)
sys.stdin.read()  # hold until the test closes our stdin
"""


@pytest.fixture
def workspace(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(pipeline, "_DASHBOARD_ENABLED", False)
    monkeypatch.delenv("PODCAST_JOB_ID", raising=False)
    ws = tmp_path / "book_0123abcd"
    ws.mkdir()
    (ws / "log.md").write_text("# Podcast Pipeline Log\n")
    return ws


@contextlib.contextmanager
def _held(lock_path: Path):
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "locked", "positive control: no lock"
        yield proc
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


@pytest.fixture
def holder(workspace):
    with _held(workspace / ".pipeline.lock") as proc:
        yield proc


def _state_files(ws: Path) -> set[str]:
    return {p.name for p in ws.iterdir()} - {"log.md", ".pipeline.lock"}


def _main(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["pipeline.py", *argv])
    pipeline.main()


def test_second_run_on_locked_workspace_exits_naming_the_holder(
    workspace, holder, monkeypatch, capsys
):
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, str(workspace), "--dry-run")

    assert exc.value.code not in (0, None)
    assert f"PID {holder.pid}" in capsys.readouterr().err
    assert _state_files(workspace) == set(), (
        "a refused run must not write any workspace state"
    )


def test_fresh_epub_run_takes_the_lock_before_setup_writes(
    tmp_path, monkeypatch, capsys
):
    """An EPUB target creates its workspace in-process: the lock must be taken on
    the deterministic workspace path before setup_workspace writes chapters."""
    monkeypatch.setattr(pipeline, "_DASHBOARD_ENABLED", False)
    monkeypatch.setattr(pipeline, "WORKSPACES_DIR", tmp_path / "workspaces")
    meta = {
        "title": "Some Book",
        "author": "Someone",
        "language": "en",
        "total_raw_chapters": 1,
        "total_raw_chars": 4,
    }
    monkeypatch.setattr(pipeline, "extract_epub", lambda _p: (meta, [("c1", "text")]))
    ws = (
        tmp_path
        / "workspaces"
        / pipeline.book_workspace_dirname("Some Book", "Someone")
    )
    ws.mkdir(parents=True)
    book = tmp_path / "book.epub"
    book.write_text("x")

    with _held(ws / ".pipeline.lock") as proc:
        with pytest.raises(SystemExit) as exc:
            _main(monkeypatch, str(book), "--dry-run")

    assert exc.value.code not in (0, None)
    assert f"PID {proc.pid}" in capsys.readouterr().err
    assert _state_files(ws) == set(), "setup_workspace ran on a locked workspace"


def test_status_is_read_only_and_works_while_locked(
    workspace, holder, monkeypatch, capsys
):
    _main(monkeypatch, str(workspace), "--status")

    assert "WORKSPACE: book_0123abcd" in capsys.readouterr().out
    assert _state_files(workspace) == set()


def test_lock_is_released_when_the_run_ends(workspace, monkeypatch):
    _main(monkeypatch, str(workspace), "--dry-run")
    _main(monkeypatch, str(workspace), "--dry-run")  # same process: no self-lock

    lock = workspace / ".pipeline.lock"
    fd = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if still held
    finally:
        os.close(fd)


def test_a_run_holds_the_lock_and_records_its_pid(workspace, monkeypatch):
    """While main() runs, the lock is held and the file names this process."""
    seen: dict[str, object] = {}

    def probe(_ws):
        fd = os.open(workspace / ".pipeline.lock", os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        seen["pid"] = (workspace / ".pipeline.lock").read_text().strip()

    # --dry-run ends in show_status(workspace): probe the lock from there.
    monkeypatch.setattr(pipeline, "show_status", probe)
    _main(monkeypatch, str(workspace), "--dry-run")

    assert seen["pid"] == str(os.getpid())


def test_concurrent_cli_runs_one_wins(workspace, tmp_path):
    """Two real pipeline processes started together: exactly one gets the lock."""
    script = tmp_path / "hold_run.py"
    script.write_text(
        "import sys, time\n"
        f"sys.path.insert(0, {str(Path(pipeline.__file__).parent)!r})\n"
        "import pipeline\n"
        "pipeline._DASHBOARD_ENABLED = False\n"
        "pipeline.show_status = lambda ws: time.sleep(5)\n"
        "sys.argv = ['pipeline.py', sys.argv[1], '--dry-run']\n"
        "pipeline.main()\n"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, str(script), str(workspace)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results = [(p.wait(timeout=60), p.stderr.read()) for p in procs]

    codes = sorted(rc for rc, _ in results)
    assert codes[0] == 0 and codes[1] != 0, results
    loser_err = next(err for rc, err in results if rc != 0)
    winner_pid = next(p.pid for p, (rc, _) in zip(procs, results) if rc == 0)
    assert f"PID {winner_pid}" in loser_err, loser_err


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
