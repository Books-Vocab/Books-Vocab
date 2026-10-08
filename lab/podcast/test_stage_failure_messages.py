"""stage_subtitle / stage_audio_qa must surface why a tool stage failed."""

from __future__ import annotations

from pathlib import Path

import pipeline


class _Log:
    def __init__(self):
        self.errors: list[str] = []
        self.events: list[str] = []

    def event(self, msg, **kw):
        self.events.append(msg)

    def error(self, msg, **kw):
        self.errors.append(msg)


def _ws(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    return tmp_path


def test_audio_qa_non_findings_exit_not_reported_as_fail_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_run_tool_stage", lambda *a, **k: 2)
    log = _Log()
    assert pipeline.stage_audio_qa(_ws(tmp_path), log) is False
    assert "exit 2" in log.errors[0]
    assert "FAIL findings" not in log.errors[0]


def test_audio_qa_real_findings_still_reported(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    (ws / "audio_qa.json").write_text("{}")
    monkeypatch.setattr(pipeline, "_run_tool_stage", lambda *a, **k: 1)
    log = _Log()
    assert pipeline.stage_audio_qa(ws, log) is False
    assert "FAIL findings" in log.errors[0]


def test_subtitle_nonzero_exit_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_run_tool_stage", lambda *a, **k: 1)
    log = _Log()
    assert pipeline.stage_subtitle(_ws(tmp_path), log) is False
    assert "subtitle exited 1" in log.errors[0]
