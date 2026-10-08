from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.routing import APIRoute

from kg.app_router_composition import (
    AppRouterDependencies,
    AppRouters,
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
    return {(route.path, tuple(sorted(route.methods or ()))) for route in app.routes if isinstance(route, APIRoute)}


def _router_surface(router) -> set[tuple[str, tuple[str, ...]]]:
    return {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes if isinstance(route, APIRoute)}


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


_REMOVED_COMPAT_WRAPPERS = frozenset(
    {
        "install_app_middlewares",
        "install_app_exception_handlers",
        "build_app_routers",
        "install_runtime_user_state",
        "create_admin_handlers",
        "build_admin_routers",
        "build_admin_router",
        "build_api_admin_router",
        "build_html_admin_router",
    }
)


def test_dead_compat_wrappers_stay_removed_from_src():
    """The keyword-signature wrappers had no production caller (#2260)."""
    import ast

    src_root = Path(__file__).resolve().parents[1] / "src"
    found: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in _REMOVED_COMPAT_WRAPPERS:
                found.append(f"{path.relative_to(src_root)}:{node.name}")
            elif isinstance(node, ast.ImportFrom):
                found.extend(
                    f"{path.relative_to(src_root)}:import {alias.name}"
                    for alias in node.names
                    if alias.name in _REMOVED_COMPAT_WRAPPERS
                )
    assert not found, f"dead compat wrappers reintroduced: {found}"
