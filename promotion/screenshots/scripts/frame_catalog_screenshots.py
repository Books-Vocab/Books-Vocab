#!/usr/bin/env -S uv run --with pillow python
"""Frame raw catalog screenshots with a local iPhone device frame.

取代先前依賴的 WithFrame web API（外部服務不穩定：封 urllib UA→403、上傳格式
變更→400，且每次 refresh 都可能失效）。改用 repo 內 checked-in 的 iPhone 裝置
外框模板（黑鈦邊框 + 動態島 + 透明圓角螢幕開口）本地合成，完全自足、無外部依賴、
可重現。

模板與螢幕開口幾何：
  promotion/screenshots/assets/iphone_frame.png   （RGBA，透明螢幕開口）
  promotion/screenshots/assets/iphone_frame.json  （screen L/T/R/B/cornerRadius）

合成 = 截圖縮放到螢幕開口尺寸 → 貼在開口位置 → 模板 overlay（圓角/邊框/動態島
蓋在最上）。輸出帶手機形狀 alpha 的 RGBA PNG，供 render 步驟以 alpha 生成手機
形狀 drop shadow（`render_screenshots.py` 既有邏輯）。輸入/輸出介面（`--shots-json`
/ `--output-dir`）與舊 WithFrame 版一致，`capture_profile.frame_snapshot_sources`
無需改動。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

_ASSETS = Path(__file__).resolve().parents[1] / "assets"
TEMPLATE_PATH = _ASSETS / "iphone_frame.png"
GEOMETRY_PATH = _ASSETS / "iphone_frame.json"


def _load_shots(path: Path) -> list[dict[str, object]]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise SystemExit("shots json 必須是 array")
    return raw


def _frame_one(raw_path: Path, template: Image.Image, screen: dict[str, int]) -> Image.Image:
    left, top = screen["left"], screen["top"]
    width = screen["right"] - left
    height = screen["bottom"] - top
    shot = Image.open(raw_path).convert("RGBA")
    # aspect guard：截圖比例應貼近螢幕開口，否則 resize 會變形。iPhone portrait
    # render（~0.461）與開口（1223/2657≈0.460）差 <0.2% 無感；差太多要 fail loud
    # 而非默默拉伸（守獨立使用與未來 resolve 偏好變更）。
    src_aspect = shot.width / shot.height
    dst_aspect = width / height
    if abs(src_aspect - dst_aspect) > 0.02:
        print(
            f"warning: {raw_path.name} aspect {src_aspect:.3f} 偏離螢幕開口 {dst_aspect:.3f}，"
            "resize 會變形（非 iPhone portrait 來源？）",
            file=sys.stderr,
        )
    shot = shot.resize((width, height), Image.LANCZOS)
    canvas = Image.new("RGBA", template.size, (0, 0, 0, 0))
    canvas.alpha_composite(shot, (left, top))
    canvas.alpha_composite(template, (0, 0))  # 邊框/圓角/動態島蓋在截圖之上
    return canvas


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if not TEMPLATE_PATH.exists() or not GEOMETRY_PATH.exists():
        raise SystemExit(f"缺少 iPhone frame 模板 asset：{TEMPLATE_PATH} / {GEOMETRY_PATH}")
    template = Image.open(TEMPLATE_PATH).convert("RGBA")
    screen = json.loads(GEOMETRY_PATH.read_text())["screen"]
    shots = _load_shots(args.shots_json)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for shot in shots:
        raw_path = Path(str(shot["rawPath"]))
        source_stem = str(shot["sourceStem"])
        framed = _frame_one(raw_path, template, screen)
        target = args.output_dir / f"{source_stem}.png"
        framed.save(target, "PNG")
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
