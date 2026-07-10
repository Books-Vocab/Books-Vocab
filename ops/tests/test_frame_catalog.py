"""Smoke tests for the local iPhone device-frame compositor.

視覺品質靠人工全解析度親驗；此處只鎖非視覺迴歸：模板/幾何 asset 存在且一致、
frame script 端到端產出模板尺寸的 PNG。用 subprocess 走 script shebang
（`uv run --with pillow`），故 backend venv 無需 pillow；輸出尺寸用 PNG IHDR
header 解析，不 import PIL。
"""

from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRAME_SCRIPT = ROOT / "promotion" / "screenshots" / "scripts" / "frame_catalog_screenshots.py"
TEMPLATE = ROOT / "promotion" / "screenshots" / "assets" / "iphone_frame.png"
GEOMETRY = ROOT / "promotion" / "screenshots" / "assets" / "iphone_frame.json"
SAMPLE = ROOT / "promotion" / "screenshots" / "sources" / "iphone-framed" / "01_vocab_list.png"


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path} 不是 PNG"
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def test_frame_template_and_geometry_present_and_consistent():
    assert TEMPLATE.exists(), f"缺少 frame 模板 {TEMPLATE}"
    assert GEOMETRY.exists(), f"缺少 frame 幾何 {GEOMETRY}"
    geo = json.loads(GEOMETRY.read_text())
    for key in ("left", "top", "right", "bottom", "cornerRadius"):
        assert key in geo["screen"], f"幾何缺 screen.{key}"
    assert geo["screen"]["right"] > geo["screen"]["left"]
    assert geo["screen"]["bottom"] > geo["screen"]["top"]
    assert (geo["canvas"]["w"], geo["canvas"]["h"]) == _png_size(TEMPLATE)


def test_frame_script_produces_template_sized_output(tmp_path: Path):
    shots = tmp_path / "shots.json"
    shots.write_text(json.dumps([{"rawPath": str(SAMPLE), "sourceStem": "smoke"}]))
    out_dir = tmp_path / "framed"
    result = subprocess.run(
        [str(FRAME_SCRIPT), "--shots-json", str(shots), "--output-dir", str(out_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    framed = out_dir / "smoke.png"
    assert framed.exists(), "frame script 未產出 smoke.png"
    # 合成輸出 = 模板尺寸（截圖貼進開口，模板 overlay）。
    assert _png_size(framed) == _png_size(TEMPLATE)
