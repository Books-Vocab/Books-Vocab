"""Subscription / admin-grant default payloads and entitlement record readers."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from ..api_models import EntitlementsResponse, SubscriptionStatusResponse
from ..types import AdminGrantRecord, StoredUserRecord, SubscriptionRecord
from ..user_store import parse_datetime

# Subscription statuses that still confer an entitlement (drive is_active /
# default will_renew). Single source of truth shared by snapshots/notifications.
ACTIVE_BEARING_STATUSES = frozenset({"active", "trial", "grace_period"})


def _allow_sandbox_purchase() -> bool:
    """Whether non-production App Store transactions may grant a real entitlement.

    Defaults OFF. Only set ``KG_ALLOW_SANDBOX_PURCHASE`` truthy in dev/test
    deployments where sandbox / Xcode subscriptions should be honoured.
    """
    return os.getenv("KG_ALLOW_SANDBOX_PURCHASE", "").strip().lower() in {"1", "true", "yes"}


def subscription_environment_is_trusted(subscription: SubscriptionRecord | None) -> bool:
    """A subscription snapshot is entitlement-bearing only when production.

    The ``environment`` field is sourced from the *verified* App Store JWS
    transaction payload (see ``billing.notifications.verified_transaction_snapshot``),
    not from any client-supplied request field. Sandbox / Xcode transactions are
    free and signed by Apple's non-production CA, so honouring them would let a
    client redeem a free transaction for real Pro access.

    Legacy snapshots written before the ``environment`` column existed have no
    field and are treated as production (App Store reconcile/notification flows
    only ever produced production data on the live deployment).
    """
    if _allow_sandbox_purchase():
        return True
    env = (subscription or {}).get("environment")
    if env is None:
        return True
    return str(env).strip().lower() == "production"


def default_subscription_payload() -> SubscriptionRecord:
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


def default_admin_grant_payload() -> AdminGrantRecord:
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


def current_admin_grant_record(user_record: StoredUserRecord | None) -> AdminGrantRecord:
    record = user_record if isinstance(user_record, dict) else {}
    raw_admin_grant = record.get("admin_grant")
    admin_grant = default_admin_grant_payload()
    if isinstance(raw_admin_grant, dict):
        admin_grant.update(raw_admin_grant)
    return admin_grant


def admin_grant_is_active(user_record: StoredUserRecord | None) -> bool:
    admin_grant = current_admin_grant_record(user_record)
    if not admin_grant.get("is_active"):
        return False
    expires_at = parse_datetime(admin_grant.get("expires_at"))
    if expires_at and expires_at <= datetime.now(tz=UTC):
        return False
    return True


def subscription_is_active(subscription: SubscriptionRecord) -> bool:
    """Resolve whether a stored subscription still grants Pro right now.

    The stored ``is_active`` flag is a static snapshot computed at sync time
    from ``status``. If the Apple EXPIRED notification never arrives it stays
    ``True`` forever, so we re-check ``expires_at`` here — mirroring
    ``admin_grant_is_active``. ``grace_period`` legitimately carries a past
    ``expires_at`` (Apple's billing-retry window) and must remain entitled.
    """
    if not subscription.get("is_active"):
        return False
    if subscription.get("status") == "grace_period":
        return True
    expires_at = parse_datetime(subscription.get("expires_at"))
    if expires_at and expires_at <= datetime.now(tz=UTC):
        return False
    return True


def current_subscription_record(user_record: StoredUserRecord | None) -> SubscriptionRecord:
    record = user_record if isinstance(user_record, dict) else {}
    raw_subscription = record.get("subscription")
    subscription = default_subscription_payload()
    if isinstance(raw_subscription, dict):
        subscription.update(raw_subscription)
    if subscription.get("is_active") and not subscription_is_active(subscription):
        subscription["is_active"] = False
        subscription["status"] = "expired"
    return subscription


def current_pro_entitlement_record(user_record: StoredUserRecord | None) -> SubscriptionRecord:
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
    subscription = current_subscription_record(user_record)
    if not subscription_environment_is_trusted(subscription):
        # Sandbox / Xcode App Store transaction: keep the raw snapshot fields for
        # diagnostics but never expose an active Pro entitlement.
        return {
            **subscription,
            "is_active": False,
            "status": "inactive",
        }
    return subscription


def build_entitlements_response(user_record: StoredUserRecord | None) -> EntitlementsResponse:
    return EntitlementsResponse(pro=SubscriptionStatusResponse(**current_pro_entitlement_record(user_record)))
