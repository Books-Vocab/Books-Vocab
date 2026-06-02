#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pytest",
# ]
# ///
"""Regression test: write_compact_srt must loud-warn on speaker-map desync.

根因：build_word_speaker_map（subtitle.py :100-106）以 Python `str.split()`
（空白切詞）建 `word_speakers`；write_compact_srt 卻迭代 whisper `seg.words`
（stable-ts 對標點/連字/縮寫重新分詞，token 數通常 > str.split()）。:174 的
`word_speakers[i] if i < len else ""` 從首個分詞背離點起 speaker tag 全錯位、
尾段空 tag，且**零 assertion/warning = silent corruption**。

本 track scope：**只**加觀測 guard（loud-warn），不改對映演算法/輸出。本測試
驗證：(a) whisper word 數 ≠ word_speakers 長度時發出 warning（caplog 捕捉）；
(b) 不拋例外、仍照現狀產出 srt（輸出行為不變）。

避免真跑 whisper：以 sys.modules stub `stable_whisper`，並用 fake word/seg 物件。
"""
import sys
import types
from pathlib import Path

import pytest

# subtitle.py 在 module top `import stable_whisper`（重量級 dep，測試環境無）。
# 在 import subtitle 之前注入 stub，避免拉 stable-ts。
sys.modules.setdefault("stable_whisper", types.ModuleType("stable_whisper"))

import subtitle  # noqa: E402


class _FakeWord:
    def __init__(self, word: str, start: float, end: float):
        self.word = word
        self.start = start
        self.end = end


class _FakeSeg:
    def __init__(self, words):
        self.words = words


class _FakeResult:
    def __init__(self, segments):
        self.segments = segments


def _whisper_words(tokens):
    """Build a fake whisper result with one segment of contiguous tokens."""
    words = [_FakeWord(t, float(i), float(i + 1)) for i, t in enumerate(tokens)]
    return _FakeResult([_FakeSeg(words)])


def test_desync_emits_warning_and_still_writes_srt(tmp_path, caplog):
    # word_speakers 來自 str.split()：2 段、各 2 詞 = 4 個 tag
    segments = [("Speaker1", "hello world"), ("Speaker2", "foo bar")]
    word_speakers = subtitle.build_word_speaker_map(segments)
    assert len(word_speakers) == 4

    # whisper 重新分詞成 6 個 token（模擬標點/縮寫被拆）= 背離
    result = _whisper_words(["hello", "world", ",", "foo", "bar", "."])

    srt_path = tmp_path / "ep_test_pro.srt"

    with caplog.at_level("WARNING"):
        subtitle.write_compact_srt(srt_path, result, word_speakers)

    # (a) 必須發出 loud warning，且訊息含差異數量資訊
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings, "expected a desync WARNING but none was emitted"
    msg = " ".join(r.getMessage() for r in warnings).lower()
    assert "speaker" in msg
    assert "6" in msg and "4" in msg  # whisper word 數 vs word_speakers 長度

    # (b) 不拋例外、仍照現狀產出 srt（6 個 cue，輸出行為不變）
    assert srt_path.exists()
    content = srt_path.read_text(encoding="utf-8")
    assert "[Speaker1] hello" in content
    # 尾段超出 word_speakers 長度者仍為空 tag（現狀輸出，不改）
    assert content.count("-->") == 6


def test_no_warning_when_counts_match(tmp_path, caplog):
    segments = [("Speaker1", "hello world"), ("Speaker2", "foo bar")]
    word_speakers = subtitle.build_word_speaker_map(segments)  # 4
    result = _whisper_words(["hello", "world", "foo", "bar"])  # 4 — 對齊

    srt_path = tmp_path / "ep_ok_pro.srt"
    with caplog.at_level("WARNING"):
        subtitle.write_compact_srt(srt_path, result, word_speakers)

    assert not [r for r in caplog.records if r.levelname == "WARNING"]
    assert srt_path.exists()
