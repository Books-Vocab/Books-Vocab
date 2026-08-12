from __future__ import annotations

from dataclasses import replace

import pytest

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
    handlers = type("Handlers", (), {"admin_stats": lambda: {"ok": True}})()

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
