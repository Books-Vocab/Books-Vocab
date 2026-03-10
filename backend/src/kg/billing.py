from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from .api_models import AppStoreNotificationRequest, EntitlementsResponse, SubscriptionStatusResponse
from .user_store import parse_datetime


def default_subscription_payload() -> dict[str, Any]:
    return {
        "is_active": False,
        "product_id": None,
        "plan_name": "BooksBrowser Pro",
        "price_display": None,
        "status": "inactive",
        "is_trial": False,
        "trial_days": 7,
        "will_renew": False,
        "expires_at": None,
        "source": "app_store",
        "last_synced_at": None,
    }


def default_admin_grant_payload() -> dict[str, Any]:
    return {
        "is_active": False,
        "plan_name": "BooksBrowser Pro",
        "status": "inactive",
        "source": "admin",
        "expires_at": None,
        "granted_at": None,
        "granted_by": None,
        "reason": None,
        "last_synced_at": None,
    }



def current_admin_grant_record(user_record: dict[str, Any] | None) -> dict[str, Any]:
    record = user_record if isinstance(user_record, dict) else {}
    raw_admin_grant = record.get("admin_grant")
    admin_grant = default_admin_grant_payload()
    if isinstance(raw_admin_grant, dict):
        admin_grant.update(raw_admin_grant)
    return admin_grant


def admin_grant_is_active(user_record: dict[str, Any] | None) -> bool:
    admin_grant = current_admin_grant_record(user_record)
    if not admin_grant.get("is_active"):
        return False
    expires_at = parse_datetime(admin_grant.get("expires_at"))
    if expires_at and expires_at <= datetime.now(tz=timezone.utc):
        return False
    return True


def current_pro_entitlement_record(user_record: dict[str, Any] | None) -> dict[str, Any]:
    if admin_grant_is_active(user_record):
        admin_grant = current_admin_grant_record(user_record)
        return {
            "is_active": True,
            "product_id": None,
            "plan_name": admin_grant.get("plan_name") or "BooksBrowser Pro",
            "price_display": None,
            "status": "active",
            "is_trial": False,
            "trial_days": None,
            "will_renew": False,
            "expires_at": admin_grant.get("expires_at"),
            "source": "admin",
            "last_synced_at": admin_grant.get("last_synced_at") or admin_grant.get("granted_at"),
        }
    return current_subscription_record(user_record)


def build_entitlements_response(user_record: dict[str, Any] | None) -> EntitlementsResponse:
    return EntitlementsResponse(pro=SubscriptionStatusResponse(**current_pro_entitlement_record(user_record)))


def current_subscription_record(user_record: dict[str, Any] | None) -> dict[str, Any]:
    record = user_record if isinstance(user_record, dict) else {}
    raw_subscription = record.get("subscription")
    subscription = default_subscription_payload()
    if isinstance(raw_subscription, dict):
        subscription.update(raw_subscription)
    return subscription


def require_pro_access(user: dict[str, Any], capability: str) -> None:
    entitlement = current_pro_entitlement_record(user.get("record"))
    if entitlement.get("is_active"):
        return
    raise HTTPException(
        status_code=402,
        detail={
            "code": "pro_required",
            "capability": capability,
            "message": "BooksBrowser Pro subscription required.",
        },
    )


def append_app_store_event(notifications_file: Path, payload: dict[str, Any]) -> None:
    notifications_file.parent.mkdir(parents=True, exist_ok=True)
    with notifications_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def upsert_subscription_index(
    users: dict[str, Any],
    user_id: str,
    original_transaction_id: str | None,
    transaction_id: str | None,
) -> None:
    index = users.get("_subscription_index")
    if not isinstance(index, dict):
        index = {}
        users["_subscription_index"] = index

    if isinstance(original_transaction_id, str) and original_transaction_id.strip():
        index[original_transaction_id.strip()] = user_id
    if isinstance(transaction_id, str) and transaction_id.strip():
        index[transaction_id.strip()] = user_id


def resolve_user_id_from_subscription_index(
    users: dict[str, Any],
    original_transaction_id: str | None,
    transaction_id: str | None,
) -> str | None:
    index = users.get("_subscription_index")
    if not isinstance(index, dict):
        return None
    for candidate in (original_transaction_id, transaction_id):
        if isinstance(candidate, str) and candidate.strip():
            resolved = index.get(candidate.strip())
            if isinstance(resolved, str) and resolved:
                return resolved
    return None


def write_subscription_snapshot(
    users: dict[str, Any],
    user_id: str,
    *,
    product_id: str,
    status: str,
    is_trial: bool,
    expires_at: str | None,
    will_renew: bool,
    environment: str,
    transaction_id: str | None,
    original_transaction_id: str | None,
    price_display: str | None,
    source: str,
) -> dict[str, Any]:
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    record = users.setdefault(user_id, {})
    subscription = default_subscription_payload()
    existing = record.get("subscription")
    if isinstance(existing, dict):
        subscription.update(existing)

    normalized_status = status.strip() or "active"
    subscription.update(
        {
            "is_active": normalized_status in {"active", "trial", "grace_period"},
            "product_id": product_id.strip(),
            "plan_name": "BooksBrowser Pro",
            "price_display": price_display.strip() if isinstance(price_display, str) and price_display.strip() else subscription.get("price_display"),
            "status": normalized_status,
            "is_trial": is_trial,
            "trial_days": subscription.get("trial_days") or 7,
            "will_renew": will_renew,
            "expires_at": expires_at,
            "source": source,
            "last_synced_at": now_iso,
            "transaction_id": transaction_id,
            "original_transaction_id": original_transaction_id,
            "environment": environment,
        }
    )
    record["subscription"] = subscription
    upsert_subscription_index(users, user_id, original_transaction_id, transaction_id)
    return record


