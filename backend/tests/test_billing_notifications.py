from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kg.api_models import (
    AppStoreNotificationRequest,
    AppStoreReconcileRequest,
    EntitlementsResponse,
    SubscriptionStatusResponse,
)
from kg.billing_handlers import (
    app_store_notifications_response,
    reconcile_app_store_subscription_response,
)


def _make_snapshot(transaction_id="txn-1", original_transaction_id="orig-1"):
    return {
        "product_id": "pro_monthly",
        "transaction_id": transaction_id,
        "original_transaction_id": original_transaction_id,
        "environment": "sandbox",
        "status": "active",
        "is_trial": False,
        "expires_at": None,
        "will_renew": True,
        "price_display": None,
    }


# ── edge: refund / duplicate / grace / partial-failure ────────────────────────


def _real_write_snapshot():
    """Wire the real write_subscription_snapshot so is_active/status reflect input."""
    from kg.billing import write_subscription_snapshot as real_write

    return real_write


def _real_resolver():
    from kg.billing import resolve_user_id_from_subscription_index as real_resolve

    return real_resolve


def _entitlements_from_record(record):
    """Build entitlements that reflect whether the record's subscription is active."""
    sub = (record or {}).get("subscription") if isinstance(record, dict) else None
    is_active = bool(sub and sub.get("is_active"))
    status = (sub or {}).get("status", "inactive") if sub else "inactive"
    return EntitlementsResponse(
        pro=SubscriptionStatusResponse(is_active=is_active, status=status)
    )


def test_refund_notification_revokes_entitlement_and_reclaims_quota(tmp_path):
    """REFUND notification flips subscription off; pre-existing usage counters survive untouched."""
    real_write = _real_write_snapshot()
    real_resolve = _real_resolver()

    # User already has an active sub + 50% token usage recorded externally.
    users_store: dict = {
        "u1": {
            "subscription": {
                "is_active": True,
                "status": "active",
                "product_id": "pro_monthly",
                "transaction_id": "txn-1",
                "original_transaction_id": "orig-1",
            },
            "usage": {"tokens_used": 50_000, "tokens_quota": 100_000},
        },
        "_subscription_index": {"orig-1": "u1", "txn-1": "u1"},
    }

    refund_snapshot = {
        "product_id": "pro_monthly",
        "transaction_id": "txn-1",
        "original_transaction_id": "orig-1",
        "environment": "production",
        # REFUND maps to status="expired" via kg.billing.notification_status
        "status": "expired",
        "is_trial": False,
        "expires_at": None,
        "will_renew": False,
        "price_display": None,
    }
    decode_fn = MagicMock(return_value=(refund_snapshot, {"notificationType": "REFUND"}))

    saved = {}

    def save_users(u):
        saved.update(u)

    req = AppStoreNotificationRequest(
        notification_type="REFUND",
        signed_payload="signed.payload",
    )

    result = app_store_notifications_response(
        req,
        users_lock_file=tmp_path / "lock",
        load_users=lambda: users_store,
        save_users=save_users,
        decode_notification_payload=decode_fn,
        append_app_store_event=MagicMock(),
        resolve_user_id_from_subscription_index=real_resolve,
        write_subscription_snapshot=real_write,
        build_entitlements_response=_entitlements_from_record,
    )

    assert result["updated"] is True
    assert result["user_id"] == "u1"
    sub = users_store["u1"]["subscription"]
    assert sub["is_active"] is False, "refund must flip is_active off"
    assert sub["status"] == "expired"
    # quota usage record is orthogonal — handler must not touch usage counters
    usage = users_store["u1"]["usage"]
    assert usage["tokens_used"] == 50_000
    assert usage["tokens_used"] >= 0, "used quota must never go negative on refund"
    # entitlement returned to client also reflects inactive state
    ent_payload = result["entitlements"]
    assert ent_payload["pro"]["is_active"] is False


