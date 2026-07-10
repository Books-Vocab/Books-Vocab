"""迴歸：device frame 完整放進官網/App Store 畫布，底部圓角不被硬切（「黑橫」）。

黑橫 bug：render_web 固定 frame_w=432 貼 y=134，frame 高 897 > 畫布可用高
(1000-134)，底部 31px（手機圓角+home indicator+黑鈦下邊框）被切成一條平黑邊，
深色截圖上尤其明顯。render_app_store 同型 bug 切 ~113px。fit_frame_into_canvas
保證 frame_y + frame_h <= target_h - bottom_margin（不硬切）。

render_screenshots.py top-level import PIL，backend venv 無 pillow，故走
subprocess + `uv run --with pillow`（比照 test_frame_catalog）；一次 subprocess
驗完全部 case，避免多次 uv 冷啟。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "promotion" / "screenshots" / "scripts" / "render_screenshots.py"
# 實際 checked-in iphone_frame.png template 尺寸（gen_iphone_frame 產出）。
TEMPLATE_W, TEMPLATE_H = 1320, 2740


def _run_fit_cases() -> dict[str, list[int]]:
    code = f"""
import importlib.util, json
spec = importlib.util.spec_from_file_location("rs", {str(SCRIPT)!r})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fit = m.fit_frame_into_canvas
cases = {{
  "web": fit({TEMPLATE_W}, {TEMPLATE_H}, target_h=1000, frame_y=134, bottom_margin=16, design_w=432),
  "app": fit({TEMPLATE_W}, {TEMPLATE_H}, target_h=2778, frame_y=430, bottom_margin=90, design_w=1200),
  "short": fit({TEMPLATE_W}, 1500, target_h=1000, frame_y=134, bottom_margin=16, design_w=432),
}}
print(json.dumps({{k: list(v) for k, v in cases.items()}}))
"""
    out = subprocess.run(
        ["uv", "run", "--with", "pillow", "python", "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_frames_fit_without_bottom_crop():
    cases = _run_fit_cases()

    # web 462x1000：frame 必須縮小（證明修復生效，非原始 432 硬切），且完整放入。
    fw, fh = cases["web"]
    assert fw < 432, "web frame 未縮小 = 仍會硬切"
    assert 134 + fh <= 1000 - 16, f"web frame 底部 {134 + fh} 超出畫布（留白 16）"

    # App Store 1284x2778：同樣完整放入，底部圓角可見。
    fw, fh = cases["app"]
    assert fw < 1200, "app frame 未縮小 = 仍會硬切"
    assert 430 + fh <= 2778 - 90, f"app frame 底部 {430 + fh} 超出畫布（留白 90）"

    # 本來就放得下的矮 frame 不應被放大（保持 design_w）。
    fw, fh = cases["short"]
    assert fw == 432, f"矮 frame 被誤放大到 {fw}"
    assert 134 + fh <= 1000 - 16
