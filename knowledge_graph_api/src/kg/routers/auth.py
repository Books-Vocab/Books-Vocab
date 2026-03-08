from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter

from ..api_models import AuthVerifyResponse


def build_auth_router(
    *,
    auth_verify: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()
    router.post("/auth/verify", response_model=AuthVerifyResponse)(auth_verify)
    return router
