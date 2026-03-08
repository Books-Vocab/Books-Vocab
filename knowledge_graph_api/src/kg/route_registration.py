from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

from .api_models import (
    AuthVerifyResponse,
)


def register_routes(
    app: FastAPI,
    *,
    get_privacy_policy: Callable[..., Any],
    get_support: Callable[..., Any],
    auth_verify: Callable[..., Any],
    admin_ui: Callable[..., Any],
    admin_stats: Callable[..., Any],
    admin_logs: Callable[..., Any],
    admin_run_tests: Callable[..., Any],
    admin_last_test_run: Callable[..., Any],
    admin_test_catalog: Callable[..., Any],
    admin_tests_ui: Callable[..., Any],
) -> None:
    app.get("/privacy.html", response_class=FileResponse)(get_privacy_policy)
    app.get("/support.html", response_class=FileResponse)(get_support)
    app.post("/auth/verify", response_model=AuthVerifyResponse)(auth_verify)

    app.get("/admin", response_class=HTMLResponse, include_in_schema=False)(admin_ui)
    app.get("/api/admin/stats", include_in_schema=False)(admin_stats)
    app.get("/api/admin/logs", include_in_schema=False)(admin_logs)
    app.post("/api/admin/tests/run", include_in_schema=False)(admin_run_tests)
    app.get("/api/admin/tests/last", include_in_schema=False)(admin_last_test_run)
    app.get("/api/admin/tests/catalog", include_in_schema=False)(admin_test_catalog)
    app.get("/admin/tests", response_class=HTMLResponse, include_in_schema=False)(admin_tests_ui)
    app.get("/admin/test", response_class=HTMLResponse, include_in_schema=False)(admin_tests_ui)
