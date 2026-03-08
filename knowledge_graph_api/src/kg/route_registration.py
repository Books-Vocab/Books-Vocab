from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse


def register_routes(
    app: FastAPI,
    *,
    get_privacy_policy: Callable[..., Any],
    get_support: Callable[..., Any],
) -> None:
    app.get("/privacy.html", response_class=FileResponse)(get_privacy_policy)
    app.get("/support.html", response_class=FileResponse)(get_support)
