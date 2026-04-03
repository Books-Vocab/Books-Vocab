from __future__ import annotations

import hmac
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from kg.admin_handlers import _resolve_admin_token, _sign_cookie, require_admin


# ── _resolve_admin_token ───────────────────────────────────────────────────────

def test_header_takes_priority_over_query_param():
    result = _resolve_admin_token(token="query-token", authorization="Bearer header-token")
    assert result == "header-token"


def test_query_param_used_when_no_header():
    result = _resolve_admin_token(token="query-token", authorization=None)
    assert result == "query-token"


def test_query_param_logs_deprecation_warning(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="kg.admin_handlers"):
        _resolve_admin_token(token="query-token", authorization=None)
    assert "deprecated" in caplog.text.lower()


def test_both_none_returns_none():
    assert _resolve_admin_token(token=None, authorization=None) is None


def test_invalid_bearer_prefix_falls_through_to_query_param():
    result = _resolve_admin_token(token="query-token", authorization="Token not-bearer")
    assert result == "query-token"


# ── require_admin ──────────────────────────────────────────────────────────────

def test_require_admin_uses_hmac_compare_digest():
    with patch("kg.admin_handlers.hmac.compare_digest", wraps=hmac.compare_digest) as mock_cd:
        require_admin(None, admin_token="secret", authorization="Bearer secret")
        mock_cd.assert_called_once_with("secret", "secret")


def test_require_admin_valid_header_passes():
    require_admin(None, admin_token="secret", authorization="Bearer secret")


def test_require_admin_valid_query_param_passes():
    require_admin("secret", admin_token="secret", authorization=None)


def test_require_admin_wrong_token_raises_403():
    with pytest.raises(HTTPException) as exc_info:
        require_admin(None, admin_token="secret", authorization="Bearer wrong")
    assert exc_info.value.status_code == 403


def test_require_admin_none_token_raises_403():
    with pytest.raises(HTTPException) as exc_info:
        require_admin(None, admin_token="secret", authorization=None)
    assert exc_info.value.status_code == 403


def test_require_admin_empty_admin_token_raises_403():
    with pytest.raises(HTTPException) as exc_info:
        require_admin(None, admin_token="", authorization="Bearer something")
    assert exc_info.value.status_code == 403
    assert "ADMIN_TOKEN not configured" in exc_info.value.detail


def test_require_admin_resolved_none_does_not_crash():
    with pytest.raises(HTTPException) as exc_info:
        require_admin(None, admin_token="secret", authorization=None)
    assert exc_info.value.status_code == 403


# ── cookie-based admin session ────────────────────────────────────────────────

def test_resolve_admin_token_no_cookie_param_returns_none():
    """_resolve_admin_token no longer handles cookies; it should return None."""
    assert _resolve_admin_token(token=None, authorization=None) is None


def test_require_admin_valid_cookie_passes():
    signed = _sign_cookie("secret")
    require_admin(None, admin_token="secret", authorization=None, cookie_token=signed)


def test_require_admin_wrong_cookie_raises_403():
    with pytest.raises(HTTPException) as exc_info:
        require_admin(None, admin_token="secret", authorization=None, cookie_token="wrong")
    assert exc_info.value.status_code == 403


def test_require_admin_header_takes_priority_over_cookie():
    """Even with a valid cookie, a wrong Bearer token should fail."""
    signed = _sign_cookie("secret")
    with pytest.raises(HTTPException) as exc_info:
        require_admin(None, admin_token="secret", authorization="Bearer wrong", cookie_token=signed)
    assert exc_info.value.status_code == 403


def test_admin_ui_response_sets_signed_cookie():
    from kg.admin_handlers import admin_ui_response

    resp = admin_ui_response(
        admin_token="secret",
        admin_html="<h1>Admin</h1>",
    )
    cookie_header = resp.headers.get("set-cookie", "")
    expected_value = _sign_cookie("secret")
    assert f"admin_session={expected_value}" in cookie_header
    assert "httponly" in cookie_header.lower()
    assert "secure" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()
    assert "path=/" in cookie_header.lower()


def test_admin_ui_response_returns_200():
    from kg.admin_handlers import admin_ui_response

    resp = admin_ui_response(
        admin_token="secret",
        admin_html="<h1>Admin</h1>",
    )
    assert resp.status_code == 200


def test_admin_tests_ui_response_sets_cookie():
    from kg.admin_handlers import admin_tests_ui_response

    resp = admin_tests_ui_response(
        admin_token="secret",
        admin_tests_html="<h1>Tests</h1>",
    )
    cookie_header = resp.headers.get("set-cookie", "")
    assert "admin_session=" in cookie_header
