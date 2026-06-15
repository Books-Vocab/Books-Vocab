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


def test_sync_forged_cert_chain_maps_to_400_not_500(tmp_path, monkeypatch):
    """End-to-end boundary: a JWS whose cert chain has a forged inner link (real
    trusted root at the tail, but the leaf signed by an attacker key) must surface
    as HTTP 400 through ``_map_app_store_errors``, NOT as an unmapped 500.

    cryptography raises ``InvalidSignature`` on the chain signature check; if that
    escapes ``AppStoreVerificationError`` it would never be caught by the handler's
    error mapper and FastAPI would return 500. This proves the real verifier
    collapses it to the domain error so the contract is 400.
    """
    import base64
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID, ObjectIdentifier

    from kg.app_store import verify_and_decode_signed_jws

    apple_oid = ObjectIdentifier("1.2.840.113635.100.6.11.1")
    now = datetime.now(tz=UTC)

    def _cert(cn, pub_key, issuer_name, signing_key, *, ca, exts=()):
        builder = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
            .issuer_name(issuer_name)
            .public_key(pub_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        )
        for ext in exts:
            builder = builder.add_extension(ext, critical=False)
        return builder.sign(private_key=signing_key, algorithm=hashes.SHA256())

    root_key = ec.generate_private_key(ec.SECP256R1())
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Apple Root")])
    root_cert = _cert("Test Apple Root", root_key.public_key(), root_name, root_key, ca=True)

    inter_key = ec.generate_private_key(ec.SECP256R1())
    inter_cert = _cert(
        "Test Apple Intermediate", inter_key.public_key(), root_cert.subject, root_key, ca=True
    )

    # Forge the leaf: signed by an attacker key, not the genuine intermediate.
    attacker_key = ec.generate_private_key(ec.SECP256R1())
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf_cert = _cert(
        "Test Apple Leaf",
        leaf_key.public_key(),
        inter_cert.subject,
        attacker_key,
        ca=False,
        exts=[x509.UnrecognizedExtension(apple_oid, b"\x05\x00")],
    )

    root_pem = tmp_path / "root.pem"
    root_pem.write_text(root_cert.public_bytes(serialization.Encoding.PEM).decode("utf-8"))
    monkeypatch.setenv("APP_STORE_ROOT_CA_PATH", str(root_pem))
    monkeypatch.delenv("APP_STORE_ROOT_CA_PEM", raising=False)

    x5c = [
        base64.b64encode(c.public_bytes(serialization.Encoding.DER)).decode("ascii")
        for c in (leaf_cert, inter_cert, root_cert)
    ]
    payload = {
        "bundleId": "com.Max0228.BooksBrowser",
        "transactionId": "txn-1",
        "exp": int(now.timestamp()) + 3600,
    }
    token = pyjwt.encode(payload, leaf_key, algorithm="ES256", headers={"alg": "ES256", "x5c": x5c})

    def decode_fn(signed: str):
        verify_and_decode_signed_jws(signed, bundle_id="com.Max0228.BooksBrowser")
        return _make_snapshot()  # unreachable — verification must raise first

    deps = _common_deps(tmp_path)
    deps["decode_signed_transaction_info"] = decode_fn

    req = AppStoreSyncRequest(
        product_id="pro_monthly",
        transaction_id="txn-1",
        signed_transaction_info=token,
    )

    with pytest.raises(HTTPException) as exc_info:
        sync_app_store_subscription_response(
            req, {"id": "u1"}, allow_unsigned_sync=False, **deps
        )
    assert exc_info.value.status_code == 400


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
    On the signed path the status is derived purely from the transaction
    payload (status_from_transaction_payload), which returns 'active' for any
    un-expired transaction — so a signed unknown-type notification would
    fail-open and grant Pro for free. The handler must treat an unknown
    notification_type as indeterminate regardless of signature.
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
