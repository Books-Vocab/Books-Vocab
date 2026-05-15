from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SubscriptionStatusResponse(BaseModel):
    is_active: bool
    product_id: str | None = None
    plan_name: str | None = None
    price_display: str | None = None
    status: str
    is_trial: bool = False
    trial_days: int | None = None
    will_renew: bool = False
    expires_at: str | None = None
    source: str = "app_store"
    last_synced_at: str | None = None


class EntitlementsResponse(BaseModel):
    pro: SubscriptionStatusResponse


class AdminGrantStatusResponse(BaseModel):
    is_active: bool
    status: str
    plan_name: str | None = None
    source: str = "admin"
    expires_at: str | None = None
    granted_at: str | None = None
    granted_by: str | None = None
    reason: str | None = None
    last_synced_at: str | None = None


class AdminGrantRequest(BaseModel):
    reason: str | None = None
    expires_at: str | None = None
    granted_by: str | None = None


class AdminUserEntitlementResponse(BaseModel):
    user_id: str
    pro: SubscriptionStatusResponse
    admin_grant: AdminGrantStatusResponse


class AppStoreSyncRequest(BaseModel):
    product_id: str
    transaction_id: str | None = None
    original_transaction_id: str | None = None
    environment: str = "sandbox"
    status: str = "active"
    is_trial: bool = False
    expires_at: str | None = None
    will_renew: bool = True
    price_display: str | None = None
    signed_transaction_info: str | None = None


class AppStoreNotificationRequest(BaseModel):
    notification_type: str | None = None
    subtype: str | None = None
    product_id: str | None = None
    transaction_id: str | None = None
    original_transaction_id: str | None = None
    environment: str = "production"
    status: str | None = None
    is_trial: bool = False
    expires_at: str | None = None
    will_renew: bool | None = None
    signed_payload: str | None = None
    raw_payload: dict[str, Any] | None = None


class AppStoreReconcileRequest(BaseModel):
    transaction_id: str
    environment: str = "production"


class AppStoreNotificationResponse(BaseModel):
    status: str
    updated: bool
    reason: str | None = None
    user_id: str | None = None
    entitlements: dict[str, Any] | None = None


class QuotaResponse(BaseModel):
    fraction: float
    reset_seconds: int
