#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pytest",
# ]
# ///
"""run_alignments:批次對齊須隔離單集失敗,不可一集崩潰拖垮整批。

根因:原 main() 迴圈直接 `align_and_save(...)`,任一集(model load/OOM/
壞音檔)拋例外即中止整批,已對齊好的也不報、後面的全不跑。改為逐集
try/except,失敗記錄並續跑,成功的 SRT 照寫,結尾以 nonzero exit 讓
pipeline 感知部分失敗。

跑法:uv run --with pytest python -m pytest test_subtitle_resilience.py -q
"""
from __future__ import annotations

from pathlib import Path

import subtitle as sub


def test_run_alignments_isolates_failure(monkeypatch, capsys):
    todo = [
        (Path("ep_1_script.md"), Path("ep_1.m4a")),
        (Path("ep_2_script.md"), Path("ep_2.m4a")),
        (Path("ep_3_script.md"), Path("ep_3.m4a")),
    ]

    def fake_align(script, audio, model):
        if script.stem == "ep_2_script":
            raise RuntimeError("simulated OOM")
        return audio.with_suffix(".srt")

    monkeypatch.setattr(sub, "align_and_save", fake_align)
    outputs, failed = sub.run_alignments(todo, "medium")

    # ep_1 and ep_3 still produced despite ep_2 blowing up.
    assert [p.name for p in outputs] == ["ep_1.srt", "ep_3.srt"]
    assert [p.stem for p in failed] == ["ep_2_script"]
    assert "ERROR aligning ep_2_script" in capsys.readouterr().err


def test_run_alignments_all_success(monkeypatch):
    todo = [(Path("a_script.md"), Path("a.m4a")), (Path("b_script.md"), Path("b.m4a"))]
    monkeypatch.setattr(sub, "align_and_save", lambda s, a, m: a.with_suffix(".srt"))
    outputs, failed = sub.run_alignments(todo, "medium")
    assert len(outputs) == 2 and failed == []