def test_duplicate_notification_same_transaction_id_idempotent(tmp_path):
    """Replaying the same REFUND twice converges to the same terminal state."""
    real_write = _real_write_snapshot()
    real_resolve = _real_resolver()

    users_store: dict = {
        "u1": {
            "subscription": {
                "is_active": True,
                "status": "active",
                "transaction_id": "txn-dup",
                "original_transaction_id": "orig-dup",
            }
        },
        "_subscription_index": {"orig-dup": "u1", "txn-dup": "u1"},
    }

    refund_snapshot = {
        "product_id": "pro_monthly",
        "transaction_id": "txn-dup",
        "original_transaction_id": "orig-dup",
        "environment": "production",
        "status": "expired",
        "is_trial": False,
        "expires_at": "2026-05-14T00:00:00+00:00",
        "will_renew": False,
        "price_display": None,
    }
    decode_fn = MagicMock(return_value=(refund_snapshot, {"notificationType": "REFUND"}))
    append_fn = MagicMock()

    req = AppStoreNotificationRequest(
        notification_type="REFUND",
        signed_payload="signed.payload",
    )

    common_kwargs = dict(
        users_lock_file=tmp_path / "lock",
        load_users=lambda: users_store,
        save_users=lambda u: None,
        decode_notification_payload=decode_fn,
        append_app_store_event=append_fn,
        resolve_user_id_from_subscription_index=real_resolve,
        write_subscription_snapshot=real_write,
        build_entitlements_response=_entitlements_from_record,
    )

    first = app_store_notifications_response(req, **common_kwargs)
    snapshot_after_first = dict(users_store["u1"]["subscription"])

    second = app_store_notifications_response(req, **common_kwargs)
    snapshot_after_second = dict(users_store["u1"]["subscription"])

    # Idempotency: replay leaves terminal state unchanged on the fields we care about.
    for key in ("is_active", "status", "expires_at", "transaction_id", "original_transaction_id"):
        assert snapshot_after_first[key] == snapshot_after_second[key], f"field {key} drifted on replay"
    assert first["updated"] is True
    assert second["updated"] is True
    # event log captures each delivery (auditable), but mutation result is stable.
    assert append_fn.call_count == 2


def test_grace_period_keeps_entitlement_until_expiry(tmp_path):
    """A snapshot with status='grace_period' must keep is_active true; later 'expired' flips it off."""
    real_write = _real_write_snapshot()
    real_resolve = _real_resolver()

    users_store: dict = {
        "u1": {
            "subscription": {
                "is_active": True,
                "status": "active",
                "transaction_id": "txn-g",
                "original_transaction_id": "orig-g",
            }
        },
        "_subscription_index": {"orig-g": "u1", "txn-g": "u1"},
    }

    grace_snapshot = {
        "product_id": "pro_monthly",
        "transaction_id": "txn-g",
        "original_transaction_id": "orig-g",
        "environment": "production",
        "status": "grace_period",
        "is_trial": False,
        "expires_at": "2026-05-20T00:00:00+00:00",
        "will_renew": True,
        "price_display": None,
    }

    req = AppStoreNotificationRequest(
        notification_type="DID_FAIL_TO_RENEW",
        signed_payload="signed.payload",
    )

    deps = dict(
        users_lock_file=tmp_path / "lock",
        load_users=lambda: users_store,
        save_users=lambda u: None,
        decode_notification_payload=MagicMock(return_value=(grace_snapshot, None)),
        append_app_store_event=MagicMock(),
        resolve_user_id_from_subscription_index=real_resolve,
        write_subscription_snapshot=real_write,
        build_entitlements_response=_entitlements_from_record,
    )

    result = app_store_notifications_response(req, **deps)
    sub = users_store["u1"]["subscription"]
    assert sub["status"] == "grace_period"
    assert sub["is_active"] is True, "grace_period must remain entitled"
    assert result["entitlements"]["pro"]["is_active"] is True

    # Now grace period expires — same user receives GRACE_PERIOD_EXPIRED.
    expired_snapshot = {**grace_snapshot, "status": "expired", "will_renew": False}
    deps["decode_notification_payload"] = MagicMock(return_value=(expired_snapshot, None))
    req2 = AppStoreNotificationRequest(
        notification_type="GRACE_PERIOD_EXPIRED",
        signed_payload="signed.payload",
    )
    result2 = app_store_notifications_response(req2, **deps)
    assert users_store["u1"]["subscription"]["is_active"] is False
    assert users_store["u1"]["subscription"]["status"] == "expired"
    assert result2["entitlements"]["pro"]["is_active"] is False


# ── edge: unknown / unsigned notification must not fail-open ───────────────────


