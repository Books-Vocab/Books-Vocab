from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Awaitable, Protocol

from fastapi import APIRouter, Cookie, Depends, Header, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..admin_handlers import check_admin_auth
from ..api_models import AdminUserEntitlementResponse
from ..deps import get_admin_user

AdminEndpointResult = dict[str, Any] | HTMLResponse | AdminUserEntitlementResponse
AdminEndpoint = Callable[..., AdminEndpointResult | Awaitable[AdminEndpointResult]]


class SupportsAdminSettings(Protocol):
    admin_token: str
    admin_password: str


RuntimeSettingsFn = Callable[[], SupportsAdminSettings]


@dataclass(frozen=True)
class AdminHtmlHandlers:
    admin_ui: AdminEndpoint
    admin_tests_ui: AdminEndpoint
    admin_user_detail_ui: AdminEndpoint | None = None


@dataclass(frozen=True)
class AdminApiHandlers:
    admin_stats: AdminEndpoint
    admin_logs: AdminEndpoint
    admin_user_entitlement: AdminEndpoint
    admin_grant_pro_access: AdminEndpoint
    admin_revoke_pro_access: AdminEndpoint
    admin_run_tests: AdminEndpoint
    admin_last_test_run: AdminEndpoint
    admin_test_catalog: AdminEndpoint
    admin_graph_density: AdminEndpoint | None = None
    admin_graph_playback: AdminEndpoint | None = None
    admin_pipeline_runs: AdminEndpoint | None = None
    admin_judge_stats: AdminEndpoint | None = None
    admin_translate_history: AdminEndpoint | None = None
    admin_user_activity: AdminEndpoint | None = None
    admin_user_usage: AdminEndpoint | None = None
    admin_user_cost_summary: AdminEndpoint | None = None
    admin_host_metrics: AdminEndpoint | None = None
    admin_users_search: AdminEndpoint | None = None
    admin_observability: AdminEndpoint | None = None
    admin_stats_trends: AdminEndpoint | None = None
    admin_log_retention_run: AdminEndpoint | None = None
    admin_audit: AdminEndpoint | None = None
    admin_orphans_scan: AdminEndpoint | None = None


@dataclass(frozen=True)
class AdminRouteHandlers:
    html: AdminHtmlHandlers
    api: AdminApiHandlers


class SupportsAdminRouteHandlers(Protocol):
    admin_ui: AdminEndpoint
    admin_tests_ui: AdminEndpoint
    admin_user_detail_ui: AdminEndpoint | None
    admin_stats: AdminEndpoint
    admin_logs: AdminEndpoint
    admin_user_entitlement: AdminEndpoint
    admin_grant_pro_access: AdminEndpoint
    admin_revoke_pro_access: AdminEndpoint
    admin_run_tests: AdminEndpoint
    admin_last_test_run: AdminEndpoint
    admin_test_catalog: AdminEndpoint
    admin_graph_density: AdminEndpoint | None
    admin_graph_playback: AdminEndpoint | None
    admin_pipeline_runs: AdminEndpoint | None
    admin_judge_stats: AdminEndpoint | None
    admin_translate_history: AdminEndpoint | None
    admin_user_activity: AdminEndpoint | None
    admin_user_usage: AdminEndpoint | None
    admin_user_cost_summary: AdminEndpoint | None
    admin_host_metrics: AdminEndpoint | None
    admin_users_search: AdminEndpoint | None
    admin_observability: AdminEndpoint | None
    admin_stats_trends: AdminEndpoint | None
    admin_log_retention_run: AdminEndpoint | None
    admin_audit: AdminEndpoint | None
    admin_orphans_scan: AdminEndpoint | None


