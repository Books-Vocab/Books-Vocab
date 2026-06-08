from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter

from kg.routers.admin import AdminRouters, build_admin_router, build_admin_routers


def _settings():
    return SimpleNamespace(admin_token="adm-token", admin_password="")


def _html():
    return "<html></html>"


def _api():
    return {"ok": True}


def _route_surface(router: APIRouter) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (route.path, tuple(sorted(route.methods or ())))
        for route in router.routes
    }


def test_build_admin_routers_returns_named_bundle():
    routers = build_admin_routers(
        admin_ui=_html,
        admin_stats=_api,
        admin_logs=_api,
        admin_user_entitlement=_api,
        admin_grant_pro_access=_api,
        admin_revoke_pro_access=_api,
        admin_run_tests=_api,
        admin_last_test_run=_api,
        admin_test_catalog=_api,
        admin_tests_ui=_html,
        runtime_settings_fn=_settings,
    )

    assert isinstance(routers, AdminRouters)
    assert isinstance(routers.login, APIRouter)
    assert isinstance(routers.html, APIRouter)
    assert isinstance(routers.api, APIRouter)


def test_build_admin_router_preserves_legacy_tuple_contract():
    named = build_admin_routers(
        admin_ui=_html,
        admin_stats=_api,
        admin_logs=_api,
        admin_user_entitlement=_api,
        admin_grant_pro_access=_api,
        admin_revoke_pro_access=_api,
        admin_run_tests=_api,
        admin_last_test_run=_api,
        admin_test_catalog=_api,
        admin_tests_ui=_html,
        runtime_settings_fn=_settings,
    )

    legacy = build_admin_router(
        admin_ui=_html,
        admin_stats=_api,
        admin_logs=_api,
        admin_user_entitlement=_api,
        admin_grant_pro_access=_api,
        admin_revoke_pro_access=_api,
        admin_run_tests=_api,
        admin_last_test_run=_api,
        admin_test_catalog=_api,
        admin_tests_ui=_html,
        runtime_settings_fn=_settings,
    )

    assert len(legacy) == 3
    assert _route_surface(legacy[0]) == _route_surface(named.login)
    assert _route_surface(legacy[1]) == _route_surface(named.html)
    assert _route_surface(legacy[2]) == _route_surface(named.api)
