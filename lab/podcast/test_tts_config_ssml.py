#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest"]
# ///
"""SSML_RE 必須剝除【完整】legacy SSML 標籤（含收尾 '>'）。

回歸守門：char-class 漏掉收尾 '>'（`<[^>]+` 而非 `<[^>]+>`）會在
subtitle._clean_spoken / audio_qa 清理後殘留 '>'（user-visible 字幕雜訊 +
污染 wpm word-count）。舊 workspace 殘留 SSML 才觸發，靜默無覆蓋。

Run:
    cd lab/podcast && uv run test_tts_config_ssml.py
"""
from __future__ import annotations

import pytest

from tts_config import SSML_RE


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("<break>foo</break>", "foo"),
        ("<speak>hi</speak>", "hi"),
        ('<break time="500ms"/>pause', "pause"),
        ("no tags here", "no tags here"),
        ("a<b>c</b>d", "acd"),
    ],
)
def test_ssml_re_strips_full_tags(raw, expected):
    assert SSML_RE.sub("", raw) == expected


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
