#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest"]
# ///
"""Contract guard: the dev/smoke TTS tools must source their default model from
``tts_config.DEFAULT_TTS_MODEL`` (the 2.5-default SoT), never hardcode a model
string. Both ``ab_perf_frame.py`` and ``smoke_tts.py`` read ``TTS_MODEL`` from
the env with a fallback — that fallback must be the SoT, or developers silently
exercise the wrong (e.g. 3.1) model.

Source-level test (AST) so it runs without the heavy google-genai / pydub deps
those scripts pull in. Pins both the wiring and the resolved default value.

Run:
    cd lab/podcast && uv run test_dev_tool_tts_default.py
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tts_config import DEFAULT_TTS_MODEL

_DIR = Path(__file__).parent
_DEV_TOOLS = ("ab_perf_frame.py", "smoke_tts.py")


def _model_default_calls(src: str) -> list[ast.Call]:
    """Find every ``os.getenv("TTS_MODEL", <default>)`` call in the module."""
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (
            isinstance(fn, ast.Attribute)
            and fn.attr == "getenv"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "TTS_MODEL"
        ):
            out.append(node)
    return out


@pytest.mark.parametrize("name", _DEV_TOOLS)
def test_tts_default_is_sot_not_hardcoded(name):
    src = (_DIR / name).read_text()
    calls = _model_default_calls(src)
    assert calls, f"{name}: expected an os.getenv('TTS_MODEL', ...) default"
    for call in calls:
        assert len(call.args) >= 2, f"{name}: TTS_MODEL getenv lacks a default"
        default = call.args[1]
        # Must reference the SoT name, NOT a string literal model id.
        assert isinstance(default, ast.Name) and default.id == "DEFAULT_TTS_MODEL", (
            f"{name}: TTS_MODEL default must be DEFAULT_TTS_MODEL, "
            f"got {ast.dump(default)}"
        )


@pytest.mark.parametrize("name", _DEV_TOOLS)
def test_imports_sot(name):
    src = (_DIR / name).read_text()
    assert "from tts_config import DEFAULT_TTS_MODEL" in src, (
        f"{name}: must import DEFAULT_TTS_MODEL from tts_config"
    )


def test_sot_default_is_2_5():
    # The current contract: 2.5 is the default family.
    assert DEFAULT_TTS_MODEL == "gemini-2.5-flash-tts"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
