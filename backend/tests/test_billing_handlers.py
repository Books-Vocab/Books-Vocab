from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from kg.api_models import AppStoreNotificationRequest, AppStoreReconcileRequest, AppStoreSyncRequest, EntitlementsResponse, SubscriptionStatusResponse
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


def test_sync_xcode_env_allows_unsigned(tmp_path):
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
        allow_unsigned_sync=False,
        **deps,
    )
    deps["decode_signed_transaction_info"].assert_not_called()
    assert isinstance(result, EntitlementsResponse)


# ── notification handler ───────────────────────────────────────────────────────

def test_notification_normal_flow_updated(tmp_path):
    snapshot = _make_snapshot()
    decode_fn = MagicMock(return_value=(snapshot, {"notification_type": "DID_RENEW"}))
    append_fn = MagicMock()

    users_store = {"orig-1": "u1"}
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