def build_admin_route_handlers(handlers: SupportsAdminRouteHandlers) -> AdminRouteHandlers:
    return AdminRouteHandlers(
        html=AdminHtmlHandlers(
            admin_ui=handlers.admin_ui,
            admin_tests_ui=handlers.admin_tests_ui,
            admin_user_detail_ui=handlers.admin_user_detail_ui,
        ),
        api=AdminApiHandlers(
            admin_stats=handlers.admin_stats,
            admin_logs=handlers.admin_logs,
            admin_user_entitlement=handlers.admin_user_entitlement,
            admin_grant_pro_access=handlers.admin_grant_pro_access,
            admin_revoke_pro_access=handlers.admin_revoke_pro_access,
            admin_run_tests=handlers.admin_run_tests,
            admin_last_test_run=handlers.admin_last_test_run,
            admin_test_catalog=handlers.admin_test_catalog,
            admin_graph_density=handlers.admin_graph_density,
            admin_graph_playback=handlers.admin_graph_playback,
            admin_pipeline_runs=handlers.admin_pipeline_runs,
            admin_judge_stats=handlers.admin_judge_stats,
            admin_translate_history=handlers.admin_translate_history,
            admin_user_activity=handlers.admin_user_activity,
            admin_user_usage=handlers.admin_user_usage,
            admin_user_cost_summary=handlers.admin_user_cost_summary,
            admin_host_metrics=handlers.admin_host_metrics,
            admin_users_search=handlers.admin_users_search,
            admin_observability=handlers.admin_observability,
            admin_stats_trends=handlers.admin_stats_trends,
            admin_log_retention_run=handlers.admin_log_retention_run,
            admin_audit=handlers.admin_audit,
            admin_orphans_scan=handlers.admin_orphans_scan,
        ),
    )


@dataclass(frozen=True)
class _AdminApiRouteSpec:
    method: str
    path: str
    endpoint: AdminEndpoint | None
    response_model: object | None = None


@dataclass(frozen=True)
class AdminRouters:
    login: APIRouter
    html: APIRouter
    api: APIRouter


# ---------------------------------------------------------------------------
# Login router — no auth required
# ---------------------------------------------------------------------------

def build_login_routes(
    *,
    runtime_settings_fn: RuntimeSettingsFn,
) -> APIRouter:
    """Create login routes with injected settings accessor."""
    router = APIRouter()

    @router.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
    async def admin_login_get() -> HTMLResponse:
        from ..admin_handlers import admin_login_page

        settings = runtime_settings_fn()
        return admin_login_page(password_enabled=bool(settings.admin_password))

    @router.post("/admin/login", response_class=HTMLResponse, include_in_schema=False)
    async def admin_login_submit(request: Request) -> HTMLResponse | RedirectResponse:
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

def _build_html_admin_router_from_handlers(
    *,
    handlers: AdminHtmlHandlers,
    runtime_settings_fn: RuntimeSettingsFn,
) -> APIRouter:
    router = APIRouter()

    def _is_authed(
        token: str | None,
        authorization: str | None,
        cookie_token: str | None,
    ) -> bool:
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
        token: str | None = Query(None, max_length=256),
        authorization: str | None = Header(None),
        admin_session: str | None = Cookie(None),
    ) -> Response:
        if not _is_authed(token, authorization, admin_session):
            return RedirectResponse("/admin/login", status_code=302)
        return handlers.admin_ui()

    @router.get("/admin/tests", response_class=HTMLResponse, include_in_schema=False)
    async def admin_tests_page(
        request: Request,
        token: str | None = Query(None, max_length=256),
        authorization: str | None = Header(None),
        admin_session: str | None = Cookie(None),
    ) -> Response:
        if not _is_authed(token, authorization, admin_session):
            return RedirectResponse("/admin/login", status_code=302)
        return handlers.admin_tests_ui()

    @router.get("/admin/test", response_class=HTMLResponse, include_in_schema=False)
    async def admin_test_page(
        request: Request,
        token: str | None = Query(None, max_length=256),
        authorization: str | None = Header(None),
        admin_session: str | None = Cookie(None),
    ) -> Response:
        if not _is_authed(token, authorization, admin_session):
            return RedirectResponse("/admin/login", status_code=302)
        return handlers.admin_tests_ui()

    if handlers.admin_user_detail_ui is not None:

        @router.get("/admin/user/{user_id}", response_class=HTMLResponse, include_in_schema=False)
        async def admin_user_detail_page(
            request: Request,
            user_id: str,
            token: str | None = Query(None, max_length=256),
            authorization: str | None = Header(None),
            admin_session: str | None = Cookie(None),
        ) -> Response:
            if not _is_authed(token, authorization, admin_session):
                return RedirectResponse("/admin/login", status_code=302)
            return handlers.admin_user_detail_ui()

    return router


