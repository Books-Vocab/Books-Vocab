"""Billing package — App Store subscriptions, admin grants and entitlements.

Re-exports every public name so existing callers (`from kg.billing import ...`)
remain unchanged after the package split.
"""

from __future__ import annotations

from .index import resolve_user_id_from_subscription_index, upsert_subscription_index
from .notifications import (
    bool_from_any,
    decode_notification_payload,
    decode_signed_transaction_info,
    normalize_ms_timestamp,
    notification_status,
    status_from_transaction_payload,
    verified_transaction_snapshot,
)
from .payloads import (
    admin_grant_is_active,
    build_entitlements_response,
    current_admin_grant_record,
    current_pro_entitlement_record,
    current_subscription_record,
    default_admin_grant_payload,
    default_subscription_payload,
)
from .snapshots import append_app_store_event, write_subscription_snapshot

__all__ = [
    "admin_grant_is_active",
    "append_app_store_event",
    "bool_from_any",
    "build_entitlements_response",
    "current_admin_grant_record",
    "current_pro_entitlement_record",
    "current_subscription_record",
    "decode_notification_payload",
    "decode_signed_transaction_info",
    "default_admin_grant_payload",
    "default_subscription_payload",
    "normalize_ms_timestamp",
    "notification_status",
    "resolve_user_id_from_subscription_index",
    "status_from_transaction_payload",
    "upsert_subscription_index",
    "verified_transaction_snapshot",
    "write_subscription_snapshot",
]
