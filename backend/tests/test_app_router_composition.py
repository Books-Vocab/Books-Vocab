from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.routing import APIRoute

from kg.app_router_composition import AppRouters, build_app_routers, include_app_routers
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


def test_build_app_routers_returns_named_bundle():
    routers = build_app_routers(
        runtime_settings_fn=_settings,
        runtime_users_lock_file_fn=lambda: Path("/tmp/users.lock"),
        load_users_fn=lambda: {},
        save_users_fn=lambda users: None,
        mem_log_getter=lambda *_args, **_kwargs: [],
        card_store_factory=lambda *_args, **_kwargs: None,
        build_entitlements_response_fn=lambda user_record: {"ok": True},
        current_admin_grant_record_fn=lambda user_record: {},
    )

    assert isinstance(routers, AppRouters)
    assert isinstance(routers.admin, AdminRouters)
    assert len(routers.domain) >= 5


def test_include_app_routers_registers_domain_and_admin_routes():
    app = FastAPI()
    routers = build_app_routers(
        runtime_settings_fn=_settings,
        runtime_users_lock_file_fn=lambda: Path("/tmp/users.lock"),
        load_users_fn=lambda: {},
        save_users_fn=lambda users: None,
        mem_log_getter=lambda *_args, **_kwargs: [],
        card_store_factory=lambda *_args, **_kwargs: None,
        build_entitlements_response_fn=lambda user_record: {"ok": True},
        current_admin_grant_record_fn=lambda user_record: {},
    )

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
