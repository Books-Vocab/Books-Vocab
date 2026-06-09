from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PAGES = [
    ROOT / "index.html",
    ROOT / "guide.html",
    ROOT / "support.html",
    ROOT / "privacy.html",
    ROOT / "terms.html",
]
APP_STORE_URL = "https://apps.apple.com/app/id6759816274"
SCREENSHOT_FILES = [
    "iphone-reader.png",
    "iphone-vocab-list.png",
    "iphone-review-card.png",
    "iphone-knowledge-graph.png",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_public_pages_do_not_ship_placeholder_app_store_links() -> None:
    for path in PUBLIC_PAGES:
        html = _read(path)
        assert 'href="#"' not in html, f"{path.name} still ships a placeholder href"
        assert "TODO: 換成真實 App Store URL" not in html

    index = _read(ROOT / "index.html")
    assert index.count(APP_STORE_URL) >= 3


def test_landing_first_viewport_names_the_product_and_real_surfaces() -> None:
    html = _read(ROOT / "index.html")
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    assert h1 is not None
    assert "Books &amp; Vocab" in h1.group(1)
    assert "iPhone" in html
    assert "單字本" in html
    assert "Podcast" in html
    assert "Chrome" in html


def test_landing_uses_real_iphone_product_screenshots() -> None:
    html = _read(ROOT / "index.html")
    first_viewport = html.split('class="how-it-works', 1)[0]
    assert 'class="hero__visual"' in first_viewport
    assert "內容為示意圖" not in first_viewport
    assert "device__frame" not in first_viewport
    for filename in SCREENSHOT_FILES[:3]:
        assert f"/static/img/screenshots/{filename}" in first_viewport

    assert 'class="product-screens' in html
    for filename in SCREENSHOT_FILES:
        assert f"/static/img/screenshots/{filename}" in html
        assert (ROOT / "static" / "img" / "screenshots" / filename).is_file()


def test_guide_matches_current_ios_surface() -> None:
    html = _read(ROOT / "guide.html")
    assert "EPUB / PDF / TXT / Markdown" in html
    for phrase in [
        "單字本",
        "知識圖譜",
        "每日複習",
        "Podcast",
        "Chrome extension",
        "Pro",
    ]:
        assert phrase in html


def test_support_page_is_zh_hant_consistent() -> None:
    html = _read(ROOT / "support.html")
    assert "Reply within" not in html
    assert "1–3 個工作日" in html
