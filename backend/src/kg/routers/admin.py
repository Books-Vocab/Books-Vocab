from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


def build_admin_router(
    *,
    admin_ui: Callable[..., Any],
    admin_stats: Callable[..., Any],
    admin_logs: Callable[..., Any],
    admin_user_entitlement: Callable[..., Any],
    admin_grant_pro_access: Callable[..., Any],
    admin_revoke_pro_access: Callable[..., Any],
    admin_run_tests: Callable[..., Any],
    admin_last_test_run: Callable[..., Any],
    admin_test_catalog: Callable[..., Any],
    admin_tests_ui: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()
    router.get("/admin", response_class=HTMLResponse, include_in_schema=False)(admin_ui)
    router.get("/api/admin/stats", include_in_schema=False)(admin_stats)
    router.get("/api/admin/logs", include_in_schema=False)(admin_logs)
    router.get("/api/admin/users/{user_id}/entitlement", include_in_schema=False)(admin_user_entitlement)
    router.post("/api/admin/users/{user_id}/admin-grant", include_in_schema=False)(admin_grant_pro_access)
    router.delete("/api/admin/users/{user_id}/admin-grant", include_in_schema=False)(admin_revoke_pro_access)
    router.post("/api/admin/tests/run", include_in_schema=False)(admin_run_tests)
    router.get("/api/admin/tests/last", include_in_schema=False)(admin_last_test_run)
    router.get("/api/admin/tests/catalog", include_in_schema=False)(admin_test_catalog)
    router.get("/admin/tests", response_class=HTMLResponse, include_in_schema=False)(admin_tests_ui)
    router.get("/admin/test", response_class=HTMLResponse, include_in_schema=False)(admin_tests_ui)
    return router