def build_html_admin_router(
    *,
    admin_ui: AdminEndpoint,
    admin_tests_ui: AdminEndpoint,
    admin_user_detail_ui: AdminEndpoint | None = None,
    runtime_settings_fn: RuntimeSettingsFn,
) -> APIRouter:
    return _build_html_admin_router_from_handlers(
        handlers=AdminHtmlHandlers(
            admin_ui=admin_ui,
            admin_tests_ui=admin_tests_ui,
            admin_user_detail_ui=admin_user_detail_ui,
        ),
        runtime_settings_fn=runtime_settings_fn,
    )


# ---------------------------------------------------------------------------
# API admin router — 403 on auth failure (unchanged behavior)
# ---------------------------------------------------------------------------

def _register_api_route(router: APIRouter, spec: _AdminApiRouteSpec) -> None:
    if spec.endpoint is None:
        return
    kwargs: dict[str, object] = {"include_in_schema": False}
    if spec.response_model is not None:
        kwargs["response_model"] = spec.response_model
    getattr(router, spec.method)(spec.path, **kwargs)(spec.endpoint)


def _build_api_admin_router_from_handlers(
    *,
    handlers: AdminApiHandlers,
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(get_admin_user)])
    specs = [
        _AdminApiRouteSpec("get", "/api/admin/stats", handlers.admin_stats),
        _AdminApiRouteSpec("get", "/api/admin/logs", handlers.admin_logs),
        # NOTE: static "/users/search" MUST register before dynamic
        # "/users/{user_id}/…" or FastAPI will greedy-match "search" as user_id.
        _AdminApiRouteSpec("get", "/api/admin/users/search", handlers.admin_users_search),
        _AdminApiRouteSpec(
            "get",
            "/api/admin/users/{user_id}/entitlement",
            handlers.admin_user_entitlement,
            response_model=AdminUserEntitlementResponse,
        ),
        _AdminApiRouteSpec(
            "post",
            "/api/admin/users/{user_id}/admin-grant",
            handlers.admin_grant_pro_access,
            response_model=AdminUserEntitlementResponse,
        ),
        _AdminApiRouteSpec(
            "delete",
            "/api/admin/users/{user_id}/admin-grant",
            handlers.admin_revoke_pro_access,
            response_model=AdminUserEntitlementResponse,
        ),
        _AdminApiRouteSpec("post", "/api/admin/tests/run", handlers.admin_run_tests),
        _AdminApiRouteSpec("get", "/api/admin/tests/last", handlers.admin_last_test_run),
        _AdminApiRouteSpec("get", "/api/admin/tests/catalog", handlers.admin_test_catalog),
        _AdminApiRouteSpec("get", "/api/admin/graph-density", handlers.admin_graph_density),
        _AdminApiRouteSpec("get", "/api/admin/graph-playback", handlers.admin_graph_playback),
        _AdminApiRouteSpec("get", "/api/admin/pipeline-runs", handlers.admin_pipeline_runs),
        _AdminApiRouteSpec("get", "/api/admin/judge-stats", handlers.admin_judge_stats),
        _AdminApiRouteSpec("get", "/api/admin/translate-history", handlers.admin_translate_history),
        _AdminApiRouteSpec("get", "/api/admin/user-activity", handlers.admin_user_activity),
        _AdminApiRouteSpec("get", "/api/admin/user-usage", handlers.admin_user_usage),
        _AdminApiRouteSpec("get", "/api/admin/user-cost-summary", handlers.admin_user_cost_summary),
        _AdminApiRouteSpec("get", "/api/admin/host-metrics", handlers.admin_host_metrics),
        _AdminApiRouteSpec("get", "/api/admin/observability", handlers.admin_observability),
        _AdminApiRouteSpec("get", "/api/admin/stats/trends", handlers.admin_stats_trends),
        _AdminApiRouteSpec("post", "/api/admin/log-retention/run", handlers.admin_log_retention_run),
        _AdminApiRouteSpec("get", "/api/admin/audit", handlers.admin_audit),
        _AdminApiRouteSpec("get", "/api/admin/orphans/scan", handlers.admin_orphans_scan),
    ]
    for spec in specs:
        _register_api_route(router, spec)
    return router


