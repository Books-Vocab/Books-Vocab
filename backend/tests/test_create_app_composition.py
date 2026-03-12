from __future__ import annotations

from fastapi.routing import APIRoute

import kg.api as api_mod
from kg.settings import KGSettings


def test_create_app_with_explicit_settings_registers_all_domain_routes(tmp_path):
    app = api_mod.create_app(
        KGSettings(
            data_dir=tmp_path,
            jwt_secret="test-secret",
            admin_token="adm-secret",
            app_store_allow_unsigned_sync=True,
            app_store_allow_unsigned_notifications=True,
        )
    )

    routes = {
        (route.path, tuple(sorted(route.methods)))
        for route in app.routes
        if isinstance(route, APIRoute)
    }

    expected = {
        ("/api/user/config", ("GET",)),
        ("/api/billing/app-store/sync", ("POST",)),
        ("/api/vocab", ("GET",)),
        ("/api/pipeline", ("POST",)),
        ("/api/translate/quick", ("POST",)),
        ("/auth/verify", ("POST",)),
        ("/api/admin/stats", ("GET",)),
        ("/api/admin/users/{user_id}/admin-grant", ("POST",)),
    }

    missing = expected - routes
    assert not missing, f"Missing routes from create_app(): {sorted(missing)}"
