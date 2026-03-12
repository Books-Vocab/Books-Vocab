from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from kg.billing import (
    admin_grant_is_active,
    bool_from_any,
    current_pro_entitlement_record,
    default_admin_grant_payload,
    default_subscription_payload,
    normalize_ms_timestamp,
    notification_status,
    status_from_transaction_payload,
    write_subscription_snapshot,
)


# ── default factories ──────────────────────────────────────────────────────────

def test_default_subscription_payload_schema():
    p = default_subscription_payload()
    assert p["is_active"] is False
    assert p["product_id"] is None
    assert p["plan_name"] == "Books & Vocab Pro"
    assert p["status"] == "inactive"
    assert p["is_trial"] is False
    assert p["trial_days"] == 7
    assert p["will_renew"] is False
    assert p["expires_at"] is None
    assert p["source"] == "app_store"
    assert p["last_synced_at"] is None


def test_default_admin_grant_payload_schema():
    p = default_admin_grant_payload()
    assert p["is_active"] is False
    assert p["plan_name"] == "Books & Vocab Pro"
    assert p["status"] == "inactive"
    assert p["source"] == "admin"
    assert p["expires_at"] is None
    assert p["granted_at"] is None
    assert p["granted_by"] is None
    assert p["reason"] is None
    assert p["last_synced_at"] is None


# ── admin_grant_is_active ──────────────────────────────────────────────────────

def _future_iso():
    return (datetime.now(tz=timezone.utc) + timedelta(days=30)).isoformat()


def _past_iso():
    return (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()


def test_admin_grant_is_active_true_not_expired():
    user = {"admin_grant": {"is_active": True, "expires_at": _future_iso()}}
    assert admin_grant_is_active(user) is True


def test_admin_grant_is_active_true_expired():
    user = {"admin_grant": {"is_active": True, "expires_at": _past_iso()}}
    assert admin_grant_is_active(user) is False


def test_admin_grant_is_active_false():
    user = {"admin_grant": {"is_active": False, "expires_at": _future_iso()}}
    assert admin_grant_is_active(user) is False


def test_admin_grant_is_active_no_record():
    assert admin_grant_is_active({}) is False
    assert admin_grant_is_active(None) is False


# ── current_pro_entitlement_record ─────────────────────────────────────────────

def test_entitlement_admin_grant_takes_priority():
    user = {
        "admin_grant": {"is_active": True, "expires_at": _future_iso()},
        "subscription": {"is_active": True, "status": "active", "product_id": "sub_pro"},
    }
    rec = current_pro_entitlement_record(user)
    assert rec["source"] == "admin"
    assert rec["is_active"] is True


def test_entitlement_falls_back_to_subscription():
    user = {
        "admin_grant": {"is_active": False},
        "subscription": {"is_active": True, "status": "active", "product_id": "sub_pro"},
    }
    rec = current_pro_entitlement_record(user)
    assert rec["source"] == "app_store"


def test_entitlement_free_when_both_absent():
    rec = current_pro_entitlement_record({})
    assert rec["is_active"] is False
    assert rec["status"] == "inactive"


# ── notification_status ────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,sub,expected", [
    ("SUBSCRIBED", "INITIAL_BUY", "trial"),
    ("SUBSCRIBED", None, "active"),
    ("DID_RENEW", None, "active"),
    ("OFFER_REDEEMED", None, "active"),
    ("DID_FAIL_TO_RENEW", None, "grace_period"),
    ("GRACE_PERIOD_EXPIRED", None, "expired"),
    ("EXPIRED", None, "expired"),
    ("REVOKE", None, "expired"),
    ("UNKNOWN_TYPE", None, "active"),
])
def test_notification_status(kind, sub, expected):
    assert notification_status(kind, sub) == expected


# ── status_from_transaction_payload ───────────────────────────────────────────

def _parse_dt(raw):
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def test_status_from_payload_revocation_date():
    payload = {"revocationDate": "2024-01-01T00:00:00+00:00", "expiresDate": None}
    assert status_from_transaction_payload(payload, _parse_dt) == "expired"


