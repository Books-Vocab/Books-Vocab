#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "google-genai",
#     "python-dotenv",
#     "pydub",
#     "audioop-lts",
#     "pytest",
# ]
# ///
"""_parse_loudnorm_json:從 ffmpeg stderr 取 loudnorm 量測 JSON。

根因:原碼用非貪婪 `\\{[\\s\\S]*?\\}` 取第一個 `{...}`,若 stderr 在
loudnorm 區塊前出現任何其他 `{...}`(其他 filter 日誌),會抓錯區塊 →
json 解析失敗或缺 input_i → 不必要地放棄 mastering。改錨定 input_i。

跑法:
  uv run --with google-genai --with python-dotenv --with pydub \\
         --with audioop-lts --with pytest pytest test_synthesize_loudnorm.py -q
"""
from __future__ import annotations

import synthesize as sy

_LOUDNORM = (
    '{\n'
    '    "input_i" : "-18.50",\n'
    '    "input_tp" : "-2.10",\n'
    '    "input_lra" : "7.20",\n'
    '    "input_thresh" : "-28.70",\n'
    '    "output_i" : "-16.00",\n'
    '    "target_offset" : "0.30"\n'
    '}'
)


def test_parses_clean_block():
    params = sy._parse_loudnorm_json(_LOUDNORM)
    assert params is not None
    assert params["input_i"] == "-18.50"
    assert params["target_offset"] == "0.30"


def test_ignores_stray_earlier_brace():
    # A stray {...} (e.g. another ffmpeg filter's log) precedes the loudnorm
    # block; the old non-greedy first-match would grab this and fail.
    stderr = '[Parsed_other] config={mode:fast}\n' + _LOUDNORM
    params = sy._parse_loudnorm_json(stderr)
    assert params is not None
    assert params["input_i"] == "-18.50"


def test_no_block_returns_none():
    assert sy._parse_loudnorm_json("ffmpeg ran but printed no json") is None


def test_malformed_block_returns_none():
    # Has the input_i anchor but is not valid JSON → None (caller falls back).
    assert sy._parse_loudnorm_json('{ input_i broken, no quotes }') is None
