"""cover pipeline stage:STAGES 位置 / series-wide / 冪等 / loud-fail / cost 聚合。

跑法:
  uv run --with ebooklib --with beautifulsoup4 --with pillow \
         --with python-dotenv --with pytest pytest test_cover_stage.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import pipeline


# ---------- STAGES 註冊 ----------
def test_cover_stage_between_subtitle_and_publish():
    s = pipeline.STAGES
    assert "cover" in s
    assert s.index("subtitle") < s.index("cover") < s.index("publish")
    # publish 是終端,cover 緊鄰其前
    assert s[s.index("publish") - 1] == "cover"


def test_cover_is_series_wide():
    # 一個 series 一張封面,--only-episode 不該觸發
    assert "cover" in pipeline._SERIES_WIDE_STAGES


def test_cover_skipped_for_only_episode_bare_loop():
    class _Args:
        only_episode = 3
        only_stage = None
    assert pipeline._should_skip_for_only_episode("cover", _Args()) is True


# ---------- stage_cover 冪等 / loud-fail ----------
@pytest.fixture
def ws(tmp_path):
    (tmp_path / "plan").mkdir()
    return tmp_path


def test_stage_cover_idempotent_skip(ws, monkeypatch):
    """plan/cover.png 已存在 → 直接 True,不呼叫 run_claude。"""
    (ws / "plan" / "cover.png").write_bytes(b"\x89PNG\r\n")
    called = {"n": 0}
    monkeypatch.setattr(pipeline, "run_claude", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or True)
    log = pipeline.PipelineLog(ws)
    assert pipeline.stage_cover(ws, log) is True
    assert called["n"] == 0, "冪等路徑不該呼叫 agent"


def test_stage_cover_loud_fail_when_no_png(ws, monkeypatch):
    """agent 回成功但沒產出 cover.png → loud-fail(False),不靜默放行。"""
    monkeypatch.setattr(pipeline, "run_claude", lambda *a, **k: True)
    log = pipeline.PipelineLog(ws)
    assert pipeline.stage_cover(ws, log) is False


def test_stage_cover_agent_failure_propagates(ws, monkeypatch):
    monkeypatch.setattr(pipeline, "run_claude", lambda *a, **k: False)
    log = pipeline.PipelineLog(ws)
    assert pipeline.stage_cover(ws, log) is False


def test_stage_cover_success_emits_usage(ws, monkeypatch):
    """agent 成功且產出 cover.png → emit image_usage,回 True。"""
    def fake_claude(*a, **k):
        (ws / "plan" / "cover.png").write_bytes(b"\x89PNG\r\n")
        (ws / "plan" / "cover_meta.json").write_text(
            json.dumps({"pexels_id": 12345, "source": "pexels", "treatment": "duo"}))
        return True
    monkeypatch.setattr(pipeline, "run_claude", fake_claude)
    log = pipeline.PipelineLog(ws)
    assert pipeline.stage_cover(ws, log) is True
    events = [json.loads(l) for l in (ws / "events.jsonl").read_text().splitlines() if l.strip()]
    img = [e for e in events if e["event"].get("type") == "image_usage"]
    assert len(img) == 1
    assert img[0]["event"]["pexels_id"] == 12345
    assert img[0]["event"]["cost_usd"] == 0.0
    assert img[0]["stage_label"] == "Cover"


def test_emit_cover_usage_tolerates_missing_meta(ws):
    """cover_meta.json 缺失也要寫出 event(pexels_id=None),不 crash。"""
    pipeline._emit_cover_usage(ws)
    events = [json.loads(l) for l in (ws / "events.jsonl").read_text().splitlines() if l.strip()]
    assert events[0]["event"]["type"] == "image_usage"
    assert events[0]["event"]["pexels_id"] is None


# ---------- cost.py 聚合 image_usage ----------
def _load_cost():
    sys.path.insert(0, str(Path(__file__).parent / "monitor"))
    import cost
    return cost


def test_cost_aggregates_image_usage_as_cover_zero(tmp_path):
    cost = _load_cost()
    ev = [
        {"ts": "t", "stage_label": "Cover",
         "event": {"type": "image_usage", "source": "pexels", "pexels_id": 7, "count": 1, "cost_usd": 0.0}},
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in ev))
    out = cost.aggregate_workspace(tmp_path)
    assert "cover" in out["by_stage"]
    assert out["by_stage"]["cover"]["calls"] == 1
    assert out["by_stage"]["cover"]["usd"] == 0.0


def test_cost_cover_label_maps_to_cover_stage(tmp_path):
    """cover 的 claude 推理成本(result modelUsage,label=Cover)應入 cover 桶。"""
    cost = _load_cost()
    ev = [
        {"ts": "t", "stage_label": "Cover",
         "event": {"type": "result", "modelUsage": {
             "claude-opus": {"costUSD": 0.05, "inputTokens": 100, "outputTokens": 50}}}},
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in ev))
    out = cost.aggregate_workspace(tmp_path)
    assert out["by_stage"]["cover"]["usd"] == pytest.approx(0.05)
