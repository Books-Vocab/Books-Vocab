"""Tests for deps_quota — the quota gate guarding translate/explain/pipeline.

Covers `_is_pro` (entitlement resolution: subscription + admin grant), and
`_with_quota_check` (gate behaviour: allow / block, handler suppression,
`QuotaExceededError` contract, `X-Quota-Fraction` header math, error paths).

DB isolation follows test_quota_service.py: patch `_get_conn`/`_lock` in
`kg.quota_service` so the real `token_usage.db` singleton is never touched.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import Response

from kg.deps_quota import _is_pro, _with_quota_check
from kg.exceptions import QuotaExceededError
from kg.quota_service import (
    configure_limits,
)

# ── shared fixtures ──────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    """In-memory token_usage DB patched into quota_service."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("""
        CREATE TABLE token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            call_type TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            provider TEXT,
            model TEXT
        )
    """)
    conn.commit()
    lock = threading.Lock()
    with patch("kg.quota_service._get_conn", return_value=conn), \
         patch("kg.quota_service._lock", lock):
        yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _stable_limits():
    """Pin limits to canonical defaults so header math is deterministic."""
    configure_limits(pro=0.30, free=0.03)
    yield
    configure_limits(pro=0.30, free=0.03)


def _insert_usage(conn, user_id, call_type, input_tokens, output_tokens=0, created_at=None):
    conn.execute(
        "INSERT INTO token_usage (user_id, call_type, input_tokens, output_tokens, created_at) "
        "VALUES (?,?,?,?,?)",
        (user_id, call_type, input_tokens, output_tokens,
         created_at or datetime.now(UTC).isoformat()),
    )
    conn.commit()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ── _is_pro ──────────────────────────────────────────────────────────


class TestIsPro:
    def test_no_record_is_not_pro(self):
        """A user dict with no 'record' key resolves to default inactive sub."""
        assert _is_pro({"id": "u1"}) is False

    def test_record_none_is_not_pro(self):
        assert _is_pro({"id": "u1", "record": None}) is False

    def test_active_subscription_is_pro(self):
        user = {"id": "u1", "record": {"subscription": {"is_active": True, "status": "active"}}}
        assert _is_pro(user) is True

    def test_inactive_subscription_is_not_pro(self):
        user = {"id": "u1", "record": {"subscription": {"is_active": False, "status": "inactive"}}}
        assert _is_pro(user) is False

    def test_active_admin_grant_is_pro(self):
        """Admin grant with is_active and no expiry overrides everything."""
        user = {"id": "u1", "record": {"admin_grant": {"is_active": True}}}
        assert _is_pro(user) is True

    def test_admin_grant_future_expiry_is_pro(self):
        future = datetime.now(UTC) + timedelta(days=30)
        user = {
            "id": "u1",
            "record": {"admin_grant": {"is_active": True, "expires_at": _iso(future)}},
        }
        assert _is_pro(user) is True

    def test_admin_grant_expired_despite_is_active_flag(self):
        """is_active=True but expires_at in the past → NOT pro.

        admin_grant_is_active() honours the timestamp over the stale flag.
        """
        past = datetime.now(UTC) - timedelta(seconds=1)
        user = {
            "id": "u1",
            "record": {"admin_grant": {"is_active": True, "expires_at": _iso(past)}},
        }
        assert _is_pro(user) is False

    def test_active_grant_overrides_inactive_subscription(self):
        """Inactive sub + active grant → pro (grant wins)."""
        user = {
            "id": "u1",
            "record": {
                "subscription": {"is_active": False, "status": "inactive"},
                "admin_grant": {"is_active": True},
            },
        }
        assert _is_pro(user) is True

    def test_expired_grant_falls_back_to_subscription(self):
        """Expired grant must not mask an otherwise-active subscription."""
        past = datetime.now(UTC) - timedelta(days=1)
        user = {
            "id": "u1",
            "record": {
                "subscription": {"is_active": True, "status": "active"},
                "admin_grant": {"is_active": True, "expires_at": _iso(past)},
            },
        }
        assert _is_pro(user) is True

    def test_expired_grant_and_inactive_subscription_is_not_pro(self):
        past = datetime.now(UTC) - timedelta(days=1)
        user = {
            "id": "u1",
            "record": {
                "subscription": {"is_active": False},
                "admin_grant": {"is_active": True, "expires_at": _iso(past)},
            },
        }
        assert _is_pro(user) is False

    def test_inactive_grant_does_not_grant_pro(self):
        user = {"id": "u1", "record": {"admin_grant": {"is_active": False}}}
        assert _is_pro(user) is False

    # ── subscription expiry recheck ──────────────────────────────────
    # Guards against the bug where a stored subscription with a stale
    # is_active=True flag keeps granting Pro forever if the Apple
    # EXPIRED notification never arrives. The expires_at timestamp must
    # be honoured over the static flag — mirroring admin_grant_is_active.

    def test_subscription_expired_despite_is_active_flag(self):
        """is_active=True + active status but expires_at in the past → NOT pro."""
        past = datetime.now(UTC) - timedelta(days=1)
        user = {
            "id": "u1",
            "record": {
                "subscription": {
                    "is_active": True,
                    "status": "active",
                    "expires_at": _iso(past),
                }
            },
        }
        assert _is_pro(user) is False

    def test_subscription_trial_expired_is_not_pro(self):
        """Trial status with a past expiry must also lose Pro."""
        past = datetime.now(UTC) - timedelta(seconds=1)
        user = {
            "id": "u1",
            "record": {
                "subscription": {
                    "is_active": True,
                    "status": "trial",
                    "expires_at": _iso(past),
                }
            },
        }
        assert _is_pro(user) is False

    def test_subscription_future_expiry_is_pro(self):
        """Active subscription whose expiry is still in the future stays Pro."""
        future = datetime.now(UTC) + timedelta(days=30)
        user = {
            "id": "u1",
            "record": {
                "subscription": {
                    "is_active": True,
                    "status": "active",
                    "expires_at": _iso(future),
                }
            },
        }
        assert _is_pro(user) is True

    def test_subscription_active_without_expiry_is_pro(self):
        """An active sub with no expires_at must not be downgraded (no regression)."""
        user = {
            "id": "u1",
            "record": {"subscription": {"is_active": True, "status": "active"}},
        }
        assert _is_pro(user) is True

    def test_subscription_grace_period_past_expiry_stays_pro(self):
        """grace_period legitimately has a past expires_at — must remain Pro."""
        past = datetime.now(UTC) - timedelta(days=1)
        user = {
            "id": "u1",
            "record": {
                "subscription": {
                    "is_active": True,
                    "status": "grace_period",
                    "expires_at": _iso(past),
                }
            },
        }
        assert _is_pro(user) is True


# ── _with_quota_check: allow path ────────────────────────────────────


class TestWithQuotaCheckAllow:
    def test_under_limit_runs_handler(self, mock_db):
        called = []

        def handler():
            called.append(True)
            return "ok"

        result = _with_quota_check({"id": "u1"}, "translate", None, handler)
        assert result == "ok"
        assert called == [True]

    def test_passes_through_handler_return_value(self, mock_db):
        payload = {"translation": "hola"}
        result = _with_quota_check({"id": "u1"}, "translate", None, lambda: payload)
        assert result is payload

    def test_pro_user_uses_pro_limit(self, mock_db):
        """Usage above free limit but below pro limit → pro user passes."""
        # $0.10 used: 1,000,000 input tokens. Over free $0.03, under pro $0.30.
        _insert_usage(mock_db, "u1", "translate", 1_000_000)
        pro_user = {"id": "u1", "record": {"subscription": {"is_active": True}}}
        result = _with_quota_check(pro_user, "translate", None, lambda: "ok")
        assert result == "ok"

    def test_same_usage_blocks_free_user(self, mock_db):
        """Same $0.10 usage that a pro passes → free user is blocked."""
        _insert_usage(mock_db, "u1", "translate", 1_000_000)
        with pytest.raises(QuotaExceededError):
            _with_quota_check({"id": "u1"}, "translate", None, lambda: "ok")


# ── _with_quota_check: block path ────────────────────────────────────


class TestWithQuotaCheckBlock:
    def test_exactly_at_limit_blocks(self, mock_db):
        """used >= limit is exceeded — exactly == limit must block.

        Free limit $0.03 = 300,000 input tokens at $0.10/M.
        """
        _insert_usage(mock_db, "u1", "translate", 300_000)
        with pytest.raises(QuotaExceededError):
            _with_quota_check({"id": "u1"}, "translate", None, lambda: "ok")

    def test_over_limit_blocks(self, mock_db):
        _insert_usage(mock_db, "u1", "translate", 500_000)
        with pytest.raises(QuotaExceededError):
            _with_quota_check({"id": "u1"}, "translate", None, lambda: "ok")

    def test_handler_never_called_when_exceeded(self, mock_db):
        """The whole point of the gate: an over-quota request must not
        reach the LLM. Handler invocation is the side effect we forbid.
        """
        _insert_usage(mock_db, "u1", "translate", 400_000)
        called = []

        def handler():
            called.append(True)
            return "should-not-happen"

        with pytest.raises(QuotaExceededError):
            _with_quota_check({"id": "u1"}, "translate", None, handler)
        assert called == [], "handler must not run once quota is exceeded"

    def test_exceeded_response_headers_untouched(self, mock_db):
        """On block, the passed Response object gets no quota headers —
        the error carries them instead.
        """
        _insert_usage(mock_db, "u1", "translate", 400_000)
        resp = Response()
        with pytest.raises(QuotaExceededError):
            _with_quota_check({"id": "u1"}, "translate", resp, lambda: "ok")
        assert "X-Quota-Fraction" not in resp.headers
        assert "X-Quota-Reset" not in resp.headers

    def test_quota_exceeded_error_contract(self, mock_db):
        """QuotaExceededError must carry status 429 + the documented headers."""
        _insert_usage(mock_db, "u1", "translate", 400_000)
        with pytest.raises(QuotaExceededError) as exc_info:
            _with_quota_check({"id": "u1"}, "translate", None, lambda: "ok")
        err = exc_info.value
        assert err.status_code == 429
        assert err.headers["X-Quota-Fraction"] == "0.0"
        assert err.headers["X-Quota-Reset"] == "86400"
        assert err.reset_seconds == 86400
        assert err.to_detail() == {"code": "quota_exhausted", "reset_seconds": 86400}


# ── X-Quota-Fraction header math ─────────────────────────────────────


class TestQuotaFractionHeader:
    def test_full_quota_fraction_is_one(self, mock_db):
        """No usage → full quota remaining → fraction 1.0."""
        resp = Response()
        _with_quota_check({"id": "u1"}, "translate", resp, lambda: "ok")
        assert resp.headers["X-Quota-Fraction"] == "1.0"
        assert resp.headers["X-Quota-Reset"] == "86400"

    def test_half_quota_fraction_is_about_half(self, mock_db):
        """Burn half the free limit → remaining fraction ≈ 0.5.

        Free limit $0.03; half = $0.015 = 150,000 input tokens.
        """
        _insert_usage(mock_db, "u1", "translate", 150_000)
        resp = Response()
        _with_quota_check({"id": "u1"}, "translate", resp, lambda: "ok")
        fraction = float(resp.headers["X-Quota-Fraction"])
        assert fraction == pytest.approx(0.5, abs=0.01)

    def test_response_none_does_not_crash(self, mock_db):
        """Endpoints may pass response=None — handler still runs, no error."""
        result = _with_quota_check({"id": "u1"}, "translate", None, lambda: "ok")
        assert result == "ok"

    def test_partial_usage_fraction_between_zero_and_one(self, mock_db):
        """A near-limit but not exceeded user → 0 < fraction < 1."""
        # $0.027 of $0.03 → 270,000 input tokens, still under limit.
        _insert_usage(mock_db, "u1", "translate", 270_000)
        resp = Response()
        _with_quota_check({"id": "u1"}, "translate", resp, lambda: "ok")
        fraction = float(resp.headers["X-Quota-Fraction"])
        assert 0.0 < fraction < 1.0


# ── error paths ──────────────────────────────────────────────────────


class TestErrorPaths:
    def test_missing_id_raises_keyerror(self, mock_db):
        """user dict without 'id' — KeyError surfaces (no silent swallow)."""
        with pytest.raises(KeyError):
            _with_quota_check({"record": None}, "translate", None, lambda: "ok")

    def test_handler_exception_propagates(self, mock_db):
        """Handler errors must bubble out unchanged after the gate opens."""

        class Boom(RuntimeError):
            pass

        def handler():
            raise Boom("downstream failure")

        with pytest.raises(Boom, match="downstream failure"):
            _with_quota_check({"id": "u1"}, "translate", None, handler)

    def test_handler_exception_leaves_no_headers(self, mock_db):
        """If the handler raises, header-writing code after it never runs."""

        def handler():
            raise RuntimeError("boom")

        resp = Response()
        with pytest.raises(RuntimeError):
            _with_quota_check({"id": "u1"}, "translate", resp, handler)
        assert "X-Quota-Fraction" not in resp.headers
