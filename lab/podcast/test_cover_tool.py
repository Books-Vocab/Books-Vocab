"""cover_tool 純函式測試(無網路):取色/後製/contact 佈局。

跑法(lab/podcast 無 venv,PEP723 補依賴):
  uv run --with pillow --with python-dotenv --with pytest pytest test_cover_tool.py -q
"""
from __future__ import annotations

import colorsys

import pytest
from PIL import Image

import cover_tool as ct


# ---------- _hex2rgb ----------
def test_hex2rgb_with_and_without_hash():
    assert ct._hex2rgb("#4A5B8C") == (74, 91, 140)
    assert ct._hex2rgb("4A5B8C") == (74, 91, 140)


# ---------- _derive_color:從 avg_color 取「不 muddy」的 series 色 ----------
def test_derive_color_boosts_grey_avg_saturation():
    """近灰的 avg_color 經取色後飽和度必須拉高,否則 duotone 會糊成灰。"""
    grey = "#8A8A8C"  # 幾乎無彩度
    r, g, b = ct._derive_color(grey)
    _, s, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    assert s >= 0.4, f"derived saturation {s:.2f} 太低,duotone 會 muddy"


def test_derive_color_preserves_hue():
    """取色只調飽和/明度,色相應大致保留(藍仍是藍)。"""
    blue = "#3A4F8C"
    h0, _, _ = colorsys.rgb_to_hsv(*[c / 255 for c in ct._hex2rgb(blue)])
    r, g, b = ct._derive_color(blue)
    h1, _, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    assert abs(h1 - h0) < 0.08, "色相偏移過大"


def test_derive_color_returns_valid_rgb():
    for hexc in ("#000000", "#FFFFFF", "#B5694A"):
        rgb = ct._derive_color(hexc)
        assert len(rgb) == 3 and all(0 <= c <= 255 for c in rgb)


# ---------- _treat:後製產出固定尺寸 RGB ----------
@pytest.fixture
def square_src():
    # 漸層方圖當輸入(模擬已裁方的照片)
    im = Image.new("RGB", (ct.SIZE, ct.SIZE))
    px = im.load()
    for y in range(ct.SIZE):
        for x in range(0, ct.SIZE, 8):
            v = (x + y) % 256
            for dx in range(8):
                if x + dx < ct.SIZE:
                    px[x + dx, y] = (v, (v + 80) % 256, (v + 160) % 256)
    return im


def test_treat_duo_output_shape(square_src):
    out = ct._treat(square_src, (74, 91, 140), "duo")
    assert out.size == (ct.SIZE, ct.SIZE)
    assert out.mode == "RGB"


def test_treat_soft_output_shape(square_src):
    out = ct._treat(square_src, (181, 105, 74), "soft")
    assert out.size == (ct.SIZE, ct.SIZE)
    assert out.mode == "RGB"


def test_treat_scrim_darkens_bottom(square_src):
    """scrim 應壓暗底部:底列平均亮度 < 中列。"""
    out = ct._treat(square_src, (74, 91, 140), "duo")
    g = out.convert("L")
    mid = sum(g.getpixel((x, ct.SIZE // 2)) for x in range(0, ct.SIZE, 32))
    bot = sum(g.getpixel((x, ct.SIZE - 4)) for x in range(0, ct.SIZE, 32))
    assert bot < mid, "底部未被 scrim 壓暗"


def test_treat_duo_deterministic(square_src):
    a = ct._treat(square_src, (74, 91, 140), "duo")
    b = ct._treat(square_src, (74, 91, 140), "duo")
    assert a.tobytes() == b.tobytes()


# ---------- _compose_contact:contact sheet 佈局 ----------
def _cells(n, cell):
    return [(i + 1, f"id{i}", Image.new("RGB", (cell, cell), (i * 20 % 255, 0, 0)))
            for i in range(n)]


def test_compose_contact_dims_3col():
    cell, gap, cols = 280, 8, 3
    sheet = ct._compose_contact(_cells(6, cell), cell=cell, cols=cols, gap=gap)
    # 6 cells / 3 col = 2 row
    assert sheet.size == (cols * cell + (cols + 1) * gap, 2 * cell + 3 * gap)


def test_compose_contact_partial_last_row():
    cell, gap, cols = 280, 8, 3
    sheet = ct._compose_contact(_cells(4, cell), cell=cell, cols=cols, gap=gap)
    assert sheet.size[1] == 2 * cell + 3 * gap  # 4 cells → 2 rows
