from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from PIL import Image, ImageStat


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_screenshots.py"
ROOT = Path(__file__).resolve().parents[3]


def _load_module():
    spec = importlib.util.spec_from_file_location("render_promo_screenshots", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sample_shots_json(tmp_path: Path) -> Path:
    path = tmp_path / "shots.json"
    path.write_text(
        """
[
  {
    "id": "bookshelf",
    "sourceStem": "01_bookshelf",
    "outputName": "final_01_bookshelf.png",
    "copy": {
      "title": "把閱讀變成會累積的字彙力",
      "subtitle": "從收藏、整理到複習，重要單字一路留在你的脈絡裡。"
    }
  }
]
""".strip()
    )
    return path


# 註：舊有兩條「render 靜態 SHOTS 路徑 == checked-in asset」pin 測試已移除。
# 它們假設 backend/static 官網圖與 docs/assets App Store 圖由 render_screenshots
# 的 SHOTS + sources/iphone-framed 靜態路徑產生；但行銷化後這些 asset 改由
# capture_profile 動態 pipeline（catalog snapshot→動態 framed→render，餵
# --source-dir/--shots-json）產出，靜態路徑永久無法重建 → pin 脫節、成 false
# gate。視覺品質改由人工全解析度親驗；此處只鎖「render 引擎不硬切 frame」的
# 非視覺結構迴歸（caller-level guard，補 fit_frame_into_canvas 純函式測不到的
# caller-only revert）。


def _bottom_strip_mean(img: Image.Image, y0: int, y1: int) -> float:
    """畫布底部中央帶的平均亮度。frame 完整放入時＝白 canvas 留白（高亮度）；
    舊 bug 版 frame 被切到底＝深色 frame 邊（低亮度）。"""
    strip = img.convert("RGB").crop((100, y0, img.width - 100, y1))
    return sum(ImageStat.Stat(strip).mean) / 3


def test_web_render_frame_fully_inside_canvas(tmp_path: Path):
    """render_web 實際輸出 462x1000 且底部保留白邊（device frame 完整、不被畫布
    硬切成「黑橫」）。用靜態 framed source 當探針；行銷 asset 由 pipeline 動態產、
    不歸此引擎測 pin。"""
    mod = _load_module()
    src = ROOT / "promotion" / "screenshots" / "sources" / "iphone-framed"
    shots = [mod.PromoShot("01_vocab_list", "final_01_vocab_list.png", "t", "s", "probe.png", "標題", "副標")]
    written = mod.render_web(root=ROOT, output_dir=tmp_path, source_dir=src, shots=shots)
    img = Image.open(written[0]).convert("RGB")
    assert img.size == (462, 1000)
    # 底部 6px（bottom_margin=16 內）應是接近白的留白，非被切平的 frame 深邊。
    assert _bottom_strip_mean(img, 994, 1000) > 228, "web 底部非白留白＝疑似 frame 硬切"


def test_app_store_render_frame_fully_inside_canvas(tmp_path: Path):
    """render_app_store 實際輸出 1284x2778 且底部保留白邊（frame 完整、不硬切）。"""
    mod = _load_module()
    src = ROOT / "promotion" / "screenshots" / "sources" / "iphone-framed"
    shots = [mod.PromoShot("01_vocab_list", "final_01_vocab_list.png", "標題", "副標", "x.png", "t", "s")]
    written = mod.render_app_store(root=ROOT, output_dir=tmp_path, source_dir=src, shots=shots)
    img = Image.open(written[0]).convert("RGB")
    assert img.size == (1284, 2778)
    assert _bottom_strip_mean(img, 2770, 2778) > 228, "app 底部非白留白＝疑似 frame 硬切"


def test_app_store_renderer_accepts_external_sources_and_shots_json(tmp_path: Path):
    mod = _load_module()
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    sample = Image.open(ROOT / "promotion" / "screenshots" / "sources" / "iphone-framed" / "01_vocab_list.png")
    sample.save(source_dir / "01_bookshelf.png")
    shots_json = _sample_shots_json(tmp_path)

    written = mod.render_app_store(
        root=ROOT,
        output_dir=tmp_path / "out",
        target="promotion",
        source_dir=source_dir,
        shots=mod.load_shots_manifest(shots_json),
    )

    assert [path.name for path in written] == ["final_01_bookshelf.png"]
    assert Image.open(written[0]).size == (1284, 2778)
