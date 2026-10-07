#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "pytest",
# ]
# ///
"""A hung subprocess stage must fail the stage, not hang the pipeline (#2069).

synthesize / audio-qa / subtitle shell out to `uv run <tool>.py` and publish to
`bash ops/podcast_upload.sh`. A stuck tool (a TTS call that never returns, a
whisper model download stall, a half-dead S3 upload) must hit a wall-clock cap,
log `TIMEOUT`, and leave nothing running behind it.

These tests drive the REAL launchers against fake tools that sleep, because the
launcher is part of the failure mode: `subprocess.run(timeout=...)` SIGKILLs
only its direct child. `uv run` cannot forward SIGKILL (the real tool is
orphaned and keeps spending TTS quota), and a SIGKILLed bash never runs its
EXIT trap (podcast_upload.sh's staging dir leaks).

Run:
    cd lab/podcast && uv run test_tool_stage_timeout.py
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

import pytest

import pipeline

_TOOL_SLEEP_S = 20
_TIMEOUT_S = 4

_FAKE_TOOL = """\
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
import os, signal, time
from pathlib import Path
if {ignore_term}:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(__file__).with_suffix(".pid").write_text(str(os.getpid()))
time.sleep({sleep})
"""

_STAGES = [
    ("stage_synthesize", "synthesize.py", "synthesize"),
    ("stage_audio_qa", "audio_qa.py", "audio-qa"),
    ("stage_subtitle", "subtitle.py", "subtitle"),
]


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


def _workspace(tmp_path: Path, episodes: int) -> Path:
    ws = tmp_path / "ws"
    (ws / "scripts").mkdir(parents=True)
    for n in range(1, episodes + 1):
        (ws / "scripts" / f"ep_{n}_script.md").write_text("Speaker1: hi\n")
    return ws


def _install_fake_tool(
    tmp_path: Path, monkeypatch, tool: str, *, ignore_term: bool = False
) -> Path:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / tool).write_text(
        _FAKE_TOOL.format(sleep=_TOOL_SLEEP_S, ignore_term=ignore_term)
    )
    monkeypatch.setattr(pipeline, "ROOT", tools)
    monkeypatch.setattr(pipeline, "_audio_qa_strict", lambda _ws: False)
    return (tools / tool).with_suffix(".pid")


def _run_stage(stage_fn: str, ws: Path, log: _FakeLog, **kw) -> tuple[bool, float]:
    t0 = time.monotonic()
    ok = getattr(pipeline, stage_fn)(ws, log, **kw)
    return ok, time.monotonic() - t0


@pytest.fixture
def reap():
    """Kill any fake tool a failing assertion (or a SIGKILL fallback) left behind."""
    pidfiles: list[Path] = []
    yield pidfiles.append
    for pidfile in pidfiles:
        if pidfile.exists():
            pid = int(pidfile.read_text())
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)


@pytest.mark.parametrize("stage_fn, tool, stage", _STAGES, ids=[s[2] for s in _STAGES])
def test_hung_tool_times_out_and_is_reaped(
    tmp_path, monkeypatch, reap, stage_fn, tool, stage
):
    pidfile = _install_fake_tool(tmp_path, monkeypatch, tool)
    reap(pidfile)
    monkeypatch.setattr(
        pipeline, "_TOOL_STAGE_TIMEOUTS", {stage: _TIMEOUT_S}, raising=False
    )
    log = _FakeLog()

    ok, elapsed = _run_stage(stage_fn, _workspace(tmp_path, episodes=1), log)

    assert ok is False, "a hung tool must fail the stage"
    assert elapsed < _TOOL_SLEEP_S - 5, f"stage blocked {elapsed:.0f}s on a hung tool"
    assert f"{stage} TIMEOUT after {_TIMEOUT_S}s" in log.errors, log.errors
    assert pidfile.exists(), "positive control: the fake tool never started"
    assert not _alive(int(pidfile.read_text())), (
        "tool still running after the stage gave up"
    )


@pytest.mark.parametrize(
    "episodes, only_episode, expected_s",
    [(2, None, 2 * 3), (3, 1, 3)],
    ids=["whole-series-scales-per-episode", "only-episode-gets-one-budget"],
)
def test_timeout_budget_is_per_episode(
    tmp_path, monkeypatch, reap, episodes, only_episode, expected_s
):
    pidfile = _install_fake_tool(tmp_path, monkeypatch, "synthesize.py")
    reap(pidfile)
    monkeypatch.setattr(
        pipeline, "_TOOL_STAGE_TIMEOUTS", {"synthesize": 3}, raising=False
    )
    log = _FakeLog()

    ok, _ = _run_stage(
        "stage_synthesize",
        _workspace(tmp_path, episodes),
        log,
        only_episode=only_episode,
    )

    assert ok is False
    assert f"synthesize TIMEOUT after {expected_s}s" in log.errors, log.errors


def test_tool_ignoring_sigterm_still_cannot_hang_the_stage(tmp_path, monkeypatch, reap):
    pidfile = _install_fake_tool(tmp_path, monkeypatch, "subtitle.py", ignore_term=True)
    reap(pidfile)
    monkeypatch.setattr(
        pipeline, "_TOOL_STAGE_TIMEOUTS", {"subtitle": _TIMEOUT_S}, raising=False
    )
    monkeypatch.setattr(pipeline, "_TOOL_TERM_GRACE", 1, raising=False)
    log = _FakeLog()

    ok, elapsed = _run_stage("stage_subtitle", _workspace(tmp_path, episodes=1), log)

    assert ok is False
    assert elapsed < _TOOL_SLEEP_S - 5, (
        f"stage blocked {elapsed:.0f}s on a SIGTERM-deaf tool"
    )
    assert f"subtitle TIMEOUT after {_TIMEOUT_S}s" in log.errors, log.errors


_FAKE_UPLOAD = """\
#!/usr/bin/env bash
set -euo pipefail
trap 'echo cleaned > "{marker}"' EXIT
sleep {sleep}
"""


def test_publish_timeout_lets_upload_script_clean_up(tmp_path, monkeypatch):
    """A timed-out publish attempt must SIGTERM (not SIGKILL) podcast_upload.sh so
    its EXIT trap removes the per-run staging dir instead of leaking it."""
    root = tmp_path / "repo" / "lab" / "podcast"
    root.mkdir(parents=True)
    (tmp_path / "repo" / "ops").mkdir()
    marker = tmp_path / "trap_ran"
    (tmp_path / "repo" / "ops" / "podcast_upload.sh").write_text(
        _FAKE_UPLOAD.format(marker=marker, sleep=_TOOL_SLEEP_S)
    )
    monkeypatch.setattr(pipeline, "ROOT", root)
    monkeypatch.setattr(pipeline, "_PUBLISH_TIMEOUT", 2)
    monkeypatch.setenv("PODCAST_BUCKET", "kg-test-bucket")
    ws = tmp_path / "series_x"
    ws.mkdir()
    log = _FakeLog()

    t0 = time.monotonic()
    ok = pipeline.stage_publish(ws, log, max_retries=1)

    assert ok is False
    assert time.monotonic() - t0 < _TOOL_SLEEP_S - 5
    assert marker.exists(), (
        "upload script was killed before its EXIT trap could clean up"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
