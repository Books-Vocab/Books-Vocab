from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.routing import APIRoute

from kg.app_router_composition import (
    AppRouterDependencies,
    AppRouters,
    build_app_routers,
    build_app_routers_from_dependencies,
    include_app_routers,
)
from kg.routers.admin import AdminRouters


def _settings():
    return SimpleNamespace(
        admin_token="adm-token",
        admin_password="",
        data_dir=Path("/tmp/kg-data"),
    )


def _route_surface(app: FastAPI) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (route.path, tuple(sorted(route.methods or ())))
        for route in app.routes
        if isinstance(route, APIRoute)
    }


def _router_surface(router) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (route.path, tuple(sorted(route.methods or ())))
        for route in router.routes
        if isinstance(route, APIRoute)
    }


def _dependencies() -> AppRouterDependencies:
    return AppRouterDependencies(
        runtime_settings_fn=_settings,
        runtime_users_lock_file_fn=lambda: Path("/tmp/users.lock"),
        load_users_fn=lambda: {},
        save_users_fn=lambda users: None,
        mem_log_getter=lambda *_args, **_kwargs: [],
        card_store_factory=lambda *_args, **_kwargs: None,
        build_entitlements_response_fn=lambda user_record: {"ok": True},
        current_admin_grant_record_fn=lambda user_record: {},
    )


def test_build_app_routers_returns_named_bundle():
    routers = build_app_routers_from_dependencies(dependencies=_dependencies())

    assert isinstance(routers, AppRouters)
    assert isinstance(routers.admin, AdminRouters)
    assert len(routers.domain) >= 5


def test_build_app_routers_from_dependencies_matches_compat_wrapper():
    named = build_app_routers_from_dependencies(dependencies=_dependencies())
    compat = build_app_routers(
        runtime_settings_fn=_settings,
        runtime_users_lock_file_fn=lambda: Path("/tmp/users.lock"),
        load_users_fn=lambda: {},
        save_users_fn=lambda users: None,
        mem_log_getter=lambda *_args, **_kwargs: [],
        card_store_factory=lambda *_args, **_kwargs: None,
        build_entitlements_response_fn=lambda user_record: {"ok": True},
        current_admin_grant_record_fn=lambda user_record: {},
    )

    assert isinstance(named, AppRouters)
    assert isinstance(compat, AppRouters)
    assert named.domain == compat.domain
    assert _router_surface(named.admin.login) == _router_surface(compat.admin.login)
    assert _router_surface(named.admin.html) == _router_surface(compat.admin.html)
    assert _router_surface(named.admin.api) == _router_surface(compat.admin.api)


def test_app_router_dependencies_are_replaceable_named_contract():
    deps = _dependencies()
    replacement = replace(
        deps,
        runtime_users_lock_file_fn=lambda: Path("/tmp/other.lock"),
    )

    assert deps.runtime_users_lock_file_fn() == Path("/tmp/users.lock")
    assert replacement.runtime_users_lock_file_fn() == Path("/tmp/other.lock")


def test_include_app_routers_registers_domain_and_admin_routes():
    app = FastAPI()
    routers = build_app_routers_from_dependencies(dependencies=_dependencies())

    include_app_routers(app, routers)

    routes = _route_surface(app)
    expected = {
        ("/api/user/config", ("GET",)),
        ("/api/pipeline", ("POST",)),
        ("/auth/verify", ("POST",)),
        ("/api/admin/stats", ("GET",)),
        ("/admin/login", ("GET",)),
    }

    missing = expected - routes
    assert not missing, f"Missing routes from include_app_routers(): {sorted(missing)}"
