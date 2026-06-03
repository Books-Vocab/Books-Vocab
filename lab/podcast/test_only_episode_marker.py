#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "ebooklib",
#     "beautifulsoup4",
#     "pytest",
# ]
# ///
"""--only-episode N must NOT write whole-stage completion markers.

根因:`pipeline.py <ws> --only-episode 3`(不帶 --only-stage)走正常 stage
loop,單集成功後 log.stage_end(success=True) 照寫 .stage_synthesize_done 等
整-stage marker。製作人補完單集後裸跑 `pipeline.py <ws>`,detect_resume_point
見 marker 存在 → 跳過 synthesize → 其餘集數永不合成,靜默缺集。

契約:當 only_episode 在場時,stage_end 不得寫整-stage marker(強制後續顯式
驅動);全量正常跑(only_episode 缺席)marker 行為不變。
"""
from pathlib import Path

import pipeline
from pipeline import PipelineLog, _STAGE_MARKER, stage_done


def _marker(ws: Path, stage: str) -> Path:
    return ws / _STAGE_MARKER.format(name=stage)


def test_only_episode_stage_end_does_not_write_whole_stage_marker(tmp_path):
    log = PipelineLog(tmp_path)
    log.stage_end("synthesize", success=True, elapsed=1.0, only_episode=True)
    assert not _marker(tmp_path, "synthesize").exists(), (
        "--only-episode must not write .stage_synthesize_done — a later bare "
        "`pipeline.py <ws>` would skip synthesize and silently drop episodes"
    )
    assert not stage_done(tmp_path, "synthesize")


def test_full_run_stage_end_still_writes_marker(tmp_path):
    """Regression guard: 全量正常跑(no only_episode)marker 行為不變。"""
    log = PipelineLog(tmp_path)
    log.stage_end("synthesize", success=True, elapsed=1.0)
    assert _marker(tmp_path, "synthesize").exists()
    assert stage_done(tmp_path, "synthesize")


def test_only_episode_false_writes_marker(tmp_path):
    """only_episode=False(顯式全量驅動)仍寫 marker。"""
    log = PipelineLog(tmp_path)
    log.stage_end("synthesize", success=True, elapsed=1.0, only_episode=False)
    assert _marker(tmp_path, "synthesize").exists()


def test_failed_stage_never_writes_marker(tmp_path):
    log = PipelineLog(tmp_path)
    log.stage_end("synthesize", success=False, elapsed=1.0, only_episode=True)
    assert not _marker(tmp_path, "synthesize").exists()
    log.stage_end("synthesize", success=False, elapsed=1.0)
    assert not _marker(tmp_path, "synthesize").exists()


def test_loop_passes_only_episode_to_stage_end(tmp_path):
    """白盒守:main loop 兩個 stage_end 呼叫都把 only_episode 傳進去,否則
    本 fix 在真實路徑上失效(unit 測 stage_end 綠但 loop 沒接線)。"""
    import inspect

    src = inspect.getsource(pipeline.main)
    # 兩個 success 路徑(失敗分支 + 成功分支)的 stage_end 都應帶 only_episode
    end_calls = [ln for ln in src.splitlines() if "log.stage_end(" in ln]
    assert end_calls, "main() should call log.stage_end"
    for ln in end_calls:
        assert "only_episode" in ln, f"stage_end call missing only_episode wiring: {ln.strip()}"
