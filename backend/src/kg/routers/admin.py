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

def build_login_routes(
    *,
    runtime_settings_fn: Callable,
) -> APIRouter:
    """Create login routes with injected settings accessor."""
    router = APIRouter()

    @router.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
    async def admin_login_get(request: Request):
        from ..admin_handlers import admin_login_page
        settings = runtime_settings_fn()
        return admin_login_page(password_enabled=bool(settings.admin_password))

    @router.post("/admin/login", response_class=HTMLResponse, include_in_schema=False)
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

    return router


# ---------------------------------------------------------------------------
# HTML admin router — auth check inline, redirect to /admin/login on failure
# ---------------------------------------------------------------------------

def build_html_admin_router(
    *,
    admin_ui: Callable[..., Any],
    admin_tests_ui: Callable[..., Any],
    admin_user_detail_ui: Callable[..., Any] | None = None,
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

    if admin_user_detail_ui is not None:
        @router.get("/admin/user/{user_id}", response_class=HTMLResponse, include_in_schema=False)
        async def admin_user_detail_page(
            request: Request,
            user_id: str,
            token: str | None = Query(None),
            authorization: str | None = Header(None),
            admin_session: str | None = Cookie(None),
        ):
            if not _is_authed(request, token, authorization, admin_session):
                return RedirectResponse("/admin/login", status_code=302)
            return admin_user_detail_ui()

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
    admin_graph_density: Callable[..., Any] | None = None,
    admin_graph_playback: Callable[..., Any] | None = None,
    admin_pipeline_runs: Callable[..., Any] | None = None,
    admin_judge_stats: Callable[..., Any] | None = None,
    admin_translate_history: Callable[..., Any] | None = None,
    admin_user_activity: Callable[..., Any] | None = None,
    admin_user_usage: Callable[..., Any] | None = None,
    admin_host_metrics: Callable[..., Any] | None = None,
    admin_users_search: Callable[..., Any] | None = None,
    admin_observability: Callable[..., Any] | None = None,
    admin_log_retention_run: Callable[..., Any] | None = None,
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(get_admin_user)])
    router.get("/api/admin/stats", include_in_schema=False)(admin_stats)
    router.get("/api/admin/logs", include_in_schema=False)(admin_logs)
    # NOTE: static "/users/search" MUST register before dynamic "/users/{user_id}/…"
    # otherwise FastAPI greedy-matches "search" as user_id.
    if admin_users_search is not None:
        router.get("/api/admin/users/search", include_in_schema=False)(admin_users_search)
    router.get("/api/admin/users/{user_id}/entitlement", include_in_schema=False)(admin_user_entitlement)
    router.post("/api/admin/users/{user_id}/admin-grant", include_in_schema=False)(admin_grant_pro_access)
    router.delete("/api/admin/users/{user_id}/admin-grant", include_in_schema=False)(admin_revoke_pro_access)
    router.post("/api/admin/tests/run", include_in_schema=False)(admin_run_tests)
    router.get("/api/admin/tests/last", include_in_schema=False)(admin_last_test_run)
    router.get("/api/admin/tests/catalog", include_in_schema=False)(admin_test_catalog)
    if admin_graph_density is not None:
        router.get("/api/admin/graph-density", include_in_schema=False)(admin_graph_density)
    if admin_graph_playback is not None:
        router.get("/api/admin/graph-playback", include_in_schema=False)(admin_graph_playback)
    if admin_pipeline_runs is not None:
        router.get("/api/admin/pipeline-runs", include_in_schema=False)(admin_pipeline_runs)
    if admin_judge_stats is not None:
        router.get("/api/admin/judge-stats", include_in_schema=False)(admin_judge_stats)
    if admin_translate_history is not None:
        router.get("/api/admin/translate-history", include_in_schema=False)(admin_translate_history)
    if admin_user_activity is not None:
        router.get("/api/admin/user-activity", include_in_schema=False)(admin_user_activity)
    if admin_user_usage is not None:
        router.get("/api/admin/user-usage", include_in_schema=False)(admin_user_usage)
    if admin_host_metrics is not None:
        router.get("/api/admin/host-metrics", include_in_schema=False)(admin_host_metrics)
    if admin_observability is not None:
        router.get("/api/admin/observability", include_in_schema=False)(admin_observability)
    if admin_log_retention_run is not None:
        router.post("/api/admin/log-retention/run", include_in_schema=False)(admin_log_retention_run)
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
    admin_graph_density: Callable[..., Any] | None = None,
    admin_graph_playback: Callable[..., Any] | None = None,
    admin_pipeline_runs: Callable[..., Any] | None = None,
    admin_judge_stats: Callable[..., Any] | None = None,
    admin_translate_history: Callable[..., Any] | None = None,
    admin_user_activity: Callable[..., Any] | None = None,
    admin_user_usage: Callable[..., Any] | None = None,
    admin_host_metrics: Callable[..., Any] | None = None,
    admin_users_search: Callable[..., Any] | None = None,
    admin_observability: Callable[..., Any] | None = None,
    admin_log_retention_run: Callable[..., Any] | None = None,
    admin_user_detail_ui: Callable[..., Any] | None = None,
    runtime_settings_fn: Callable | None = None,
) -> tuple[APIRouter, APIRouter, APIRouter]:
    """Build all three admin routers. Returns (login_router, html_router, api_router)."""
    login = build_login_routes(runtime_settings_fn=runtime_settings_fn)
    html = build_html_admin_router(
        admin_ui=admin_ui,
        admin_tests_ui=admin_tests_ui,
        admin_user_detail_ui=admin_user_detail_ui,
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
        admin_graph_density=admin_graph_density,
        admin_graph_playback=admin_graph_playback,
        admin_pipeline_runs=admin_pipeline_runs,
        admin_judge_stats=admin_judge_stats,
        admin_translate_history=admin_translate_history,
        admin_user_activity=admin_user_activity,
        admin_user_usage=admin_user_usage,
        admin_host_metrics=admin_host_metrics,
        admin_users_search=admin_users_search,
        admin_observability=admin_observability,
        admin_log_retention_run=admin_log_retention_run,
    )
    return login, html, api
