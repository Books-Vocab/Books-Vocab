from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from PIL import Image, ImageChops, ImageStat


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_screenshots.py"
ROOT = Path(__file__).resolve().parents[3]


def _load_module():
    spec = importlib.util.spec_from_file_location("render_promo_screenshots", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _mean_diff(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    return sum(ImageStat.Stat(diff).mean) / 3


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


def test_app_store_renderer_rebuilds_existing_assets_pixel_exact(tmp_path: Path):
    mod = _load_module()

    written = mod.render_app_store(root=ROOT, output_dir=tmp_path)

    assert len(written) == 4
    for rendered in written:
        expected = ROOT / "docs/assets/screenshots/iphone" / rendered.name
        diff = ImageChops.difference(Image.open(rendered).convert("RGB"), Image.open(expected).convert("RGB"))
        assert diff.getbbox() is None, rendered.name


def test_web_renderer_rebuilds_existing_assets_with_low_visual_delta(tmp_path: Path):
    mod = _load_module()

    written = mod.render_web(root=ROOT, output_dir=tmp_path)

    assert {path.name for path in written} == {
        "iphone-reader.png",
        "iphone-vocab-list.png",
        "iphone-review-card.png",
        "iphone-knowledge-graph.png",
    }
    for rendered in written:
        expected = ROOT / "backend/static/img/screenshots" / rendered.name
        assert Image.open(rendered).size == Image.open(expected).size == (462, 1000)
        assert _mean_diff(Image.open(rendered), Image.open(expected)) < 15.0, rendered.name


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
