from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI

from .routers.static_pages import build_static_pages_router


def register_routes(
    app: FastAPI,
    *,
    get_privacy_policy: Callable[..., Any],
    get_support: Callable[..., Any],
) -> None:
    app.include_router(
        build_static_pages_router(
            get_privacy_policy=get_privacy_policy,
            get_support=get_support,
        )
    )
