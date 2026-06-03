#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pytest",
# ]
# ///
"""Regression: a .m4a target must be classified as audio, not script.

根因：find_audio()（subtitle.py）優先找 `.m4a`（Track-B 後 TTS 預設輸出），
但 main() 單檔分支舊版只認 `{".mp3", ".wav"}`。直接把 `ep_1_pro.m4a` 當 target
傳 → 落 else 分支被當 script → script_to_segments 讀二進位音檔亂解析。

本測試鎖兩件事：
(a) is_audio_target() 對 .m4a/.mp3/.wav 回 True，對 .md 回 False（副檔名分類）；
(b) resolve_script_for_audio() 能由 `ep_1_pro.m4a` 推回 `ep_1_script.md`
    （_pro/_flash 後綴剝除正確）。

deferred import 後 subtitle 模組可在無 stable-ts 下 import；保留 stub 以防萬一。
"""
import sys
import types
from pathlib import Path

# subtitle.py 已將 stable_whisper 改為 deferred import；stub 僅作保險。
sys.modules.setdefault("stable_whisper", types.ModuleType("stable_whisper"))

import subtitle  # noqa: E402


def test_m4a_is_audio_target():
    assert subtitle.is_audio_target(Path("ep_1_pro.m4a")) is True


def test_mp3_wav_still_audio_target():
    assert subtitle.is_audio_target(Path("ep_1_pro.mp3")) is True
    assert subtitle.is_audio_target(Path("ep_1.wav")) is True


def test_uppercase_suffix_classified():
    assert subtitle.is_audio_target(Path("EP_1_PRO.M4A")) is True


def test_md_is_not_audio_target():
    assert subtitle.is_audio_target(Path("ep_1_script.md")) is False
    assert subtitle.is_audio_target(Path("ep_1.md")) is False


def test_m4a_resolves_to_script_stripping_pro_suffix(tmp_path):
    script = tmp_path / "ep_1_script.md"
    script.write_text("Speaker A: hello\n")
    audio = tmp_path / "ep_1_pro.m4a"
    audio.write_bytes(b"\x00\x00")  # binary audio — must NOT be parsed as script
    assert subtitle.resolve_script_for_audio(audio) == script


def test_m4a_resolves_flash_suffix_and_bare_md(tmp_path):
    script = tmp_path / "ep_2.md"
    script.write_text("Speaker A: hi\n")
    audio = tmp_path / "ep_2_flash.m4a"
    audio.write_bytes(b"\x00")
    assert subtitle.resolve_script_for_audio(audio) == script


def test_resolve_returns_none_when_no_script(tmp_path):
    audio = tmp_path / "ep_9_pro.m4a"
    audio.write_bytes(b"\x00")
    assert subtitle.resolve_script_for_audio(audio) is None
