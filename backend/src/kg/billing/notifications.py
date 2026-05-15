"""App Store Server Notification / signed transaction decoding and status logic."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..api_models import AppStoreNotificationRequest
from ..exceptions import BadRequestError, ValidationError

_logger = logging.getLogger(__name__)


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
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat()


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
    if expires_at and expires_at <= datetime.now(tz=UTC):
        return "expired"
    grace = renewal_payload.get("gracePeriodExpiresDate") if isinstance(renewal_payload, dict) else None
    if grace:
        grace_dt = parse_datetime_fn(normalize_ms_timestamp(grace, parse_datetime_fn))
        if grace_dt and grace_dt > datetime.now(tz=UTC):
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
        raise ValidationError("Verified App Store transaction is missing productId")

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
            _logger.warning(
                "Accepting unsigned App Store notification (signature verification skipped)"
            )
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
        raise BadRequestError("signed_payload is required for App Store notifications")

    verified_notification = verify_signed_jws(req.signed_payload, bundle_id=bundle_id)
    notification_payload = verified_notification.payload
    data = notification_payload.get("data", {})
    if not isinstance(data, dict):
        raise BadRequestError("App Store notification data payload is malformed")

    signed_transaction_info = data.get("signedTransactionInfo")
    signed_renewal_info = data.get("signedRenewalInfo")
    if not isinstance(signed_transaction_info, str) or not signed_transaction_info:
        raise BadRequestError("App Store notification missing signedTransactionInfo")

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
