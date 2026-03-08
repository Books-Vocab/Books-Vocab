from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter

from ..api_models import DeleteAccountResponse, EntitlementsResponse, HealthResponse, UserConfigResponse


def build_user_router(
    *,
    get_user_config: Callable[..., Any],
    get_user_entitlements: Callable[..., Any],
    update_user_config: Callable[..., Any],
    delete_user_account: Callable[..., Any],
    health: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()
    router.get("/api/user/config", response_model=UserConfigResponse)(get_user_config)
    router.get("/api/user/entitlements", response_model=EntitlementsResponse)(get_user_entitlements)
    router.put("/api/user/config", response_model=UserConfigResponse)(update_user_config)
    router.delete("/api/user/account", response_model=DeleteAccountResponse)(delete_user_account)
    router.get("/api/health", response_model=HealthResponse)(health)
    return router
