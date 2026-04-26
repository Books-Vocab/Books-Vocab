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
    # Cookie value uses expiry-bound payload + signature; verify structure
    # by extracting the value and confirming require_admin accepts it.
    import re
    m = re.search(r"admin_session=([^;]+)", cookie_header)
    assert m is not None
    cookie_value = m.group(1)
    assert cookie_value.count(".") == 2
    require_admin(None, admin_token="secret", authorization=None, cookie_token=cookie_value)
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


# ── expiry-bound cookie binding (C5) ──────────────────────────────────────────


def test_sign_cookie_includes_expiry_and_nonce():
    """Cookie value must encode expires_at + nonce + signature, not a fixed HMAC."""
    a = _sign_cookie("secret")
    b = _sign_cookie("secret")
    # Two consecutive signs should differ (nonce randomness).
    assert a != b
    # Expected shape: "<expires_at>.<nonce_hex>.<sig_hex>".
    assert a.count(".") == 2
    expires_at, nonce, sig = a.split(".")
    assert expires_at.isdigit()
    assert len(nonce) == 32  # 16 bytes hex
    assert len(sig) == 64  # sha256 hex


def test_expired_cookie_rejected():
    import time

    from kg.admin_handlers import _build_cookie_value

    expired_at = int(time.time()) - 10
    expired = _build_cookie_value("secret", expires_at=expired_at)
    with pytest.raises(HTTPException) as exc_info:
        require_admin(None, admin_token="secret", authorization=None, cookie_token=expired)
    assert exc_info.value.status_code == 403


def test_tampered_payload_rejected():
    """Modifying expires_at must invalidate the signature."""
    signed = _sign_cookie("secret")
    expires_at, nonce, sig = signed.split(".")
    # Bump expires_at far into the future without re-signing.
    tampered = f"{int(expires_at) + 10**9}.{nonce}.{sig}"
    with pytest.raises(HTTPException) as exc_info:
        require_admin(None, admin_token="secret", authorization=None, cookie_token=tampered)
    assert exc_info.value.status_code == 403


def test_tampered_signature_rejected():
    signed = _sign_cookie("secret")
    expires_at, nonce, _sig = signed.split(".")
    bad_sig = "0" * 64
    tampered = f"{expires_at}.{nonce}.{bad_sig}"
    with pytest.raises(HTTPException) as exc_info:
        require_admin(None, admin_token="secret", authorization=None, cookie_token=tampered)
    assert exc_info.value.status_code == 403


def test_malformed_cookie_rejected():
    with pytest.raises(HTTPException):
        require_admin(None, admin_token="secret", authorization=None, cookie_token="garbage")
    with pytest.raises(HTTPException):
        require_admin(None, admin_token="secret", authorization=None, cookie_token="a.b")


def test_default_ttl_is_seven_days():
    from kg.admin_handlers import ADMIN_COOKIE_TTL_SECONDS

    assert ADMIN_COOKIE_TTL_SECONDS == 7 * 24 * 60 * 60


def test_set_admin_cookie_uses_seven_day_max_age():
    from kg.admin_handlers import admin_ui_response

    resp = admin_ui_response(admin_token="secret", admin_html="<h1>Admin</h1>")
    cookie_header = resp.headers.get("set-cookie", "")
    assert f"max-age={7 * 24 * 60 * 60}" in cookie_header.lower()
