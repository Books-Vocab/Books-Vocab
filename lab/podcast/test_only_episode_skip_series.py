#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "pytest",
# ]
# ///
"""--only-episode N (bare full loop) must skip series-polish + publish.

根因:裸跑 `pipeline.py <ws> --only-episode N`(不帶 --only-stage)走完整 stage
loop。series-polish 用 LLM 重寫**所有**集腳本、publish 全量重發布 —— 兩者都不接
only_episode。補一集卻觸發全 series 重 polish + 全量重發布 = 語義錯位 + 成本浪費。

契約:
  - only_episode 在場且非 --only-stage 顯式選中 → series-polish / publish 被 skip;
    且 skip 不得寫 .stage_<name>_done marker(後續裸跑全量仍會執行)。
  - only_episode 缺席(全量跑)→ 兩 stage 照常執行。
  - 製作人**顯式** --only-stage series-polish/publish (+ --only-episode N) → 不 skip,
    須執行(這是他刻意要跑全 series polish/publish)。
其餘 episode-aware stage(scriptwrite / synthesize / ...)在 only_episode 下不受影響。
"""
from types import SimpleNamespace

import pipeline
import pipeline_plan
from pipeline import _should_skip_for_only_episode


def _args(only_episode=None, only_stage=None):
    return SimpleNamespace(only_episode=only_episode, only_stage=only_stage)


# ── 裸跑單集(full loop, only_stage=None)→ series-polish / publish 被 skip ──
def test_bare_only_episode_skips_series_polish():
    assert _should_skip_for_only_episode("series-polish", _args(only_episode=3))


def test_bare_only_episode_skips_publish():
    assert _should_skip_for_only_episode("publish", _args(only_episode=3))


# ── 全量跑(only_episode=None)→ 兩 stage 照常執行(不 skip) ──
def test_full_run_does_not_skip_series_polish():
    assert not _should_skip_for_only_episode("series-polish", _args())


def test_full_run_does_not_skip_publish():
    assert not _should_skip_for_only_episode("publish", _args())


# ── 顯式 --only-stage series-polish/publish (+ --only-episode N) → 不 skip ──
def test_explicit_only_stage_publish_not_skipped():
    assert not _should_skip_for_only_episode(
        "publish", _args(only_episode=3, only_stage="publish")
    )


def test_explicit_only_stage_series_polish_not_skipped():
    assert not _should_skip_for_only_episode(
        "series-polish", _args(only_episode=3, only_stage="series-polish")
    )


# ── episode-aware / 其他 stage 在 only_episode 下絕不被本 guard skip ──
def test_only_episode_does_not_skip_episode_aware_stages():
    for stage in ("scriptwrite", "synthesize", "audio-qa", "subtitle", "script-review"):
        assert not _should_skip_for_only_episode(stage, _args(only_episode=3)), stage


# ── planner wiring guard: stage selection must use the pure plan ──
def test_main_loop_wires_skip_guard():
    plan = pipeline_plan.resolve_run_plan(
        pipeline_plan.PipelineConfig(stages=pipeline_plan.STAGE_SPECS, only_episode=3)
    )
    assert "series-polish" in plan.skipped_series_wide
    assert "publish" in plan.skipped_series_wide
    assert "scriptwrite" in plan.stage_names
