from __future__ import annotations

from pathlib import Path


_ASSET_DIR = Path(__file__).resolve().parent

ADMIN_HTML = (_ASSET_DIR / "admin_dashboard.html").read_text(encoding="utf-8")
ADMIN_TESTS_HTML = (_ASSET_DIR / "admin_tests.html").read_text(encoding="utf-8")