def test_status_from_payload_expired_by_date():
    past_ms = int((_past_iso_dt() - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds() * 1000)
    payload = {"expiresDate": past_ms}
    assert status_from_transaction_payload(payload, _parse_dt) == "expired"


def _past_iso_dt():
    return datetime.now(tz=timezone.utc) - timedelta(days=2)


def test_status_from_payload_grace_period():
    # expiresDate not set (None), gracePeriodExpiresDate in the future → grace_period
    future_ms = int(
        (datetime.now(tz=timezone.utc) + timedelta(days=5) - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()
        * 1000
    )
    payload = {"expiresDate": None}
    renewal = {"gracePeriodExpiresDate": future_ms, "autoRenewStatus": True}
    assert status_from_transaction_payload(payload, _parse_dt, renewal) == "grace_period"


def test_status_from_payload_trial_offer_type():
    future_ms = int(
        (datetime.now(tz=timezone.utc) + timedelta(days=7) - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()
        * 1000
    )
    payload = {"expiresDate": future_ms, "offerType": 1}
    assert status_from_transaction_payload(payload, _parse_dt) == "trial"


def test_status_from_payload_active():
    future_ms = int(
        (datetime.now(tz=timezone.utc) + timedelta(days=30) - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()
        * 1000
    )
    payload = {"expiresDate": future_ms}
    assert status_from_transaction_payload(payload, _parse_dt) == "active"


# ── normalize_ms_timestamp ─────────────────────────────────────────────────────

def test_normalize_ms_timestamp_integer():
    result = normalize_ms_timestamp(1_700_000_000_000, _parse_dt)
    assert result is not None
    assert "2023" in result


def test_normalize_ms_timestamp_string_passthrough():
    iso = "2024-06-01T12:00:00+00:00"
    result = normalize_ms_timestamp(iso, _parse_dt)
    assert result == iso


def test_normalize_ms_timestamp_none():
    assert normalize_ms_timestamp(None, _parse_dt) is None


def test_normalize_ms_timestamp_invalid_string():
    result = normalize_ms_timestamp("not-a-date", _parse_dt)
    assert result is None


# ── bool_from_any ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (True, True),
    (False, False),
    (1, True),
    (0, False),
    ("true", True),
    ("True", True),
    ("1", True),
    ("yes", True),
    ("YES", True),
    ("false", False),
    ("no", False),
    ("", False),
    (None, False),
])
def test_bool_from_any(raw, expected):
    assert bool_from_any(raw) == expected


# ── write_subscription_snapshot ───────────────────────────────────────────────

def test_write_subscription_snapshot_active_sets_is_active():
    users = {}
    record = write_subscription_snapshot(
        users, "u1",
        product_id="pro_monthly",
        status="active",
        is_trial=False,
        expires_at=_future_iso(),
        will_renew=True,
        environment="production",
        transaction_id="txn-1",
        original_transaction_id="orig-1",
        price_display="$9.99",
        source="app_store",
    )
    sub = record["subscription"]
    assert sub["is_active"] is True
    assert sub["status"] == "active"


def test_write_subscription_snapshot_trial_is_active():
    users = {}
    record = write_subscription_snapshot(
        users, "u1",
        product_id="pro_monthly",
        status="trial",
        is_trial=True,
        expires_at=_future_iso(),
        will_renew=True,
        environment="sandbox",
        transaction_id="txn-2",
        original_transaction_id="orig-2",
        price_display=None,
        source="app_store",
    )
    assert record["subscription"]["is_active"] is True


def test_write_subscription_snapshot_grace_period_is_active():
    users = {}
    record = write_subscription_snapshot(
        users, "u1",
        product_id="pro_monthly",
        status="grace_period",
        is_trial=False,
        expires_at=_past_iso(),
        will_renew=False,
        environment="production",
        transaction_id="txn-3",
        original_transaction_id="orig-3",
        price_display=None,
        source="app_store",
    )
    assert record["subscription"]["is_active"] is True


def test_write_subscription_snapshot_expired_not_active():
    users = {}
    record = write_subscription_snapshot(
        users, "u1",
        product_id="pro_monthly",
        status="expired",
        is_trial=False,
        expires_at=_past_iso(),
        will_renew=False,
        environment="production",
        transaction_id="txn-4",
        original_transaction_id="orig-4",
        price_display=None,
        source="app_store",
    )
    assert record["subscription"]["is_active"] is False


def test_write_subscription_snapshot_preserves_existing_trial_days():
    users = {"u1": {"subscription": {"trial_days": 14}}}
    record = write_subscription_snapshot(
        users, "u1",
        product_id="pro_monthly",
        status="active",
        is_trial=False,
        expires_at=_future_iso(),
        will_renew=True,
        environment="production",
        transaction_id="txn-5",
        original_transaction_id="orig-5",
        price_display=None,
        source="app_store",
    )
    assert record["subscription"]["trial_days"] == 14
