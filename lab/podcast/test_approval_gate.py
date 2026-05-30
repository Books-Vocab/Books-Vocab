#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "pytest",
# ]
# ///
"""Phase 2 — 計畫/腳本兩道人工核准 gate。

製作人要在「生成逐字腳本前」「生成音頻(TTS)前」各攔一次,審查滿意才放行。
pipeline 因此夾兩道 gate:
    PLAN(prep→enricher) ┃gate1 .plan_approved┃ SCRIPT(scriptwrite→script-review)
                        ┃gate2 .script_approved┃ AUDIO(tts-prep→subtitle)

純決策函式 `approval_gate_block(stage, ws, explicit_skip_idx, ignore_gates)`:
回傳擋住進入 `stage` 的 marker 檔名,或 None(可進)。

關鍵正確性:bypass 只認**顯式** --skip-to/--only-stage(製作人主動驅動=核准),
**不**認 auto-resume —— 否則未核准卻再跑 `pipeline.py <ws>`,auto-resume 把
start_idx 推到 scriptwrite 就會繞過 gate。故顯式判斷用 args.skip_to(只在使用者
明確指定時非 None),而非 auto-resume 後的 start_idx。
"""
import pytest

import pipeline


SCRIPTWRITE_IDX = pipeline.STAGES.index("scriptwrite")  # gate1
TTS_PREP_IDX = pipeline.STAGES.index("tts-prep")        # gate2


def _gate(stage, ws, **kw):
    return pipeline.approval_gate_block(stage, ws, **kw)


# ─── 非 gate stage 永遠放行 ───
@pytest.mark.parametrize("stage", ["prep", "architect", "enricher",
                                   "series-polish", "synthesize", "subtitle"])
def test_non_gate_stage_never_blocks(tmp_path, stage):
    assert _gate(stage, tmp_path) is None


# ─── gate1:scriptwrite ───
def test_gate1_blocks_fresh(tmp_path):
    """全新到 scriptwrite、無 .plan_approved、非顯式 → 擋。"""
    assert _gate("scriptwrite", tmp_path) == ".plan_approved"


def test_gate1_passes_with_marker(tmp_path):
    (tmp_path / ".plan_approved").write_text("ok")
    assert _gate("scriptwrite", tmp_path) is None


def test_gate1_passes_when_explicit_skip_to_scriptwrite(tmp_path):
    """--skip-to scriptwrite / --only-stage scriptwrite = 製作人主動驅動。"""
    assert _gate("scriptwrite", tmp_path, explicit_skip_idx=SCRIPTWRITE_IDX) is None


def test_gate1_still_blocks_when_explicit_skip_to_earlier(tmp_path):
    """--skip-to architect 會 auto-progress 跨越 gate → 仍須核准。"""
    archi = pipeline.STAGES.index("architect")
    assert _gate("scriptwrite", tmp_path, explicit_skip_idx=archi) == ".plan_approved"


def test_gate1_bypassed_by_ignore_gates(tmp_path):
    assert _gate("scriptwrite", tmp_path, ignore_gates=True) is None


# ─── gate2:tts-prep ───
def test_gate2_blocks_fresh(tmp_path):
    assert _gate("tts-prep", tmp_path) == ".script_approved"


def test_gate2_passes_with_marker(tmp_path):
    (tmp_path / ".script_approved").write_text("ok")
    assert _gate("tts-prep", tmp_path) is None


def test_gate2_passes_when_explicit_skip_to_tts_prep(tmp_path):
    assert _gate("tts-prep", tmp_path, explicit_skip_idx=TTS_PREP_IDX) is None


def test_gate2_independent_of_plan_marker(tmp_path):
    """.plan_approved 不解 gate2;gate2 只認 .script_approved。"""
    (tmp_path / ".plan_approved").write_text("ok")
    assert _gate("tts-prep", tmp_path) == ".script_approved"


def test_gate2_bypassed_by_ignore_gates(tmp_path):
    assert _gate("tts-prep", tmp_path, ignore_gates=True) is None


def test_gate2_blocks_when_explicit_skip_one_stage_before(tmp_path):
    """--skip-to series-polish(gate2 前一階段)會 auto-progress 跨 gate2 → 仍須核准。"""
    one_before = pipeline.STAGES.index("script-review")  # tts-prep 前一個
    assert one_before == TTS_PREP_IDX - 1
    assert _gate("tts-prep", tmp_path, explicit_skip_idx=one_before) == ".script_approved"


# ─── auto-resume 必須仍守 gate(回歸:不可用 start_idx 當顯式判斷)───
def test_autoresume_to_scriptwrite_without_approval_still_blocks(tmp_path):
    """模擬:plan 階段做完(markers 在),未核准就再跑 pipeline.py <ws>。
    auto-resume 會把 start_idx 推到 scriptwrite,但 explicit_skip_idx 仍是
    None(使用者沒給 --skip-to)→ gate 必須擋。"""
    assert _gate("scriptwrite", tmp_path, explicit_skip_idx=None) == ".plan_approved"