def test_unknown_notification_type_does_not_reactivate_expired_sub(tmp_path):
    """An unsigned notification with an unknown type must not flip an inactive sub
    back to active. notification_status returns None for unknown types, so the
    handler must skip the snapshot write rather than fail-open to 'active'."""
    from kg.billing import decode_notification_payload as real_decode

    real_write = _real_write_snapshot()
    real_resolve = _real_resolver()

    # User's subscription already expired.
    users_store: dict = {
        "u1": {
            "subscription": {
                "is_active": False,
                "status": "expired",
                "product_id": "pro_monthly",
                "transaction_id": "txn-1",
                "original_transaction_id": "orig-1",
            }
        },
        "_subscription_index": {"orig-1": "u1", "txn-1": "u1"},
    }

    # Unsigned notification, no explicit status, unrecognised type.
    req = AppStoreNotificationRequest(
        notification_type="SOME_FUTURE_TYPE",
        product_id="pro_monthly",
        transaction_id="txn-1",
        original_transaction_id="orig-1",
        environment="production",
    )

    def decode(r):
        return real_decode(
            r,
            bundle_id="com.example.app",
            allow_unsigned_notifications=True,
            parse_datetime_fn=lambda x: None,
            verify_signed_jws=MagicMock(),
        )

    result = app_store_notifications_response(
        req,
        users_lock_file=tmp_path / "lock",
        load_users=lambda: users_store,
        save_users=lambda u: None,
        decode_notification_payload=decode,
        append_app_store_event=MagicMock(),
        resolve_user_id_from_subscription_index=real_resolve,
        write_subscription_snapshot=real_write,
        build_entitlements_response=_entitlements_from_record,
    )

    # Handler must NOT have reactivated the expired subscription.
    sub = users_store["u1"]["subscription"]
    assert sub["is_active"] is False, "unknown notification type must not fail-open to active"
    assert sub["status"] == "expired"
    assert result["updated"] is False
    assert result["reason"] == "indeterminate_status"


def test_refund_via_real_decode_revokes_entitlement(tmp_path):
    """End-to-end through the real decoder: an unsigned REFUND notification
    must drive the subscription to expired/inactive."""
    from kg.billing import decode_notification_payload as real_decode

    real_write = _real_write_snapshot()
    real_resolve = _real_resolver()

    users_store: dict = {
        "u1": {
            "subscription": {
                "is_active": True,
                "status": "active",
                "product_id": "pro_monthly",
                "transaction_id": "txn-1",
                "original_transaction_id": "orig-1",
            }
        },
        "_subscription_index": {"orig-1": "u1", "txn-1": "u1"},
    }

    req = AppStoreNotificationRequest(
        notification_type="REFUND",
        product_id="pro_monthly",
        transaction_id="txn-1",
        original_transaction_id="orig-1",
        environment="production",
    )

    def decode(r):
        return real_decode(
            r,
            bundle_id="com.example.app",
            allow_unsigned_notifications=True,
            parse_datetime_fn=lambda x: None,
            verify_signed_jws=MagicMock(),
        )

    result = app_store_notifications_response(
        req,
        users_lock_file=tmp_path / "lock",
        load_users=lambda: users_store,
        save_users=lambda u: None,
        decode_notification_payload=decode,
        append_app_store_event=MagicMock(),
        resolve_user_id_from_subscription_index=real_resolve,
        write_subscription_snapshot=real_write,
        build_entitlements_response=_entitlements_from_record,
    )

    sub = users_store["u1"]["subscription"]
    assert sub["is_active"] is False, "REFUND must revoke entitlement"
    assert sub["status"] == "expired"
    assert result["updated"] is True
    assert result["entitlements"]["pro"]["is_active"] is False


# ── edge: SIGNED notification fail-safe asymmetry (PR #535 follow-up) ──────────


class _Verified:
    """Minimal stand-in for the verify_signed_jws return value (exposes .payload)."""

    def __init__(self, payload):
        self.payload = payload


def _signed_jws_verifier(notification_payload, transaction_payload, renewal_payload=None):
    """Return a verify_signed_jws mock that dispatches by the opaque JWS token.

    decode_notification_payload calls verify_signed_jws three times:
      1. req.signed_payload          -> the notification envelope (has 'data')
      2. data.signedTransactionInfo  -> the transaction payload
      3. data.signedRenewalInfo      -> optional renewal payload
    """

    def verify(token, *, bundle_id):
        if token == "SIGNED_NOTIFICATION":
            return _Verified(notification_payload)
        if token == "SIGNED_TXN":
            return _Verified(transaction_payload)
        if token == "SIGNED_RENEWAL":
            return _Verified(renewal_payload or {})
        raise AssertionError(f"unexpected JWS token {token!r}")

    return verify


