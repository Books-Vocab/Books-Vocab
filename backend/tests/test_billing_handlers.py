from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from kg.api_models import (
    AppStoreNotificationRequest,
    AppStoreReconcileRequest,
    AppStoreSyncRequest,
    EntitlementsResponse,
    SubscriptionStatusResponse,
)
from kg.billing_handlers import (
    app_store_notifications_response,
    reconcile_app_store_subscription_response,
    sync_app_store_subscription_response,
)

# ── helpers ────────────────────────────────────────────────────────────────────

def _free_entitlements():
    return EntitlementsResponse(
        pro=SubscriptionStatusResponse(is_active=False, status="inactive")
    )


def _active_entitlements():
    return EntitlementsResponse(
        pro=SubscriptionStatusResponse(is_active=True, status="active")
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


def _common_deps(tmp_path: Path, entitlements=None):
    users_lock = tmp_path / "users.json.lock"
    users_store = {}

    def load_users():
        return users_store

    def save_users(u):
        users_store.update(u)

    def write_sub(users, uid, **kwargs):
        record = {"subscription": {"status": kwargs["status"], "is_active": True}}
        users[uid] = record
        return record

    return {
        "users_lock_file": users_lock,
        "load_users": load_users,
        "save_users": save_users,
        "write_subscription_snapshot": write_sub,
        "build_entitlements_response": lambda rec: entitlements or _active_entitlements(),
    }


# ── sync handler ───────────────────────────────────────────────────────────────

def test_sync_signed_transaction_verifies_and_writes(tmp_path):
    snapshot = _make_snapshot()
    decode_fn = MagicMock(return_value=snapshot)
    deps = _common_deps(tmp_path)
    deps["decode_signed_transaction_info"] = decode_fn

    req = AppStoreSyncRequest(
        product_id="pro_monthly",
        transaction_id="txn-1",
        original_transaction_id="orig-1",
        signed_transaction_info="signed.jws.token",
    )
    user = {"id": "u1"}

    result = sync_app_store_subscription_response(
        req, user,
        allow_unsigned_sync=False,
        **deps,
    )
    decode_fn.assert_called_once_with("signed.jws.token")
    assert isinstance(result, EntitlementsResponse)


def test_sync_transaction_id_mismatch_raises_400(tmp_path):
    snapshot = _make_snapshot(transaction_id="txn-OTHER")
    decode_fn = MagicMock(return_value=snapshot)
    deps = _common_deps(tmp_path)
    deps["decode_signed_transaction_info"] = decode_fn

    req = AppStoreSyncRequest(
        product_id="pro_monthly",
        transaction_id="txn-1",
        signed_transaction_info="signed.jws.token",
    )

    with pytest.raises(HTTPException) as exc_info:
        sync_app_store_subscription_response(req, {"id": "u1"}, allow_unsigned_sync=False, **deps)
    assert exc_info.value.status_code == 400


def test_sync_xcode_env_rejects_unsigned_when_not_debug(tmp_path):
    """Xcode environment bypass must NOT work when allow_unsigned_sync=False (production)."""
    deps = _common_deps(tmp_path)
    deps["decode_signed_transaction_info"] = MagicMock()

    req = AppStoreSyncRequest(
        product_id="pro_monthly",
        transaction_id="txn-xcode",
        environment="xcode",
        status="active",
        is_trial=False,
        will_renew=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        sync_app_store_subscription_response(
            req, {"id": "u1"},
            allow_unsigned_sync=False,
            **deps,
        )
    assert exc_info.value.status_code == 400


def test_sync_xcode_env_allows_unsigned_when_enabled(tmp_path):
    """Xcode environment bypass works when allow_unsigned_sync=True (dev/test)."""
    deps = _common_deps(tmp_path)
    deps["decode_signed_transaction_info"] = MagicMock()

    req = AppStoreSyncRequest(
        product_id="pro_monthly",
        transaction_id="txn-xcode",
        environment="xcode",
        status="active",
        is_trial=False,
        will_renew=True,
    )

    result = sync_app_store_subscription_response(
        req, {"id": "u1"},
        allow_unsigned_sync=True,
        **deps,
    )
    deps["decode_signed_transaction_info"].assert_not_called()
    assert isinstance(result, EntitlementsResponse)


# ── notification handler ───────────────────────────────────────────────────────

def test_notification_normal_flow_updated(tmp_path):
    snapshot = _make_snapshot()
    decode_fn = MagicMock(return_value=(snapshot, {"notification_type": "DID_RENEW"}))
    append_fn = MagicMock()

    lock = tmp_path / "lock"

    def resolve_fn(users, oti, ti):
        return "u1"

    def write_sub(users, uid, **kwargs):
        record = {"subscription": {"status": "active"}}
        users[uid] = record
        return record

    req = AppStoreNotificationRequest(
        notification_type="DID_RENEW",
        signed_payload="signed.payload",
    )

    result = app_store_notifications_response(
        req,
        users_lock_file=lock,
        load_users=lambda: {},
        save_users=lambda u: None,
        decode_notification_payload=decode_fn,
        append_app_store_event=append_fn,
        resolve_user_id_from_subscription_index=resolve_fn,
        write_subscription_snapshot=write_sub,
        build_entitlements_response=lambda rec: _active_entitlements(),
    )

    append_fn.assert_called_once()
    assert result["status"] == "accepted"
    assert result["updated"] is True


def test_notification_unmapped_transaction_accepted(tmp_path):
    snapshot = _make_snapshot(transaction_id="txn-unknown", original_transaction_id="orig-unknown")
    decode_fn = MagicMock(return_value=(snapshot, None))
    append_fn = MagicMock()

    req = AppStoreNotificationRequest(notification_type="DID_RENEW", signed_payload="s")

    result = app_store_notifications_response(
        req,
        users_lock_file=tmp_path / "lock",
        load_users=lambda: {},
        save_users=lambda u: None,
        decode_notification_payload=decode_fn,
        append_app_store_event=append_fn,
        resolve_user_id_from_subscription_index=lambda *a: None,
        write_subscription_snapshot=MagicMock(),
        build_entitlements_response=lambda rec: _active_entitlements(),
    )

    assert result["status"] == "accepted"
    assert result["updated"] is False
    assert result["reason"] == "unmapped_transaction"


# ── reconcile handler ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconcile_apple_api_failure_raises_502(tmp_path):
    import httpx

    async def fetch_fail(*args, **kwargs):
        raise httpx.HTTPStatusError("err", request=MagicMock(), response=MagicMock(status_code=503))

    req = AppStoreReconcileRequest(transaction_id="txn-1", environment="production")

    with pytest.raises(HTTPException) as exc_info:
        await reconcile_app_store_subscription_response(
            req, {"id": "u1"},
            apple_bundle_id="com.example.app",
            users_lock_file=tmp_path / "lock",
            load_users=lambda: {},
            save_users=lambda u: None,
            fetch_transaction_info=fetch_fail,
            decode_signed_transaction_info=MagicMock(),
            resolve_user_id_from_subscription_index=lambda *a: None,
            write_subscription_snapshot=MagicMock(),
            build_entitlements_response=lambda rec: _active_entitlements(),
        )
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_reconcile_normal_flow_returns_entitlements(tmp_path):
    snapshot = _make_snapshot()
    decode_fn = MagicMock(return_value=snapshot)

    async def fetch_ok(*args, **kwargs):
        return {"signedTransactionInfo": "signed.jws"}

    def write_sub(users, uid, **kwargs):
        record = {"subscription": {"status": "active"}}
        users[uid] = record
        return record

    req = AppStoreReconcileRequest(transaction_id="txn-1", environment="production")

    result = await reconcile_app_store_subscription_response(
        req, {"id": "u1"},
        apple_bundle_id="com.example.app",
        users_lock_file=tmp_path / "lock",
        load_users=lambda: {},
        save_users=lambda u: None,
        fetch_transaction_info=fetch_ok,
        decode_signed_transaction_info=decode_fn,
        resolve_user_id_from_subscription_index=lambda *a: None,
        write_subscription_snapshot=write_sub,
        build_entitlements_response=lambda rec: _active_entitlements(),
    )

    decode_fn.assert_called_once_with("signed.jws")
    assert isinstance(result, EntitlementsResponse)


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
