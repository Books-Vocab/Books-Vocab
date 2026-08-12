"""Single source of truth for admin API route ownership.

The router layer still owns authentication and FastAPI registration.  This
module owns the feature/path/handler mapping so adding a feature cannot
silently update only one of the legacy handler or builder lists.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ...api_models import AdminUserEntitlementResponse


@dataclass(frozen=True)
class AdminRouteRegistration:
    feature: str
    method: str
    path: str
    handler_name: str
    response_model: object | None = None


@dataclass(frozen=True)
class BoundAdminRoute:
    feature: str
    method: str
    path: str
    handler_name: str
    endpoint: Any | None
    response_model: object | None = None


ADMIN_API_ROUTE_REGISTRY: tuple[AdminRouteRegistration, ...] = (
    AdminRouteRegistration("stats", "get", "/api/admin/stats", "admin_stats"),
    AdminRouteRegistration("logs", "get", "/api/admin/logs", "admin_logs"),
    # Static search must precede the dynamic user-id routes in FastAPI.
    AdminRouteRegistration("users", "get", "/api/admin/users/search", "admin_users_search"),
    AdminRouteRegistration(
        "entitlements",
        "get",
        "/api/admin/users/{user_id}/entitlement",
        "admin_user_entitlement",
        response_model=AdminUserEntitlementResponse,
    ),
    AdminRouteRegistration(
        "entitlements",
        "post",
        "/api/admin/users/{user_id}/admin-grant",
        "admin_grant_pro_access",
        response_model=AdminUserEntitlementResponse,
    ),
    AdminRouteRegistration(
        "entitlements",
        "delete",
        "/api/admin/users/{user_id}/admin-grant",
        "admin_revoke_pro_access",
        response_model=AdminUserEntitlementResponse,
    ),
    AdminRouteRegistration("tests", "post", "/api/admin/tests/run", "admin_run_tests"),
    AdminRouteRegistration("tests", "get", "/api/admin/tests/last", "admin_last_test_run"),
    AdminRouteRegistration("tests", "get", "/api/admin/tests/catalog", "admin_test_catalog"),
    AdminRouteRegistration("graph", "get", "/api/admin/graph-density", "admin_graph_density"),
    AdminRouteRegistration("graph", "get", "/api/admin/graph-playback", "admin_graph_playback"),
    AdminRouteRegistration("pipeline", "get", "/api/admin/pipeline-runs", "admin_pipeline_runs"),
    AdminRouteRegistration("judge", "get", "/api/admin/judge-stats", "admin_judge_stats"),
    AdminRouteRegistration(
        "translate",
        "get",
        "/api/admin/translate-history",
        "admin_translate_history",
    ),
    AdminRouteRegistration("activity", "get", "/api/admin/user-activity", "admin_user_activity"),
    AdminRouteRegistration("usage", "get", "/api/admin/user-usage", "admin_user_usage"),
    AdminRouteRegistration(
        "usage",
        "get",
        "/api/admin/user-cost-summary",
        "admin_user_cost_summary",
    ),
    AdminRouteRegistration("observability", "get", "/api/admin/host-metrics", "admin_host_metrics"),
    AdminRouteRegistration(
        "users",
        "get",
        "/api/admin/observability",
        "admin_observability",
    ),
    AdminRouteRegistration("trends", "get", "/api/admin/stats/trends", "admin_stats_trends"),
    AdminRouteRegistration(
        "retention",
        "post",
        "/api/admin/log-retention/run",
        "admin_log_retention_run",
    ),
    AdminRouteRegistration("audit", "get", "/api/admin/audit", "admin_audit"),
    AdminRouteRegistration("orphans", "get", "/api/admin/orphans/scan", "admin_orphans_scan"),
)


def validate_admin_route_registry(
    registrations: Iterable[AdminRouteRegistration] = ADMIN_API_ROUTE_REGISTRY,
) -> None:
    """Reject malformed, duplicate, or incomplete route ownership tables."""
    entries = tuple(registrations)
    expected = {
        (registration.method.lower(), registration.path)
        for registration in ADMIN_API_ROUTE_REGISTRY
    }
    seen: dict[tuple[str, str], str] = {}
    for registration in entries:
        method = registration.method.lower()
        if not registration.feature:
            raise ValueError("admin route feature owner must not be empty")
        if not registration.handler_name:
            raise ValueError("admin route handler name must not be empty")
        if not registration.path.startswith("/api/admin/"):
            raise ValueError(f"admin route path {registration.path!r} must start with /api/admin/")
        key = (method, registration.path)
        owner = seen.get(key)
        if owner is not None:
            raise ValueError(f"duplicate admin route {method} {registration.path}: {owner} and {registration.feature}")
        seen[key] = registration.feature
    if set(seen) != expected:
        missing = sorted(expected - set(seen))
        extra = sorted(set(seen) - expected)
        raise ValueError(f"missing required admin route(s): missing={missing}, extra={extra}")


def iter_bound_admin_api_routes(handlers: Any) -> tuple[BoundAdminRoute, ...]:
    """Bind registry entries to a handler bundle without changing ownership."""
    validate_admin_route_registry()
    return tuple(
        BoundAdminRoute(
            feature=registration.feature,
            method=registration.method,
            path=registration.path,
            handler_name=registration.handler_name,
            endpoint=getattr(handlers, registration.handler_name, None),
            response_model=registration.response_model,
        )
        for registration in ADMIN_API_ROUTE_REGISTRY
    )