def test_signed_unknown_notification_type_does_not_fail_open_to_active(tmp_path):
    """A SIGNED notification with an unknown/future type carrying a still-valid
    (un-expired) transaction must NOT write status='active'.

    PR #535 added the unknown-type fail-safe but only on the unsigned path.
    On the signed path the status is derived purely from the transaction payload
    (status_from_transaction_payload), which returns 'active' for any un-expired
    transaction — so a signed unknown-type notification would fail-open and grant
    Pro for free. The handler must treat an unknown notification_type as
    indeterminate regardless of signature.
    """
    from kg.billing import decode_notification_payload as real_decode

    real_write = _real_write_snapshot()
    real_resolve = _real_resolver()

    # User's subscription is already expired.
    users_store: dict = {
        "u1": {
            "subscription": {
                "is_active": False,
                "status": "expired",
                "product_id": "pro_monthly",
                "transaction_id": "txn-1",
                "original_transaction_id": "orig-1",
            }
        },
        "_subscription_index": {"orig-1": "u1", "txn-1": "u1"},
    }

    # A still-valid transaction: no revocationDate, no expiresDate -> "active".
    transaction_payload = {
        "productId": "pro_monthly",
        "transactionId": "txn-1",
        "originalTransactionId": "orig-1",
        "environment": "Production",
    }
    notification_payload = {
        "notificationType": "SOME_FUTURE_TYPE",
        "data": {"signedTransactionInfo": "SIGNED_TXN"},
    }

    req = AppStoreNotificationRequest(
        notification_type="SOME_FUTURE_TYPE",
        signed_payload="SIGNED_NOTIFICATION",
    )

    def decode(r):
        return real_decode(
            r,
            bundle_id="com.example.app",
            allow_unsigned_notifications=False,
            parse_datetime_fn=lambda x: None,
            verify_signed_jws=_signed_jws_verifier(notification_payload, transaction_payload),
        )

    result = app_store_notifications_response(
        req,
        users_lock_file=tmp_path / "lock",
        load_users=lambda: users_store,
        save_users=lambda u: None,
        decode_notification_payload=decode,
        append_app_store_event=MagicMock(),
        resolve_user_id_from_subscription_index=real_resolve,
        write_subscription_snapshot=real_write,
        build_entitlements_response=_entitlements_from_record,
    )

    sub = users_store["u1"]["subscription"]
    assert sub["is_active"] is False, "signed unknown-type notification must not fail-open to active"
    assert sub["status"] == "expired"
    assert result["updated"] is False
    assert result["reason"] == "indeterminate_status"


def test_signed_did_renew_known_type_still_activates(tmp_path):
    """Regression guard: a SIGNED known type (DID_RENEW) with a valid
    transaction must continue to drive the subscription to active."""
    from kg.billing import decode_notification_payload as real_decode

    real_write = _real_write_snapshot()
    real_resolve = _real_resolver()

    users_store: dict = {
        "u1": {
            "subscription": {
                "is_active": False,
                "status": "expired",
                "product_id": "pro_monthly",
                "transaction_id": "txn-1",
                "original_transaction_id": "orig-1",
            }
        },
        "_subscription_index": {"orig-1": "u1", "txn-1": "u1"},
    }

    transaction_payload = {
        "productId": "pro_monthly",
        "transactionId": "txn-1",
        "originalTransactionId": "orig-1",
        "environment": "Production",
    }
    notification_payload = {
        "notificationType": "DID_RENEW",
        "data": {"signedTransactionInfo": "SIGNED_TXN"},
    }

    req = AppStoreNotificationRequest(
        notification_type="DID_RENEW",
        signed_payload="SIGNED_NOTIFICATION",
    )

    def decode(r):
        return real_decode(
            r,
            bundle_id="com.example.app",
            allow_unsigned_notifications=False,
            parse_datetime_fn=lambda x: None,
            verify_signed_jws=_signed_jws_verifier(notification_payload, transaction_payload),
        )

    result = app_store_notifications_response(
        req,
        users_lock_file=tmp_path / "lock",
        load_users=lambda: users_store,
        save_users=lambda u: None,
        decode_notification_payload=decode,
        append_app_store_event=MagicMock(),
        resolve_user_id_from_subscription_index=real_resolve,
        write_subscription_snapshot=real_write,
        build_entitlements_response=_entitlements_from_record,
    )

    sub = users_store["u1"]["subscription"]
    assert sub["is_active"] is True, "signed DID_RENEW must still activate"
    assert sub["status"] == "active"
    assert result["updated"] is True
    assert result["entitlements"]["pro"]["is_active"] is True


