#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "fastapi",
#     "uvicorn[standard]",
#     "python-multipart",
#     "pytest",
# ]
# ///
"""Phase 1 — per-episode artifact status (durable, disk-derived).

監視器現有的 per-episode 狀態(`parallelEps` / ep-tile)**只來自 live SSE**,
idle workspace 全空白。製作人要的「逐集有沒有腳本/音頻/字幕」必須來自磁碟
artifact —— running 或 idle 都要。本測試鎖定 `server._episode_status(ws)`:
對任一 workspace 目錄掃出每集四個 gate(plan/script/audio/subtitle)的真實狀態。

檔名 numbering(已對真實 workspace 確認):
  plan      plan/episodes/ep_NN.md      (zero-pad 2 位:ep_01.md)
  script    scripts/ep_N_script.md      (無 pad:ep_1_script.md)
  audio     scripts/ep_N_(pro|flash).mp3
  subtitle  scripts/ep_N_(pro|flash).srt
  (干擾項:ep_N_review.md / ep_N_voice_preview.mp3 不得被算成 gate)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import server  # noqa: E402


def _mk(ws: Path, rel: str, content: str = "x") -> None:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _by_ep(rows: list[dict]) -> dict[int, dict]:
    return {r["ep"]: r for r in rows}


def test_empty_workspace_returns_empty(tmp_path):
    ws = tmp_path / "empty_abcd1234"
    ws.mkdir()
    assert server._episode_status(ws) == []


def test_plan_only_all_gates_but_plan_false(tmp_path):
    ws = tmp_path / "planonly_abcd1234"
    for n in (1, 2, 3):
        _mk(ws, f"plan/episodes/ep_{n:02d}.md")
    rows = server._episode_status(ws)
    assert [r["ep"] for r in rows] == [1, 2, 3]
    for r in rows:
        assert r["plan"] is True
        assert r["script"] is False
        assert r["audio"] is False
        assert r["subtitle"] is False
        assert r["variant"] is None
        assert r["audio_bytes"] is None


def test_mixed_gates_per_episode(tmp_path):
    """ep1 全四關;ep2 plan+script;ep3 只有 plan。"""
    ws = tmp_path / "mixed_abcd1234"
    for n in (1, 2, 3):
        _mk(ws, f"plan/episodes/ep_{n:02d}.md")
    _mk(ws, "scripts/ep_1_script.md")
    _mk(ws, "scripts/ep_2_script.md")
    _mk(ws, "scripts/ep_1_pro.mp3", "AUDIOBYTES")  # 10 bytes
    _mk(ws, "scripts/ep_1_pro.srt")
    rows = _by_ep(server._episode_status(ws))
    assert rows[1] == {
        "ep": 1, "plan": True, "script": True, "audio": True,
        "subtitle": True, "variant": "pro", "audio_bytes": 10,
    }
    assert rows[2]["plan"] and rows[2]["script"]
    assert not rows[2]["audio"] and not rows[2]["subtitle"]
    assert rows[3]["plan"]
    assert not (rows[3]["script"] or rows[3]["audio"] or rows[3]["subtitle"])


def test_pro_preferred_over_flash(tmp_path):
    ws = tmp_path / "variant_abcd1234"
    _mk(ws, "plan/episodes/ep_01.md")
    _mk(ws, "scripts/ep_1_flash.mp3", "FLASH")
    _mk(ws, "scripts/ep_1_pro.mp3", "PROVARIANT")
    rows = _by_ep(server._episode_status(ws))
    assert rows[1]["variant"] == "pro"
    assert rows[1]["audio_bytes"] == len("PROVARIANT")


def test_flash_only_reported(tmp_path):
    ws = tmp_path / "flashonly_abcd1234"
    _mk(ws, "plan/episodes/ep_01.md")
    _mk(ws, "scripts/ep_1_flash.mp3", "FL")
    rows = _by_ep(server._episode_status(ws))
    assert rows[1]["audio"] is True
    assert rows[1]["variant"] == "flash"


def test_decoy_files_not_counted(tmp_path):
    """ep_N_review.md 與 ep_N_voice_preview.mp3 不是 gate artifact。"""
    ws = tmp_path / "decoy_abcd1234"
    _mk(ws, "plan/episodes/ep_01.md")
    _mk(ws, "scripts/ep_1_review.md")
    _mk(ws, "scripts/ep_1_voice_preview.mp3", "PREVIEW")
    rows = _by_ep(server._episode_status(ws))
    assert rows[1]["script"] is False
    assert rows[1]["audio"] is False


def test_script_or_audio_without_plan_still_listed(tmp_path):
    """episode 集合 = plan ∪ scripts;有腳本但 plan 缺也要出現(plan=False)。"""
    ws = tmp_path / "noplan_abcd1234"
    _mk(ws, "scripts/ep_4_script.md")
    _mk(ws, "scripts/ep_4_pro.mp3", "AA")
    rows = _by_ep(server._episode_status(ws))
    assert 4 in rows
    assert rows[4]["plan"] is False
    assert rows[4]["script"] is True
    assert rows[4]["audio"] is True
