"""Subscription / admin-grant default payloads and entitlement record readers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..api_models import EntitlementsResponse, SubscriptionStatusResponse
from ..user_store import parse_datetime


def default_subscription_payload() -> dict[str, Any]:
    return {
        "is_active": False,
        "product_id": None,
        "plan_name": "Books & Vocab Pro",
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
        "plan_name": "Books & Vocab Pro",
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
    if expires_at and expires_at <= datetime.now(tz=UTC):
        return False
    return True


def current_subscription_record(user_record: dict[str, Any] | None) -> dict[str, Any]:
    record = user_record if isinstance(user_record, dict) else {}
    raw_subscription = record.get("subscription")
    subscription = default_subscription_payload()
    if isinstance(raw_subscription, dict):
        subscription.update(raw_subscription)
    return subscription


def current_pro_entitlement_record(user_record: dict[str, Any] | None) -> dict[str, Any]:
    if admin_grant_is_active(user_record):
        admin_grant = current_admin_grant_record(user_record)
        return {
            "is_active": True,
            "product_id": None,
            "plan_name": admin_grant.get("plan_name") or "Books & Vocab Pro",
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
