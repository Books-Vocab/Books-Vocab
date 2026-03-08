from __future__ import annotations

from fastapi.routing import APIRoute

import kg.api as api_mod
from kg.settings import KGSettings


def test_create_app_with_explicit_settings_registers_all_domain_routes(tmp_path):
    original_settings = KGSettings(
        data_dir=api_mod.DATA_DIR,
        jwt_secret=api_mod.JWT_SECRET,
        jwt_algorithm=api_mod.JWT_ALGORITHM,
        jwt_expiry_minutes=api_mod.JWT_EXPIRY_MINUTES,
        google_client_id=api_mod.GOOGLE_CLIENT_ID,
        apple_bundle_id=api_mod.APPLE_BUNDLE_ID,
        app_store_allow_unsigned_sync=api_mod.APP_STORE_ALLOW_UNSIGNED_SYNC,
        app_store_allow_unsigned_notifications=api_mod.APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS,
        admin_token=api_mod.ADMIN_TOKEN,
    )

    try:
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
        }

        missing = expected - routes
        assert not missing, f"Missing routes from create_app(): {sorted(missing)}"
    finally:
        api_mod.configure_runtime(original_settings)