def notification_status(notification_type: str | None, subtype: str | None) -> str:
    kind = (notification_type or "").upper()
    sub = (subtype or "").upper()
    if kind in {"SUBSCRIBED", "OFFER_REDEEMED", "DID_RENEW"}:
        return "trial" if sub == "INITIAL_BUY" else "active"
    if kind == "GRACE_PERIOD_EXPIRED":
        return "expired"
    if kind == "DID_FAIL_TO_RENEW":
        return "grace_period"
    if kind in {"EXPIRED", "REVOKE"}:
        return "expired"
    return "active"


def normalize_ms_timestamp(raw: Any, parse_datetime_fn: Callable[[Any], datetime | None]) -> str | None:
    if raw is None:
        return None
    try:
        timestamp_ms = int(raw)
    except (TypeError, ValueError):
        parsed = parse_datetime_fn(raw)
        return parsed.isoformat() if parsed else None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def bool_from_any(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    return default


def status_from_transaction_payload(
    payload: dict[str, Any],
    parse_datetime_fn: Callable[[Any], datetime | None],
    renewal_payload: dict[str, Any] | None = None,
) -> str:
    if payload.get("revocationDate"):
        return "expired"
    expires_at = parse_datetime_fn(normalize_ms_timestamp(payload.get("expiresDate"), parse_datetime_fn))
    if expires_at and expires_at <= datetime.now(tz=timezone.utc):
        return "expired"
    grace = renewal_payload.get("gracePeriodExpiresDate") if isinstance(renewal_payload, dict) else None
    if grace:
        grace_dt = parse_datetime_fn(normalize_ms_timestamp(grace, parse_datetime_fn))
        if grace_dt and grace_dt > datetime.now(tz=timezone.utc):
            return "grace_period"
    offer_type = payload.get("offerType")
    offer_discount_type = str(payload.get("offerDiscountType") or "").upper()
    if offer_type == 1 or offer_discount_type == "FREE_TRIAL":
        return "trial"
    return "active"


def verified_transaction_snapshot(
    payload: dict[str, Any],
    *,
    parse_datetime_fn: Callable[[Any], datetime | None],
    renewal_payload: dict[str, Any] | None = None,
    price_display: str | None = None,
) -> dict[str, Any]:
    product_id = payload.get("productId")
    if not isinstance(product_id, str) or not product_id.strip():
        raise HTTPException(status_code=400, detail="Verified App Store transaction is missing productId")

    environment = str(payload.get("environment") or "production").lower()
    transaction_id = payload.get("transactionId")
    original_transaction_id = payload.get("originalTransactionId")
    status = status_from_transaction_payload(payload, parse_datetime_fn, renewal_payload)
    auto_renew_status = None
    if isinstance(renewal_payload, dict):
        auto_renew_status = renewal_payload.get("autoRenewStatus")

    return {
        "product_id": product_id.strip(),
        "transaction_id": str(transaction_id) if transaction_id is not None else None,
        "original_transaction_id": str(original_transaction_id) if original_transaction_id is not None else None,
        "environment": environment,
        "status": status,
        "is_trial": status == "trial",
        "expires_at": normalize_ms_timestamp(payload.get("expiresDate"), parse_datetime_fn),
        "will_renew": bool_from_any(auto_renew_status, default=status in {"active", "trial", "grace_period"}),
        "price_display": price_display,
    }


def decode_signed_transaction_info(
    signed_transaction_info: str,
    *,
    bundle_id: str,
    parse_datetime_fn: Callable[[Any], datetime | None],
    verify_signed_jws: Callable[..., Any],
) -> dict[str, Any]:
    verified = verify_signed_jws(signed_transaction_info, bundle_id=bundle_id)
    return verified_transaction_snapshot(verified.payload, parse_datetime_fn=parse_datetime_fn)


def decode_notification_payload(
    req: AppStoreNotificationRequest,
    *,
    bundle_id: str,
    allow_unsigned_notifications: bool,
    parse_datetime_fn: Callable[[Any], datetime | None],
    verify_signed_jws: Callable[..., Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not req.signed_payload:
        if allow_unsigned_notifications:
            return (
                {
                    "product_id": req.product_id,
                    "transaction_id": req.transaction_id,
                    "original_transaction_id": req.original_transaction_id,
                    "environment": req.environment,
                    "status": req.status or notification_status(req.notification_type, req.subtype),
                    "is_trial": req.is_trial,
                    "expires_at": req.expires_at,
                    "will_renew": req.will_renew if req.will_renew is not None else True,
                    "price_display": None,
                },
                req.raw_payload,
            )
        raise HTTPException(status_code=400, detail="signed_payload is required for App Store notifications")

    verified_notification = verify_signed_jws(req.signed_payload, bundle_id=bundle_id)
    notification_payload = verified_notification.payload
    data = notification_payload.get("data", {})
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="App Store notification data payload is malformed")

    signed_transaction_info = data.get("signedTransactionInfo")
    signed_renewal_info = data.get("signedRenewalInfo")
    if not isinstance(signed_transaction_info, str) or not signed_transaction_info:
        raise HTTPException(status_code=400, detail="App Store notification missing signedTransactionInfo")

    transaction_verified = verify_signed_jws(signed_transaction_info, bundle_id=bundle_id)
    renewal_payload = None
    if isinstance(signed_renewal_info, str) and signed_renewal_info:
        renewal_payload = verify_signed_jws(signed_renewal_info, bundle_id=bundle_id).payload

    snapshot = verified_transaction_snapshot(
        transaction_verified.payload,
        parse_datetime_fn=parse_datetime_fn,
        renewal_payload=renewal_payload,
    )
    return snapshot, notification_payload
