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
"""Agent-stage `claude -p` runner: real timeouts, no stderr deadlock, spend cap (#2095).

Stream-json is the default (PODCAST_VERBOSE=1) and what the dashboard forces. The
old runner read stdout to EOF *before* calling ``proc.wait(timeout=...)``, so the
timeout could only fire after the agent had already exited, and it left stderr in
an unread pipe — a child that wrote more than the pipe buffer blocked forever while
the pipeline blocked on its stdout. The tests below drive the REAL runner against
real child processes (the stage tests stub ``_run_claude_with_retry``, which is why
none of this was ever exercised):

  * a hung child whose grandchild keeps stdout open is killed — the whole process
    group — within timeout+5s, in both stream and plain mode;
  * 200 KB / 1 MB of stderr completes instead of deadlocking;
  * the dashboard's ``killpg`` on the pipeline's group still stops the agent, now
    that the agent runs in its own group;
  * every agent command carries ``--max-budget-usd`` and hitting it is fatal.

Run:
    cd lab/podcast && uv run test_agent_subprocess.py
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import pipeline

_HERE = Path(__file__).resolve().parent
_TIMEOUT_S = 2
_CHILD_SLEEP_S = 15  # how long a "hung" child would run if nobody killed it

# Prints one stream-json event, starts a grandchild that inherits stdout+stderr
# (so killing only the direct child would leave the pipes open), records both
# PIDs, then hangs.
_HANG_CHILD = f"""
import json, os, subprocess, sys, time
from pathlib import Path
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep({_CHILD_SLEEP_S})"])
Path(sys.argv[1]).write_text(f"{{os.getpid()}} {{grandchild.pid}}")
print(json.dumps({{"type": "system", "subtype": "init", "cwd": "."}}), flush=True)
time.sleep({_CHILD_SLEEP_S})
"""

# Floods stderr before closing stdout — the order that deadlocks a reader that
# only drains stdout — then reports success.
_STDERR_CHILD = """
import json, os, sys
from pathlib import Path
Path(sys.argv[1]).write_text(str(os.getpid()))
sys.stderr.write("x" * int(sys.argv[2]))
sys.stderr.flush()
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok"}), flush=True)
"""

# The terminal result event the installed CLI (claude 2.1.226) actually emits when
# --max-budget-usd is exhausted, captured from a real `claude -p` run: exit code 1,
# empty stderr, no "result" field — the reason lives in "errors".
_BUDGET_RESULT = {
    "type": "result",
    "subtype": "error_max_budget_usd",
    "is_error": True,
    "num_turns": 1,
    "total_cost_usd": 0.043337,
    "terminal_reason": "budget_exhausted",
    "errors": ["Reached maximum budget ($0.000001)"],
}
_BUDGET_CHILD = f"""
import json, sys
print(json.dumps({_BUDGET_RESULT!r}), flush=True)
sys.exit(1)
"""


class _FakeLog:
    def __init__(self):
        self.errors: list[str] = []
        self.events: list[str] = []

    def event(self, msg, **kw):
        self.events.append(msg)

    def error(self, msg, **kw):
        self.errors.append(msg)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_dead(pid: int, within_s: float) -> bool:
    """A killed grandchild is reaped by launchd/init, not by us: poll briefly."""
    deadline = time.monotonic() + within_s
    while _alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def _read_pids(path: Path, within_s: float = 10) -> list[int]:
    deadline = time.monotonic() + within_s
    while not (path.exists() and path.read_text().strip()):
        if time.monotonic() >= deadline:
            raise AssertionError(f"positive control: child never wrote {path}")
        time.sleep(0.05)
    return [int(p) for p in path.read_text().split()]


@pytest.fixture
def reap():
    """SIGKILL anything a failing assertion left running (pids read from files)."""
    pidfiles: list[Path] = []
    yield pidfiles.append
    for pidfile in pidfiles:
        if pidfile.exists() and pidfile.read_text().strip():
            for pid in (int(p) for p in pidfile.read_text().split()):
                if _alive(pid):
                    os.kill(pid, signal.SIGKILL)


def _run(cmd: list[str], ws: Path, log: _FakeLog, timeout: int):
    t0 = time.monotonic()
    ok, _elapsed, failure = pipeline._run_claude_subprocess(
        cmd, ws, "Analyst", log, timeout, prompt="hello"
    )
    return ok, failure, time.monotonic() - t0


@pytest.mark.parametrize("stream", [True, False], ids=["stream-json", "plain"])
def test_hung_agent_group_is_killed_within_timeout(tmp_path, monkeypatch, reap, stream):
    monkeypatch.setattr(pipeline, "_STREAM_JSON", stream)
    pidfile = tmp_path / "hang.pids"
    reap(pidfile)
    log = _FakeLog()

    ok, failure, elapsed = _run(
        [sys.executable, "-c", _HANG_CHILD, str(pidfile)], tmp_path, log, _TIMEOUT_S
    )

    child, grandchild = _read_pids(pidfile)
    assert ok is False, "a hung agent must fail the stage"
    assert failure is not None and failure.status == "timeout", failure
    assert elapsed < _TIMEOUT_S + 5, f"runner blocked {elapsed:.1f}s on a hung agent"
    assert f"Analyst TIMEOUT after {_TIMEOUT_S}s" in log.errors, log.errors
    assert not _alive(child), "agent still running after the timeout"
    assert _wait_dead(grandchild, 2), "agent's subprocess survived — group not killed"
    if stream:
        events = (tmp_path / "events.jsonl").read_text().splitlines()
        assert json.loads(events[0])["event"]["subtype"] == "init", (
            "events emitted before the hang must still reach events.jsonl"
        )


@pytest.mark.parametrize("stderr_bytes", [200_000, 1_000_000], ids=["200KB", "1MB"])
def test_large_stderr_does_not_deadlock(tmp_path, monkeypatch, reap, stderr_bytes):
    monkeypatch.setattr(pipeline, "_STREAM_JSON", True)
    pidfile = tmp_path / "flood.pid"
    reap(pidfile)
    watchdog_s = 10

    def _watchdog():
        # The pre-fix runner deadlocks here forever; kill the child so the red run
        # ends (as a failure) instead of hanging the suite.
        if pidfile.exists() and pidfile.read_text().strip():
            os.kill(int(pidfile.read_text()), signal.SIGKILL)

    timer = threading.Timer(watchdog_s, _watchdog)
    timer.start()
    try:
        ok, failure, elapsed = _run(
            [sys.executable, "-c", _STDERR_CHILD, str(pidfile), str(stderr_bytes)],
            tmp_path,
            _FakeLog(),
            60,
        )
    finally:
        timer.cancel()

    assert elapsed < watchdog_s, f"deadlocked on {stderr_bytes} B of stderr"
    assert ok is True, failure


_EVENTS = [
    {"type": "system", "subtype": "init", "cwd": "."},
    {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]},
    },
    {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.5},
]
_EVENTS_CHILD = f"""
import json
for event in {_EVENTS!r}:
    print(json.dumps(event), flush=True)
