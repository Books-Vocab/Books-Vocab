"""Feature-owned admin API route registrations."""

from .registry import (
    ADMIN_API_ROUTE_REGISTRY,
    REQUIRED_ADMIN_API_ROUTE_KEYS,
    AdminRouteRegistration,
    BoundAdminRoute,
    iter_bound_admin_api_routes,
    validate_admin_route_registry,
)

__all__ = [
    "ADMIN_API_ROUTE_REGISTRY",
    "AdminRouteRegistration",
    "BoundAdminRoute",
    "REQUIRED_ADMIN_API_ROUTE_KEYS",
    "iter_bound_admin_api_routes",
    "validate_admin_route_registry",
]
