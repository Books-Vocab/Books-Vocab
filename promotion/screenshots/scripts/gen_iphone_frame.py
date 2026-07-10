#!/usr/bin/env -S uv run --with pillow python
"""Regenerate the iPhone device-frame template asset used by App Store framing.

一次性從既有 WithFrame 產物提取乾淨的裝置外框（黑鈦邊框 + 側鍵 + 透明圓角螢幕
開口），再以 Pillow 重繪動態島，寫出 checked-in 模板 asset 供
`frame_catalog_screenshots.py` 本地合成使用（取代已失效的 WithFrame web API）。

產物：
  promotion/screenshots/assets/iphone_frame.png   （RGBA，透明螢幕開口 + 動態島）
  promotion/screenshots/assets/iphone_frame.json  （螢幕開口幾何）

改動態島/圓角/邊框只需調本檔常數後重跑：
  ./promotion/screenshots/scripts/gen_iphone_frame.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

_SCREENSHOTS = Path(__file__).resolve().parents[1]  # promotion/screenshots
# 外框來源：WithFrame 曾套框的真實 iPhone frame（我們只取其黑鈦邊框幾何，螢幕內容
# 會被挖空）。此圖的螢幕開口幾何由下方常數描述（實測 2026-07-10）。
SOURCE = _SCREENSHOTS / "sources/iphone-framed/01_vocab_list.png"
OUT_PNG = _SCREENSHOTS / "assets/iphone_frame.png"
OUT_JSON = _SCREENSHOTS / "assets/iphone_frame.json"

# 螢幕開口（實測 SOURCE 的圓角螢幕邊界）與圓角半徑。
SCREEN = {"left": 48, "top": 41, "right": 1271, "bottom": 2698, "cornerRadius": 155}
# 動態島（pill + 相機鏡頭），置於螢幕頂部中央。
DI_W, DI_H, DI_TOP_OFFSET = 352, 104, 40


def build_template() -> Image.Image:
    base = Image.open(SOURCE).convert("RGBA")
    w, h = base.size
    left, top, right, bottom = SCREEN["left"], SCREEN["top"], SCREEN["right"], SCREEN["bottom"]
    radius = SCREEN["cornerRadius"]

    # 挖空圓角螢幕開口（角落黑鈦邊框保留），只留 frame chrome。
    hole = Image.new("L", (w, h), 0)
    ImageDraw.Draw(hole).rounded_rectangle([left, top, right - 1, bottom - 1], radius=radius, fill=255)
    tpl = base.copy()
    tpl.putalpha(ImageChops.multiply(base.split()[3], ImageChops.invert(hole)))

    # 動態島：黑 pill + 相機鏡頭（深色截圖上靠相機藍點辨識）。
    di_cx = (left + right) // 2
    di_top = top + DI_TOP_OFFSET
    di_l = di_cx - DI_W // 2
    d = ImageDraw.Draw(tpl)
    d.rounded_rectangle([di_l, di_top, di_l + DI_W, di_top + DI_H], radius=DI_H // 2, fill=(0, 0, 0, 255))
    cam_r = 25
    cam_cx = di_l + DI_W - 56
    cam_cy = di_top + DI_H // 2
    d.ellipse([cam_cx - cam_r, cam_cy - cam_r, cam_cx + cam_r, cam_cy + cam_r], fill=(16, 18, 26, 255))
    d.ellipse([cam_cx - 9, cam_cy - 9, cam_cx + 6, cam_cy + 6], fill=(38, 58, 116, 255))
    return tpl


def main() -> int:
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    tpl = build_template()
    tpl.save(OUT_PNG, "PNG")
    OUT_JSON.write_text(json.dumps({"screen": SCREEN, "canvas": {"w": tpl.width, "h": tpl.height}}, indent=2))
    print(f"wrote {OUT_PNG} {tpl.size}")
    print(f"wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