"""


@pytest.mark.parametrize(
    "child", [_EVENTS_CHILD, "pass"], ids=["three-events", "no-output"]
)
def test_every_stream_event_is_teed(tmp_path, monkeypatch, child):
    """Every stdout event — not just the last line — must reach events.jsonl (the
    dashboard's live tool feed + cost source), and an agent that prints nothing
    is a clean result, not a crash."""
    monkeypatch.setattr(pipeline, "_STREAM_JSON", True)

    ok, failure, _ = _run([sys.executable, "-c", child], tmp_path, _FakeLog(), 30)

    assert ok is True, failure
    events_file = tmp_path / "events.jsonl"
    teed = [json.loads(l)["event"] for l in events_file.read_text().splitlines()]
    assert teed == (_EVENTS if child == _EVENTS_CHILD else [])


_FORWARD_HELPER = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import pipeline

class _Log:
    def event(self, *a, **k): pass
    def error(self, *a, **k): pass

pipeline._STREAM_JSON = True
ws = Path(sys.argv[2])
pipeline._run_claude_subprocess(
    [sys.executable, "-c", sys.argv[3], str(ws / "hang.pids")], ws, "Analyst", _Log(), 120
)
"""


@pytest.mark.parametrize(
    "sig", [signal.SIGTERM, signal.SIGHUP, signal.SIGINT], ids=["TERM", "HUP", "INT"]
)
def test_signal_to_pipeline_group_still_stops_agent(tmp_path, reap, sig):
    """The dashboard stops a job with killpg(<pipeline group>, SIGTERM) and a
    terminal sends SIGINT/SIGHUP to the pipeline's group. The agent now lives in
    its own group (so a timeout can kill its whole tree); it must still die."""
    pidfile = tmp_path / "hang.pids"
    reap(pidfile)
    helper = subprocess.Popen(
        [sys.executable, "-c", _FORWARD_HELPER, str(_HERE), str(tmp_path), _HANG_CHILD],
        start_new_session=True,  # like monitor/jobs.py
    )
    try:
        child, grandchild = _read_pids(pidfile)
        os.killpg(helper.pid, sig)
        helper.wait(timeout=10)
    finally:
        if helper.poll() is None:
            os.killpg(helper.pid, signal.SIGKILL)
            helper.wait()

    assert _wait_dead(child, 5), f"agent survived {sig.name} to the pipeline group"
    assert _wait_dead(grandchild, 5), "agent's subprocess survived"


def test_budget_exhausted_is_a_fatal_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_STREAM_JSON", True)
    log = _FakeLog()

    ok, failure, _ = _run([sys.executable, "-c", _BUDGET_CHILD], tmp_path, log, 30)

    assert ok is False
    assert failure.status == "budget", failure
    assert "Reached maximum budget" in failure.reason, failure
    assert (
        pipeline._is_retryable_claude_failure(failure.status, failure.reason) is False
    )


def test_budget_failure_is_not_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_STREAM_JSON", True)
    monkeypatch.setattr(pipeline, "_STAGE_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(pipeline.time, "sleep", lambda *_: None)
    calls = tmp_path / "calls"
    child = f"open({str(calls)!r}, 'a').write('x')\n" + _BUDGET_CHILD

    ok, _ = pipeline._run_claude_with_retry(
        [sys.executable, "-c", child], tmp_path, "Analyst", _FakeLog(), 30
    )

    assert ok is False
    assert calls.read_text() == "x", "a spend-cap hit must not start a fresh agent"


def _budget_arg(cmd: list[str]) -> str | None:
    return cmd[cmd.index("--max-budget-usd") + 1] if "--max-budget-usd" in cmd else None


def _capture_cmds(monkeypatch) -> list[tuple[str, list[str]]]:
    seen: list[tuple[str, list[str]]] = []

    def fake_retry(cmd, workspace, label, log, timeout, prompt=None):
        seen.append((label, list(cmd)))
        return True, 0.0

    monkeypatch.setattr(pipeline, "_run_claude_with_retry", fake_retry)
    return seen


def test_every_agent_command_carries_its_stage_spend_cap(tmp_path, monkeypatch):
    monkeypatch.delenv("PODCAST_STAGE_MAX_BUDGET_USD", raising=False)
    seen = _capture_cmds(monkeypatch)
    ws = tmp_path / "ws"
    ws.mkdir()

    pipeline.run_claude("prompt", ws, "Analyst", _FakeLog())
    pipeline.run_claude("prompt", ws, "Prep", _FakeLog())
    pipeline.run_scriptwriter(ws, 1)
    pipeline.run_script_reviewer(ws, 1)

    caps = {label: _budget_arg(cmd) for label, cmd in seen}
    assert caps == {
        "Analyst": f"{pipeline._STAGE_BUDGETS_USD['Analyst']:g}",
        "Prep": f"{pipeline._DEFAULT_BUDGET_USD:g}",
        "Scriptwriter EP1": f"{pipeline._STAGE_BUDGETS_USD['Scriptwriter']:g}",
        "Script Review EP1": f"{pipeline._STAGE_BUDGETS_USD['Script Review']:g}",
    }


def test_spend_cap_env_overrides_and_zero_disables(tmp_path, monkeypatch):
    seen = _capture_cmds(monkeypatch)
    ws = tmp_path / "ws"
    ws.mkdir()

    monkeypatch.setenv("PODCAST_STAGE_MAX_BUDGET_USD", "2.5")
    pipeline.run_claude("prompt", ws, "Analyst", _FakeLog())
    monkeypatch.setenv("PODCAST_STAGE_MAX_BUDGET_USD", "0")
    pipeline.run_claude("prompt", ws, "Analyst", _FakeLog())

    assert _budget_arg(seen[0][1]) == "2.5"
    assert "--max-budget-usd" not in seen[1][1]


@pytest.mark.parametrize("value", ["abc", "-1"])
def test_invalid_spend_cap_env_is_rejected(monkeypatch, value):
    monkeypatch.setenv("PODCAST_STAGE_MAX_BUDGET_USD", value)
    with pytest.raises(ValueError, match="PODCAST_STAGE_MAX_BUDGET_USD"):
        pipeline._stage_budget_usd("Analyst")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