def build_api_admin_router(
    *,
    admin_stats: AdminEndpoint,
    admin_logs: AdminEndpoint,
    admin_user_entitlement: AdminEndpoint,
    admin_grant_pro_access: AdminEndpoint,
    admin_revoke_pro_access: AdminEndpoint,
    admin_run_tests: AdminEndpoint,
    admin_last_test_run: AdminEndpoint,
    admin_test_catalog: AdminEndpoint,
    admin_graph_density: AdminEndpoint | None = None,
    admin_graph_playback: AdminEndpoint | None = None,
    admin_pipeline_runs: AdminEndpoint | None = None,
    admin_judge_stats: AdminEndpoint | None = None,
    admin_translate_history: AdminEndpoint | None = None,
    admin_user_activity: AdminEndpoint | None = None,
    admin_user_usage: AdminEndpoint | None = None,
    admin_user_cost_summary: AdminEndpoint | None = None,
    admin_host_metrics: AdminEndpoint | None = None,
    admin_users_search: AdminEndpoint | None = None,
    admin_observability: AdminEndpoint | None = None,
    admin_stats_trends: AdminEndpoint | None = None,
    admin_log_retention_run: AdminEndpoint | None = None,
    admin_audit: AdminEndpoint | None = None,
    admin_orphans_scan: AdminEndpoint | None = None,
) -> APIRouter:
    return _build_api_admin_router_from_handlers(
        handlers=AdminApiHandlers(
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
            admin_user_cost_summary=admin_user_cost_summary,
            admin_host_metrics=admin_host_metrics,
            admin_users_search=admin_users_search,
            admin_observability=admin_observability,
            admin_stats_trends=admin_stats_trends,
            admin_log_retention_run=admin_log_retention_run,
            admin_audit=admin_audit,
            admin_orphans_scan=admin_orphans_scan,
        ),
    )


def build_admin_routers_from_handlers(
    *,
    handlers: AdminRouteHandlers,
    runtime_settings_fn: RuntimeSettingsFn,
) -> AdminRouters:
    """Build admin routers from the named router-layer handler contract."""
    login = build_login_routes(runtime_settings_fn=runtime_settings_fn)
    html = _build_html_admin_router_from_handlers(
        handlers=handlers.html,
        runtime_settings_fn=runtime_settings_fn,
    )
    api = _build_api_admin_router_from_handlers(handlers=handlers.api)
    return AdminRouters(login=login, html=html, api=api)


# ---------------------------------------------------------------------------
# Router composition
# ---------------------------------------------------------------------------

def build_admin_routers(
    *,
    admin_ui: AdminEndpoint,
    admin_stats: AdminEndpoint,
    admin_logs: AdminEndpoint,
    admin_user_entitlement: AdminEndpoint,
    admin_grant_pro_access: AdminEndpoint,
    admin_revoke_pro_access: AdminEndpoint,
    admin_run_tests: AdminEndpoint,
    admin_last_test_run: AdminEndpoint,
    admin_test_catalog: AdminEndpoint,
    admin_tests_ui: AdminEndpoint,
    admin_graph_density: AdminEndpoint | None = None,
    admin_graph_playback: AdminEndpoint | None = None,
    admin_pipeline_runs: AdminEndpoint | None = None,
    admin_judge_stats: AdminEndpoint | None = None,
    admin_translate_history: AdminEndpoint | None = None,
    admin_user_activity: AdminEndpoint | None = None,
    admin_user_usage: AdminEndpoint | None = None,
    admin_user_cost_summary: AdminEndpoint | None = None,
    admin_host_metrics: AdminEndpoint | None = None,
    admin_users_search: AdminEndpoint | None = None,
    admin_observability: AdminEndpoint | None = None,
    admin_stats_trends: AdminEndpoint | None = None,
    admin_log_retention_run: AdminEndpoint | None = None,
    admin_audit: AdminEndpoint | None = None,
    admin_orphans_scan: AdminEndpoint | None = None,
    admin_user_detail_ui: AdminEndpoint | None = None,
    runtime_settings_fn: RuntimeSettingsFn,
) -> AdminRouters:
    """Backward-compatible builder around the named router-layer handler contract."""
    return build_admin_routers_from_handlers(
        handlers=AdminRouteHandlers(
            html=AdminHtmlHandlers(
                admin_ui=admin_ui,
                admin_tests_ui=admin_tests_ui,
                admin_user_detail_ui=admin_user_detail_ui,
            ),
            api=AdminApiHandlers(
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
                admin_user_cost_summary=admin_user_cost_summary,
                admin_host_metrics=admin_host_metrics,
                admin_users_search=admin_users_search,
                admin_observability=admin_observability,
                admin_stats_trends=admin_stats_trends,
                admin_log_retention_run=admin_log_retention_run,
                admin_audit=admin_audit,
                admin_orphans_scan=admin_orphans_scan,
            ),
        ),
        runtime_settings_fn=runtime_settings_fn,
    )


