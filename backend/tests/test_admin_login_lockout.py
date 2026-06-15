"""Brute-force lockout for POST /admin/login.

The shared ADMIN_PASSWORD is a single online-guessable secret. The generic
api_limiter (60/min/IP) is far too loose to slow a credential-stuffing attack.
POST /admin/login must have its own low-threshold limiter that returns 429 once
exceeded, independent of the generic API budget.
"""
from __future__ import annotations

import pytest

from conftest import ADMIN_TOKEN

ADMIN_PASSWORD = "my-secret-admin-password"


@pytest.fixture()
def admin_app(admin_app_factory):
    from kg.rate_limit import login_limiter

    login_limiter.reset()
    try:
        yield admin_app_factory(admin_token=ADMIN_TOKEN, admin_password=ADMIN_PASSWORD)
    finally:
        login_limiter.reset()


def test_login_post_has_dedicated_low_limiter():
    """A dedicated login_limiter exists with a low threshold (<= generic 60)."""
    from kg.rate_limit import api_limiter, login_limiter

    assert login_limiter.max_requests < api_limiter.max_requests
    assert login_limiter.max_requests <= 10
    assert login_limiter.window_seconds == 60


def test_repeated_wrong_password_eventually_429(admin_app):
    """After exceeding the login limiter, POST /admin/login returns 429."""
    from kg.rate_limit import login_limiter

    saw_429 = False
    # One extra beyond the limit guarantees a rejection.
    for _ in range(login_limiter.max_requests + 1):
        resp = admin_app.client.post(
            "/admin/login",
            data={"password": "wrong-password"},
            follow_redirects=False,
        )
        if resp.status_code == 429:
            saw_429 = True
            break
    assert saw_429, "brute-force attempts must eventually hit 429"


def test_login_429_below_generic_api_budget(admin_app):
    """Lockout trips well before the generic 60/min api_limiter would."""
    from kg.rate_limit import api_limiter

    statuses = []
    for _ in range(api_limiter.max_requests):
        resp = admin_app.client.post(
            "/admin/login",
            data={"password": "wrong-password"},
            follow_redirects=False,
        )
        statuses.append(resp.status_code)
        if resp.status_code == 429:
            break
    assert 429 in statuses
    # Must trip strictly before the generic budget would have.
    assert statuses.index(429) < api_limiter.max_requests
