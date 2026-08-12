from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import APIRouter

from kg.deps import get_admin_user
from kg.routers.admin import build_api_admin_router
from kg.routers.admin_features.registry import (
    ADMIN_API_ROUTE_REGISTRY,
    AdminRouteRegistration,
    iter_bound_admin_api_routes,
    validate_admin_route_registry,
)


def test_admin_route_registry_has_unique_feature_owned_routes_in_safe_order():
    validate_admin_route_registry()

    route_keys = [
        (registration.method, registration.path)
        for registration in ADMIN_API_ROUTE_REGISTRY
    ]

    assert len(route_keys) == len(set(route_keys))
    assert route_keys.index(("get", "/api/admin/users/search")) < route_keys.index(
        ("get", "/api/admin/users/{user_id}/entitlement")
    )
    assert all(registration.feature for registration in ADMIN_API_ROUTE_REGISTRY)
    assert all(registration.handler_name for registration in ADMIN_API_ROUTE_REGISTRY)


def test_admin_route_registry_binds_optional_missing_handlers_without_dropping_ownership():
    def stats():
        return {"ok": True}

    handlers = SimpleNamespace(admin_stats=stats)

    bound = iter_bound_admin_api_routes(handlers)

    stats = next(route for route in bound if route.path == "/api/admin/stats")
    optional = next(route for route in bound if route.path == "/api/admin/graph-density")

    assert stats.endpoint is handlers.admin_stats
    assert optional.endpoint is None
    assert optional.feature


def test_admin_route_registry_rejects_duplicate_method_and_path_even_with_different_features():
    duplicate = replace(
        ADMIN_API_ROUTE_REGISTRY[0],
        feature="duplicate-owner",
    )

    with pytest.raises(ValueError, match="duplicate admin route"):
        validate_admin_route_registry((*ADMIN_API_ROUTE_REGISTRY, duplicate))


def test_admin_route_registration_requires_admin_api_paths():
    invalid = AdminRouteRegistration(
        feature="stats",
        method="get",
        path="/admin/stats",
        handler_name="admin_stats",
    )

    with pytest.raises(ValueError, match="must start with /api/admin/"):
        validate_admin_route_registry((invalid,))


def test_admin_route_registry_rejects_missing_required_registration():
    with pytest.raises(ValueError, match="missing required admin route"):
        validate_admin_route_registry(ADMIN_API_ROUTE_REGISTRY[:-1])


def test_admin_api_router_keeps_registry_surface_and_admin_dependency_in_sync():
    def endpoint():
        return {"ok": True}

    router = build_api_admin_router(
        admin_stats=endpoint,
        admin_logs=endpoint,
        admin_user_entitlement=endpoint,
        admin_grant_pro_access=endpoint,
        admin_revoke_pro_access=endpoint,
        admin_run_tests=endpoint,
        admin_last_test_run=endpoint,
        admin_test_catalog=endpoint,
        admin_graph_density=endpoint,
        admin_graph_playback=endpoint,
        admin_pipeline_runs=endpoint,
        admin_judge_stats=endpoint,
        admin_translate_history=endpoint,
        admin_user_activity=endpoint,
        admin_user_usage=endpoint,
        admin_user_cost_summary=endpoint,
        admin_host_metrics=endpoint,
        admin_users_search=endpoint,
        admin_observability=endpoint,
        admin_stats_trends=endpoint,
        admin_log_retention_run=endpoint,
        admin_audit=endpoint,
        admin_orphans_scan=endpoint,
    )

    legacy_surface = {
        (frozenset(route.methods or ()), route.path)
        for route in router.routes
    }
    registry_surface = {
        (frozenset({registration.method.upper()}), registration.path)
        for registration in ADMIN_API_ROUTE_REGISTRY
    }

    assert isinstance(router, APIRouter)
    assert legacy_surface == registry_surface
    assert [dependency.dependency for dependency in router.dependencies] == [get_admin_user]
