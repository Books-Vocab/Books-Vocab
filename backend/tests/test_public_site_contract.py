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