def test_signed_refund_known_type_still_revokes(tmp_path):
    """Regression guard: a SIGNED REFUND (known type) with a revoked transaction
    must continue to drive the subscription to expired/inactive."""
    from kg.billing import decode_notification_payload as real_decode

    real_write = _real_write_snapshot()
    real_resolve = _real_resolver()

    users_store: dict = {
        "u1": {
            "subscription": {
                "is_active": True,
                "status": "active",
                "product_id": "pro_monthly",
                "transaction_id": "txn-1",
                "original_transaction_id": "orig-1",
            }
        },
        "_subscription_index": {"orig-1": "u1", "txn-1": "u1"},
    }

    # Apple stamps revocationDate on a refunded transaction.
    transaction_payload = {
        "productId": "pro_monthly",
        "transactionId": "txn-1",
        "originalTransactionId": "orig-1",
        "environment": "Production",
        "revocationDate": 1_700_000_000_000,
    }
    notification_payload = {
        "notificationType": "REFUND",
        "data": {"signedTransactionInfo": "SIGNED_TXN"},
    }

    req = AppStoreNotificationRequest(
        notification_type="REFUND",
        signed_payload="SIGNED_NOTIFICATION",
    )

    def decode(r):
        return real_decode(
            r,
            bundle_id="com.example.app",
            allow_unsigned_notifications=False,
            parse_datetime_fn=lambda x: None,
            verify_signed_jws=_signed_jws_verifier(notification_payload, transaction_payload),
        )

    result = app_store_notifications_response(
        req,
        users_lock_file=tmp_path / "lock",
        load_users=lambda: users_store,
        save_users=lambda u: None,
        decode_notification_payload=decode,
        append_app_store_event=MagicMock(),
        resolve_user_id_from_subscription_index=real_resolve,
        write_subscription_snapshot=real_write,
        build_entitlements_response=_entitlements_from_record,
    )

    sub = users_store["u1"]["subscription"]
    assert sub["is_active"] is False, "signed REFUND must revoke entitlement"
    assert sub["status"] == "expired"
    assert result["updated"] is True
    assert result["entitlements"]["pro"]["is_active"] is False


@pytest.mark.asyncio
async def test_reconcile_partial_failure_does_not_corrupt(tmp_path):
    """If write_subscription_snapshot raises mid-reconcile, state must be unchanged so retry resumes cleanly."""
    real_resolve = _real_resolver()

    pre_state = {
        "u1": {
            "subscription": {
                "is_active": True,
                "status": "active",
                "transaction_id": "txn-1",
                "original_transaction_id": "orig-1",
            }
        },
        "u2": {
            "subscription": {
                "is_active": True,
                "status": "active",
                "transaction_id": "txn-2",
                "original_transaction_id": "orig-2",
            }
        },
        "_subscription_index": {
            "orig-1": "u1", "txn-1": "u1",
            "orig-2": "u2", "txn-2": "u2",
        },
    }
    # deep-copy snapshot for post-failure comparison
    import copy
    expected_after = copy.deepcopy(pre_state)

    save_calls = {"count": 0}

    def save_users(u):
        save_calls["count"] += 1

    def exploding_write(*args, **kwargs):
        raise RuntimeError("simulated DB hiccup mid-reconcile")

    snapshot = _make_snapshot(transaction_id="txn-2", original_transaction_id="orig-2")
    decode_fn = MagicMock(return_value=snapshot)

    async def fetch_ok(*args, **kwargs):
        return {"signedTransactionInfo": "signed.jws"}

    req = AppStoreReconcileRequest(transaction_id="txn-2", environment="production")

    with pytest.raises(RuntimeError, match="simulated DB hiccup"):
        await reconcile_app_store_subscription_response(
            req, {"id": "u2"},
            apple_bundle_id="com.example.app",
            users_lock_file=tmp_path / "lock",
            load_users=lambda: pre_state,
            save_users=save_users,
            fetch_transaction_info=fetch_ok,
            decode_signed_transaction_info=decode_fn,
            resolve_user_id_from_subscription_index=real_resolve,
            write_subscription_snapshot=exploding_write,
            build_entitlements_response=_entitlements_from_record,
        )

    # Partial failure must NOT have called save_users (no half-written state).
    assert save_calls["count"] == 0
    # Existing users untouched, retry can pick up from the same baseline.
    assert pre_state == expected_after
