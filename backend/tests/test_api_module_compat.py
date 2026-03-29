from __future__ import annotations

import inspect

import kg.api as api_mod
from kg.settings import KGSettings


def test_api_module_exposes_expected_surface():
    expected_symbols = [
        "app",
        "create_app",
        "get_current_user",
        "get_user_lock",
        "_card_store",
        "_graph_store",
        "_embedding_store",
        "_parse_datetime",
        "_default_subscription_payload",
        "_build_entitlements_response",
        "_current_subscription_record",
        "_resolve_user_id_from_subscription_index",
        "_write_subscription_snapshot",
        "_notification_status",
        "translate_quick",
        "translate_phrase",
        "translate_explain",
        "_create_jwt_token",
        "_resolve_and_link_user",
        "auth_verify",
        "list_vocab",
        "lookup_word",
        "delete_word",
        "get_graph_links",
        "add_vocab",
        "_build_links_by_kind",
        "_card_response",
        "_run_pipeline_background",
        "run_pipeline",
        "_get_settings",
    ]

    missing = [name for name in expected_symbols if not hasattr(api_mod, name)]
    assert not missing, f"Missing compatibility symbols: {missing}"


def test_api_module_no_legacy_globals():
    """Verify that legacy module-level mutable globals have been removed."""
    removed = [
        "DATA_DIR",
        "USERS_FILE",
        "USERS_LOCK_FILE",
        "APP_STORE_NOTIFICATIONS_FILE",
        "JWT_SECRET",
        "JWT_ALGORITHM",
        "JWT_EXPIRY_MINUTES",
        "GOOGLE_CLIENT_ID",
        "APPLE_BUNDLE_ID",
        "APP_STORE_ALLOW_UNSIGNED_SYNC",
        "APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS",
        "ADMIN_TOKEN",
        "configure_runtime",
        "_runtime_settings",
        "_runtime_users_file",
        "_runtime_users_lock_file",
        "_runtime_notifications_file",
        "load_users",
        "save_users",
    ]
    still_present = [name for name in removed if hasattr(api_mod, name)]
    assert not still_present, f"Legacy globals still present: {still_present}"


def test_api_module_keeps_expected_callable_shapes():
    assert inspect.iscoroutinefunction(api_mod.get_user_lock)
    assert callable(api_mod.create_app)
    assert callable(api_mod._card_store)
    assert callable(api_mod._graph_store)
    assert callable(api_mod._embedding_store)
    assert callable(api_mod.translate_quick)
    assert callable(api_mod.translate_phrase)
    assert callable(api_mod.translate_explain)
    assert callable(api_mod._create_jwt_token)
    assert callable(api_mod._resolve_and_link_user)
    assert callable(api_mod.list_vocab)
    assert callable(api_mod.lookup_word)
    assert callable(api_mod.delete_word)
    assert callable(api_mod.get_graph_links)
    assert callable(api_mod.add_vocab)
    assert callable(api_mod._build_links_by_kind)
    assert callable(api_mod._card_response)
    assert callable(api_mod._run_pipeline_background)
    assert callable(api_mod.run_pipeline)


def test_create_app_accepts_explicit_settings(tmp_path):
    settings = KGSettings(
        data_dir=tmp_path,
        jwt_secret="test-secret",
        admin_token="adm-token",
        app_store_allow_unsigned_sync=True,
        app_store_allow_unsigned_notifications=True,
    )

    custom_app = api_mod.create_app(settings)
    assert custom_app.state.kg_settings == settings


def test_settings_accessible_via_app_state():
    """The global app instance should have settings on app.state.kg_settings."""
    assert hasattr(api_mod.app.state, "kg_settings")
    assert isinstance(api_mod.app.state.kg_settings, KGSettings)


def test_load_save_users_on_app_state():
    """app.state should expose load_users and save_users closures."""
    assert callable(api_mod.app.state.load_users)
    assert callable(api_mod.app.state.save_users)
