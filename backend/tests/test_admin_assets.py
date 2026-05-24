"""Smoke test: admin HTML template constants load and are well-formed."""
from __future__ import annotations

from kg import admin_assets


def test_admin_html_loaded() -> None:
    assert admin_assets.ADMIN_HTML
    assert admin_assets.ADMIN_HTML.lstrip().startswith("<!DOCTYPE")


def test_admin_tests_html_loaded() -> None:
    assert admin_assets.ADMIN_TESTS_HTML
    assert admin_assets.ADMIN_TESTS_HTML.lstrip().startswith("<!DOCTYPE")


def test_admin_user_detail_html_loaded() -> None:
    assert admin_assets.ADMIN_USER_DETAIL_HTML
    assert admin_assets.ADMIN_USER_DETAIL_HTML.lstrip().startswith("<!DOCTYPE")
