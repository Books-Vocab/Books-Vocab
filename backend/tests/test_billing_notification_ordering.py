from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from kg.api_models import AppStoreNotificationRequest, EntitlementsResponse, SubscriptionStatusResponse
from kg.billing.notifications import decode_notification_payload
from kg.billing.snapshots import write_subscription_snapshot
from kg.billing_handlers import app_store_notifications_response
from kg.user_store import parse_datetime


def _entitlements(record):
    subscription = record.get("subscription", {})
    return EntitlementsResponse(
        pro=SubscriptionStatusResponse(
            is_active=subscription.get("is_active", False),
            status=subscription.get("status", "inactive"),
        )
    )


def _snapshot(*, status: str, signed_date: str, notification_uuid: str):
    return {
        "product_id": "pro_monthly",
        "transaction_id": f"txn-{notification_uuid}",
        "original_transaction_id": "orig-1",
        "environment": "production",
        "status": status,
        "is_trial": False,
        "expires_at": None,
        "will_renew": status == "active",
        "price_display": None,
        "signed_date": signed_date,
        "notification_uuid": notification_uuid,
    }


def _send_notification(tmp_path: Path, users, events, snapshot, notification_type: str):
    def append_event(event):
        events.append(deepcopy(event))

    return app_store_notifications_response(
        AppStoreNotificationRequest(
            notification_type=notification_type,
            signed_payload=f"signed-{snapshot['notification_uuid']}",
        ),
        users_lock_file=tmp_path / "users.lock",
        load_users=lambda: users,
        save_users=lambda updated: None,
        decode_notification_payload=lambda request: (snapshot, {"notificationType": notification_type}),
        append_app_store_event=append_event,
        resolve_user_id_from_subscription_index=lambda loaded, original, transaction: "u1",
        write_subscription_snapshot=write_subscription_snapshot,
        build_entitlements_response=_entitlements,
    )


def test_newer_refund_cannot_be_reopened_by_older_renew(tmp_path):
    users = {}
    events = []

    _send_notification(
        tmp_path,
        users,
        events,
        _snapshot(status="expired", signed_date="2026-08-01T00:00:00+00:00", notification_uuid="refund"),
        "REFUND",
    )
    result = _send_notification(
        tmp_path,
        users,
        events,
        _snapshot(status="active", signed_date="2026-07-31T00:00:00+00:00", notification_uuid="renew-old"),
        "DID_RENEW",
    )

    assert users["u1"]["subscription"]["status"] == "expired"
    assert users["u1"]["subscription"]["is_active"] is False
    assert result["updated"] is False
    assert len(events) == 2


def test_newer_expired_cannot_be_reopened_by_older_active(tmp_path):
    users = {}
    events = []

    _send_notification(
        tmp_path,
        users,
        events,
        _snapshot(status="expired", signed_date="2026-08-02T00:00:00+00:00", notification_uuid="expired"),
        "EXPIRED",
    )
    result = _send_notification(
        tmp_path,
        users,
        events,
        _snapshot(status="active", signed_date="2026-08-01T00:00:00+00:00", notification_uuid="renew-old"),
        "DID_RENEW",
    )

    assert users["u1"]["subscription"]["status"] == "expired"
    assert result["updated"] is False


def test_duplicate_notification_uuid_is_audit_only(tmp_path):
    users = {}
    events = []
    first = _snapshot(status="active", signed_date="2026-08-01T00:00:00+00:00", notification_uuid="same")
    duplicate = _snapshot(status="expired", signed_date="2026-08-01T00:00:00+00:00", notification_uuid="same")

    _send_notification(tmp_path, users, events, first, "DID_RENEW")
    result = _send_notification(tmp_path, users, events, duplicate, "REFUND")

    assert users["u1"]["subscription"]["status"] == "active"
    assert result["updated"] is False
    assert len(events) == 2


def test_forward_order_applies_latest_watermark_and_preserves_event_metadata(tmp_path):
    users = {}
    events = []

    _send_notification(
        tmp_path,
        users,
        events,
        _snapshot(status="active", signed_date="2026-08-01T00:00:00+00:00", notification_uuid="renew"),
        "DID_RENEW",
    )
    result = _send_notification(
        tmp_path,
        users,
        events,
        _snapshot(status="expired", signed_date="2026-08-02T00:00:00+00:00", notification_uuid="expired"),
        "EXPIRED",
    )

    assert users["u1"]["subscription"]["status"] == "expired"
    assert users["u1"]["subscription"]["last_signed_date"] == "2026-08-02T00:00:00+00:00"
    assert users["u1"]["subscription"]["last_notification_uuid"] == "expired"
    assert result["updated"] is True
    assert [event["notification_uuid"] for event in events] == ["renew", "expired"]
    assert [event["signed_date"] for event in events] == [
        "2026-08-01T00:00:00+00:00",
        "2026-08-02T00:00:00+00:00",
    ]


def test_signed_envelope_metadata_survives_decode():
    signed_date = int(datetime(2026, 8, 1, tzinfo=UTC).timestamp() * 1000)
    payloads = {
        "notification": {
            "notificationType": "DID_RENEW",
            "signedDate": signed_date,
            "notificationUUID": "notification-1",
            "data": {"signedTransactionInfo": "transaction"},
        },
        "transaction": {
            "productId": "pro_monthly",
            "transactionId": "txn-1",
            "originalTransactionId": "orig-1",
            "environment": "Production",
            "expiresDate": 2_000_000_000_000,
        },
    }

    snapshot, envelope = decode_notification_payload(
        AppStoreNotificationRequest(signed_payload="notification"),
        bundle_id="com.example.app",
        allow_unsigned_notifications=False,
        parse_datetime_fn=parse_datetime,
        verify_signed_jws=lambda token, *, bundle_id: SimpleNamespace(payload=payloads[token]),
    )

    assert envelope == payloads["notification"]
    assert snapshot["signed_date"] == "2026-08-01T00:00:00+00:00"
    assert snapshot["notification_uuid"] == "notification-1"


def test_unsigned_snapshot_cannot_override_signed_watermark(tmp_path):
    users = {}
    events = []
    _send_notification(
        tmp_path,
        users,
        events,
        _snapshot(status="expired", signed_date="2026-08-02T00:00:00+00:00", notification_uuid="expired"),
        "EXPIRED",
    )
    unsigned = {
        **_snapshot(status="active", signed_date="2026-08-01T00:00:00+00:00", notification_uuid="unsigned"),
        "signed_date": None,
        "notification_uuid": None,
    }
    result = _send_notification(tmp_path, users, events, unsigned, "DID_RENEW")

    assert users["u1"]["subscription"]["status"] == "expired"
    assert result["updated"] is False


def test_same_signed_date_uses_deterministic_uuid_tie_break(tmp_path):
    users = {}
    events = []
    _send_notification(
        tmp_path,
        users,
        events,
        _snapshot(status="active", signed_date="2026-08-01T00:00:00+00:00", notification_uuid="b"),
        "DID_RENEW",
    )
    result = _send_notification(
        tmp_path,
        users,
        events,
        _snapshot(status="active", signed_date="2026-08-01T00:00:00+00:00", notification_uuid="a"),
        "DID_RENEW",
    )

    assert users["u1"]["subscription"]["last_notification_uuid"] == "b"
    assert result["updated"] is False
