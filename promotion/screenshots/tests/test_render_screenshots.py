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
