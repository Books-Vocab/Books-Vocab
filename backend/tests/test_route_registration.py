from __future__ import annotations

from fastapi.routing import APIRoute

import kg.api as api_mod


def test_registered_routes_cover_core_api_surface():
    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in api_mod.app.routes
        if isinstance(route, APIRoute)
    }

    expected_routes = {
        ("/privacy.html", ("GET",)),
        ("/support.html", ("GET",)),
        ("/api/user/config", ("GET",)),
        ("/api/user/config", ("PUT",)),
        ("/api/user/entitlements", ("GET",)),
        ("/api/billing/app-store/sync", ("POST",)),
        ("/api/billing/app-store/notifications", ("POST",)),
        ("/api/billing/app-store/reconcile", ("POST",)),
        ("/api/user/account", ("DELETE",)),
        ("/api/health", ("GET",)),
        ("/api/vocab", ("GET",)),
        ("/api/vocab", ("POST",)),
        ("/api/vocab/{word}", ("GET",)),
        ("/api/vocab/{word}", ("DELETE",)),
        ("/api/graph/links", ("GET",)),
        ("/api/pipeline", ("POST",)),
        ("/api/translate/quick", ("POST",)),
        ("/api/translate/phrase", ("POST",)),
        ("/api/translate/explain", ("POST",)),
        ("/auth/verify", ("POST",)),
        ("/admin", ("GET",)),
        ("/api/admin/stats", ("GET",)),
        ("/api/admin/logs", ("GET",)),
        ("/api/admin/users/{user_id}/entitlement", ("GET",)),
        ("/api/admin/users/{user_id}/admin-grant", ("POST",)),
        ("/api/admin/users/{user_id}/admin-grant", ("DELETE",)),
        ("/api/admin/tests/run", ("POST",)),
        ("/api/admin/tests/last", ("GET",)),
        ("/api/admin/tests/catalog", ("GET",)),
        ("/admin/tests", ("GET",)),
        ("/admin/test", ("GET",)),
    }

    missing = expected_routes - routes
    assert not missing, f"Missing registered routes: {sorted(missing)}"
