#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "pytest",
# ]
# ///
"""單集 scriptwriter 路徑必須寫 .script_tts_family sidecar。

根因:stage_scriptwriters(only_episode=N) 早 return 前不寫 .script_tts_family
(只全量路徑寫)。純靠 --only-episode 建稿的 ws 永缺 sidecar →
stage_synthesize 預設 "3.1" → 跨-family mismatch 噪音(backstop 仍保安全,
僅 informational)。

契約:單集成功 return 前也寫 resolve_tts_family(workspace),與全量路徑一致;
單集失敗則不寫(無稿不該宣稱 family)。
"""
from pathlib import Path

import pytest

import pipeline
from pipeline import _SCRIPT_TTS_FAMILY_SIDECAR


class _FakeLog:
    def error(self, m, **k): pass
    def event(self, m, **k): pass


def test_only_episode_success_writes_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "run_scriptwriter", lambda ws, n: (n, True))
    monkeypatch.setattr(pipeline, "resolve_tts_family", lambda ws: "2.5")

    ok = pipeline.stage_scriptwriters(tmp_path, _FakeLog(), only_episode=3)

    assert ok is True
    sidecar = tmp_path / _SCRIPT_TTS_FAMILY_SIDECAR
    assert sidecar.exists(), "single-episode scriptwriter must write .script_tts_family"
    assert sidecar.read_text() == "2.5"


def test_only_episode_failure_does_not_write_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "run_scriptwriter", lambda ws, n: (n, False))
    monkeypatch.setattr(pipeline, "resolve_tts_family", lambda ws: "2.5")

    ok = pipeline.stage_scriptwriters(tmp_path, _FakeLog(), only_episode=3)

    assert ok is False
    assert not (tmp_path / _SCRIPT_TTS_FAMILY_SIDECAR).exists()
