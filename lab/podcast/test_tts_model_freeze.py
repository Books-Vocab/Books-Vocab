#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "pytest",
# ]
# ///
"""TTS model is frozen at workspace creation and restored at the single point
every spawn path funnels through — `stage_synthesize`. Because /start, /resume,
/approve and a manual `--skip-to synthesize` all reach synthesis via this one
function, testing it here proves the restore happens on every path (no per-
endpoint env injection to drift out of sync).

Run:
    cd lab/podcast && uv run test_tts_model_freeze.py
"""
from __future__ import annotations

import types

import pytest

import pipeline


class _FakeLog:
    def __init__(self):
        self.events: list[str] = []

    def event(self, msg, **kw):
        self.events.append(msg)

    def error(self, msg, **kw):
        self.events.append(f"ERROR: {msg}")


@pytest.fixture
def captured_env(monkeypatch):
    """Replace subprocess.run inside pipeline with a recorder returning rc=0."""
    box = {}

    def fake_run(cmd, **kwargs):
        box["cmd"] = cmd
        box["env"] = kwargs.get("env")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    return box


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "scripts").mkdir(parents=True)
    return ws


def test_tts_family_extraction():
    assert pipeline.tts_family("gemini-3.1-flash-tts-preview") == "3.1"
    assert pipeline.tts_family("gemini-2.5-pro-tts") == "2.5"
    assert pipeline.tts_family("opaque-id") == "opaque-id"


def test_synthesize_injects_frozen_tts_model(tmp_path, captured_env):
    ws = _ws(tmp_path)
    (ws / pipeline._TTS_MODEL_SIDECAR).write_text("gemini-2.5-pro-tts")

    assert pipeline.stage_synthesize(ws, _FakeLog()) is True
    assert captured_env["env"]["TTS_MODEL"] == "gemini-2.5-pro-tts"


def test_synthesize_no_sidecar_leaves_env_default(tmp_path, captured_env):
    ws = _ws(tmp_path)  # no .tts_model sidecar

    assert pipeline.stage_synthesize(ws, _FakeLog()) is True
    # Falls through to synthesize.py's own TTS_MODEL env default — pipeline must
    # not inject one. The base _UNBUF_ENV may inherit an ambient TTS_MODEL, but
    # pipeline itself adds nothing, so the value equals whatever os.environ had.
    assert captured_env["env"] is pipeline._UNBUF_ENV


def test_synthesize_warns_on_cross_family_mismatch(tmp_path, captured_env):
    ws = _ws(tmp_path)
    (ws / pipeline._TTS_MODEL_SIDECAR).write_text("gemini-2.5-pro-tts")
    (ws / pipeline._SCRIPT_TTS_FAMILY_SIDECAR).write_text("3.1")

    log = _FakeLog()
    pipeline.stage_synthesize(ws, log)
    assert any("mismatch" in m for m in log.events), log.events


def test_synthesize_no_warn_when_families_match(tmp_path, captured_env):
    ws = _ws(tmp_path)
    (ws / pipeline._TTS_MODEL_SIDECAR).write_text("gemini-3.1-flash-tts-preview")
    (ws / pipeline._SCRIPT_TTS_FAMILY_SIDECAR).write_text("3.1")

    log = _FakeLog()
    pipeline.stage_synthesize(ws, log)
    assert not any("mismatch" in m for m in log.events), log.events


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
