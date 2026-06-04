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
def test_derive_color_boosts_washed_out_saturation():
    """色相洗白(有色相但飽和低)的 avg_color 取色後飽和度必須拉高,否則 duotone 糊成灰。"""
    washed = "#9A8576"  # 暖色相,飽和低
    r, g, b = ct._derive_color(washed)
    _, s, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    assert s >= 0.4, f"derived saturation {s:.2f} 太低,duotone 會 muddy"


def test_derive_color_achromatic_returns_neutral():
    """純灰/黑/白(色相無定義)不可被任意提飽和變紅 → 退回品牌中性色。"""
    for grey in ("#8A8A8A", "#000000", "#FFFFFF"):
        assert ct._derive_color(grey) == ct._NEUTRAL_COLOR


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


# ---------- _get:網路/HTTP/JSON 故障收斂為 _die,不吐裸 traceback ----------
class _FakeResp:
    def __init__(self, body): self._body = body
    def read(self): return self._body
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_get_network_error_dies_cleanly(monkeypatch):
    import urllib.error
    def boom(*a, **k):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(ct.urllib.request, "urlopen", boom)
    with pytest.raises(SystemExit):
        ct._get("https://api.pexels.com/v1/search?query=x")


def test_get_http_error_dies_cleanly(monkeypatch):
    import urllib.error
    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
    monkeypatch.setattr(ct.urllib.request, "urlopen", boom)
    with pytest.raises(SystemExit):
        ct._get("https://api.pexels.com/v1/search?query=x")


def test_get_bad_json_dies_cleanly(monkeypatch):
    monkeypatch.setattr(ct.urllib.request, "urlopen", lambda *a, **k: _FakeResp(b"<html>nope</html>"))
    with pytest.raises(SystemExit):
        ct._get("https://api.pexels.com/v1/search?query=x")


def test_get_raw_returns_bytes(monkeypatch):
    monkeypatch.setattr(ct.urllib.request, "urlopen", lambda *a, **k: _FakeResp(b"\x89PNG"))
    assert ct._get("https://img", raw=True) == b"\x89PNG"


def test_get_json_ok(monkeypatch):
    monkeypatch.setattr(ct.urllib.request, "urlopen", lambda *a, **k: _FakeResp(b'{"photos": []}'))
    assert ct._get("https://api") == {"photos": []}
