from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse


def build_static_pages_router(
    *,
    get_privacy_policy: Callable[..., Any],
    get_support: Callable[..., Any],
    get_terms: Callable[..., Any],
    get_guide: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()
    router.get("/privacy.html", response_class=FileResponse)(get_privacy_policy)
    router.get("/support.html", response_class=FileResponse)(get_support)
    router.get("/terms.html", response_class=FileResponse)(get_terms)
    router.get("/guide.html", response_class=FileResponse)(get_guide)
    return router
