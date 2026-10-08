from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from fastapi import APIRouter

from kg.routers.admin import (
    AdminApiHandlers,
    AdminHtmlHandlers,
    AdminRouteHandlers,
    AdminRouters,
    build_admin_route_handlers,
    build_admin_routers_from_handlers,
)


def _settings():
    return SimpleNamespace(admin_token="adm-token", admin_password="")


def _html():
    return "<html></html>"


def _api():
    return {"ok": True}


@dataclass(frozen=True)
class _FlatAdminHandlers:
    admin_ui: object = _html
    admin_stats: object = _api
    admin_logs: object = _api
    admin_user_entitlement: object = _api
    admin_grant_pro_access: object = _api
    admin_revoke_pro_access: object = _api
    admin_run_tests: object = _api
    admin_last_test_run: object = _api
    admin_test_catalog: object = _api
    admin_tests_ui: object = _html
    admin_graph_density: object = _api
    admin_graph_playback: object = _api
    admin_pipeline_runs: object = _api
    admin_judge_stats: object = _api
    admin_translate_history: object = _api
    admin_user_activity: object = _api
    admin_user_usage: object = _api
    admin_user_cost_summary: object = _api
    admin_host_metrics: object = _api
    admin_users_search: object = _api
    admin_observability: object = _api
    admin_stats_trends: object = _api
    admin_log_retention_run: object = _api
    admin_audit: object = _api
    admin_user_detail_ui: object = _html
    admin_orphans_scan: object = _api


def _route_surface(router: APIRouter) -> set[tuple[str, tuple[str, ...]]]:
    return {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}


def test_build_admin_routers_from_handlers_returns_named_bundle():
    routers = build_admin_routers_from_handlers(
        handlers=build_admin_route_handlers(_FlatAdminHandlers()),
        runtime_settings_fn=_settings,
    )

    assert isinstance(routers, AdminRouters)
    assert isinstance(routers.login, APIRouter)
    assert isinstance(routers.html, APIRouter)
    assert isinstance(routers.api, APIRouter)


def test_build_admin_route_handlers_returns_named_contract():
    handlers = build_admin_route_handlers(_FlatAdminHandlers())

    assert isinstance(handlers, AdminRouteHandlers)
    assert isinstance(handlers.html, AdminHtmlHandlers)
    assert isinstance(handlers.api, AdminApiHandlers)
    assert handlers.html.admin_ui is _html
    assert handlers.html.admin_tests_ui is _html
    assert handlers.api.admin_stats is _api
    assert handlers.api.admin_audit is _api


def test_build_admin_routers_from_handlers_matches_explicit_builder():
    routed = build_admin_routers_from_handlers(
        handlers=build_admin_route_handlers(_FlatAdminHandlers()),
        runtime_settings_fn=_settings,
    )
    api_names = [name for name in AdminApiHandlers.__dataclass_fields__]
    explicit = build_admin_routers_from_handlers(
        handlers=AdminRouteHandlers(
            html=AdminHtmlHandlers(
                admin_ui=_html,
                admin_tests_ui=_html,
                admin_user_detail_ui=_html,
            ),
            api=AdminApiHandlers(**{name: _api for name in api_names}),
        ),
        runtime_settings_fn=_settings,
    )

    assert _route_surface(routed.login) == _route_surface(explicit.login)
    assert _route_surface(routed.html) == _route_surface(explicit.html)
    assert _route_surface(routed.api) == _route_surface(explicit.api)