# ---------------------------------------------------------------------------
# Backward-compatible tuple builder
# ---------------------------------------------------------------------------

def build_admin_router(
    *,
    admin_ui: AdminEndpoint,
    admin_stats: AdminEndpoint,
    admin_logs: AdminEndpoint,
    admin_user_entitlement: AdminEndpoint,
    admin_grant_pro_access: AdminEndpoint,
    admin_revoke_pro_access: AdminEndpoint,
    admin_run_tests: AdminEndpoint,
    admin_last_test_run: AdminEndpoint,
    admin_test_catalog: AdminEndpoint,
    admin_tests_ui: AdminEndpoint,
    admin_graph_density: AdminEndpoint | None = None,
    admin_graph_playback: AdminEndpoint | None = None,
    admin_pipeline_runs: AdminEndpoint | None = None,
    admin_judge_stats: AdminEndpoint | None = None,
    admin_translate_history: AdminEndpoint | None = None,
    admin_user_activity: AdminEndpoint | None = None,
    admin_user_usage: AdminEndpoint | None = None,
    admin_user_cost_summary: AdminEndpoint | None = None,
    admin_host_metrics: AdminEndpoint | None = None,
    admin_users_search: AdminEndpoint | None = None,
    admin_observability: AdminEndpoint | None = None,
    admin_stats_trends: AdminEndpoint | None = None,
    admin_log_retention_run: AdminEndpoint | None = None,
    admin_audit: AdminEndpoint | None = None,
    admin_orphans_scan: AdminEndpoint | None = None,
    admin_user_detail_ui: AdminEndpoint | None = None,
    runtime_settings_fn: RuntimeSettingsFn,
) -> tuple[APIRouter, APIRouter, APIRouter]:
    """Backward-compatible wrapper around :func:`build_admin_routers`."""
    routers = build_admin_routers(
        admin_ui=admin_ui,
        admin_stats=admin_stats,
        admin_logs=admin_logs,
        admin_user_entitlement=admin_user_entitlement,
        admin_grant_pro_access=admin_grant_pro_access,
        admin_revoke_pro_access=admin_revoke_pro_access,
        admin_run_tests=admin_run_tests,
        admin_last_test_run=admin_last_test_run,
        admin_test_catalog=admin_test_catalog,
        admin_tests_ui=admin_tests_ui,
        admin_graph_density=admin_graph_density,
        admin_graph_playback=admin_graph_playback,
        admin_pipeline_runs=admin_pipeline_runs,
        admin_judge_stats=admin_judge_stats,
        admin_translate_history=admin_translate_history,
        admin_user_activity=admin_user_activity,
        admin_user_usage=admin_user_usage,
        admin_user_cost_summary=admin_user_cost_summary,
        admin_host_metrics=admin_host_metrics,
        admin_users_search=admin_users_search,
        admin_observability=admin_observability,
        admin_stats_trends=admin_stats_trends,
        admin_log_retention_run=admin_log_retention_run,
        admin_audit=admin_audit,
        admin_orphans_scan=admin_orphans_scan,
        admin_user_detail_ui=admin_user_detail_ui,
        runtime_settings_fn=runtime_settings_fn,
    )
    return routers.login, routers.html, routers.api
