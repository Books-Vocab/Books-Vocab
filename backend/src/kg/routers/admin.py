from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Cookie, Depends, Header, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..admin_handlers import check_admin_auth, ADMIN_COOKIE_NAME
from ..deps import get_admin_user


# ---------------------------------------------------------------------------
# Login router — no auth required
# ---------------------------------------------------------------------------

login_router = APIRouter()


def build_login_routes(
    *,
    runtime_settings_fn: Callable,
) -> APIRouter:
    """Create login routes with injected settings accessor."""

    @login_router.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
    async def admin_login_get(request: Request):
        from ..admin_handlers import admin_login_page
        settings = runtime_settings_fn()
        return admin_login_page(password_enabled=bool(settings.admin_password))

    @login_router.post("/admin/login", response_class=HTMLResponse, include_in_schema=False)
    async def admin_login_submit(request: Request):
        from ..admin_handlers import admin_login_post
        form = await request.form()
        password = form.get("password", "")
        settings = runtime_settings_fn()
        return admin_login_post(
            password,
            admin_password=settings.admin_password,
            admin_token=settings.admin_token,
        )

    return login_router


# ---------------------------------------------------------------------------
# HTML admin router — auth check inline, redirect to /admin/login on failure
# ---------------------------------------------------------------------------

def build_html_admin_router(
    *,
    admin_ui: Callable[..., Any],
    admin_tests_ui: Callable[..., Any],
    runtime_settings_fn: Callable,
) -> APIRouter:
    router = APIRouter()

    def _is_authed(request: Request, token, authorization, cookie_token) -> bool:
        admin_token = runtime_settings_fn().admin_token
        return check_admin_auth(
            token=token,
            authorization=authorization,
            cookie_token=cookie_token,
            admin_token=admin_token,
        )

    @router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    async def admin_ui_page(
        request: Request,
        token: str | None = Query(None),
        authorization: str | None = Header(None),
        admin_session: str | None = Cookie(None),
    ):
        if not _is_authed(request, token, authorization, admin_session):
            return RedirectResponse("/admin/login", status_code=302)
        return admin_ui()

    @router.get("/admin/tests", response_class=HTMLResponse, include_in_schema=False)
    async def admin_tests_page(
        request: Request,
        token: str | None = Query(None),
        authorization: str | None = Header(None),
        admin_session: str | None = Cookie(None),
    ):
        if not _is_authed(request, token, authorization, admin_session):
            return RedirectResponse("/admin/login", status_code=302)
        return admin_tests_ui()

    @router.get("/admin/test", response_class=HTMLResponse, include_in_schema=False)
    async def admin_test_page(
        request: Request,
        token: str | None = Query(None),
        authorization: str | None = Header(None),
        admin_session: str | None = Cookie(None),
    ):
        if not _is_authed(request, token, authorization, admin_session):
            return RedirectResponse("/admin/login", status_code=302)
        return admin_tests_ui()

    return router


# ---------------------------------------------------------------------------
# API admin router — 403 on auth failure (unchanged behavior)
# ---------------------------------------------------------------------------

def build_api_admin_router(
    *,
    admin_stats: Callable[..., Any],
    admin_logs: Callable[..., Any],
    admin_user_entitlement: Callable[..., Any],
    admin_grant_pro_access: Callable[..., Any],
    admin_revoke_pro_access: Callable[..., Any],
    admin_run_tests: Callable[..., Any],
    admin_last_test_run: Callable[..., Any],
    admin_test_catalog: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(get_admin_user)])
    router.get("/api/admin/stats", include_in_schema=False)(admin_stats)
    router.get("/api/admin/logs", include_in_schema=False)(admin_logs)
    router.get("/api/admin/users/{user_id}/entitlement", include_in_schema=False)(admin_user_entitlement)
    router.post("/api/admin/users/{user_id}/admin-grant", include_in_schema=False)(admin_grant_pro_access)
    router.delete("/api/admin/users/{user_id}/admin-grant", include_in_schema=False)(admin_revoke_pro_access)
    router.post("/api/admin/tests/run", include_in_schema=False)(admin_run_tests)
    router.get("/api/admin/tests/last", include_in_schema=False)(admin_last_test_run)
    router.get("/api/admin/tests/catalog", include_in_schema=False)(admin_test_catalog)
    return router


# ---------------------------------------------------------------------------
# Backward-compatible build_admin_router (still used by api.py)
# ---------------------------------------------------------------------------

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
    runtime_settings_fn: Callable | None = None,
) -> tuple[APIRouter, APIRouter, APIRouter]:
    """Build all three admin routers. Returns (login_router, html_router, api_router)."""
    login = build_login_routes(runtime_settings_fn=runtime_settings_fn)
    html = build_html_admin_router(
        admin_ui=admin_ui,
        admin_tests_ui=admin_tests_ui,
        runtime_settings_fn=runtime_settings_fn,
    )
    api = build_api_admin_router(
        admin_stats=admin_stats,
        admin_logs=admin_logs,
        admin_user_entitlement=admin_user_entitlement,
        admin_grant_pro_access=admin_grant_pro_access,
        admin_revoke_pro_access=admin_revoke_pro_access,
        admin_run_tests=admin_run_tests,
        admin_last_test_run=admin_last_test_run,
        admin_test_catalog=admin_test_catalog,
    )
    return login, html, api
