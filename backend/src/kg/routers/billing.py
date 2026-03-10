from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter

from ..api_models import EntitlementsResponse


def build_billing_router(
    *,
    sync_app_store_subscription: Callable[..., Any],
    app_store_notifications: Callable[..., Any],
    reconcile_app_store_subscription: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()
    router.post("/api/billing/app-store/sync", response_model=EntitlementsResponse)(sync_app_store_subscription)
    router.post("/api/billing/app-store/notifications")(app_store_notifications)
    router.post("/api/billing/app-store/reconcile", response_model=EntitlementsResponse)(reconcile_app_store_subscription)
    return router
