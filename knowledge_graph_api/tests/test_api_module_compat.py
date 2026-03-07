from __future__ import annotations

import inspect

import kg.api as api_mod


def test_api_module_exposes_legacy_surface():
    expected_symbols = [
        "app",
        "DATA_DIR",
        "USERS_FILE",
        "USERS_LOCK_FILE",
        "APP_STORE_NOTIFICATIONS_FILE",
        "APPLE_BUNDLE_ID",
        "load_users",
        "save_users",
        "get_current_user",
        "get_user_lock",
        "_card_store",
        "_graph_store",
        "_embedding_store",
        "_normalize_users_payload",
        "_parse_datetime",
        "_default_subscription_payload",
        "_build_entitlements_response",
        "_current_subscription_record",
        "_require_pro_access",
        "_append_app_store_event",
        "_resolve_user_id_from_subscription_index",
        "_write_subscription_snapshot",
        "_notification_status",
        "_decode_signed_transaction_info",
        "_decode_notification_payload",
        "_build_test_catalog",
        "_run_pytest_matrix",
    ]

    missing = [name for name in expected_symbols if not hasattr(api_mod, name)]
    assert not missing, f"Missing compatibility symbols: {missing}"


def test_api_module_keeps_expected_callable_shapes():
    assert inspect.iscoroutinefunction(api_mod.get_user_lock)
    assert callable(api_mod.load_users)
    assert callable(api_mod.save_users)
    assert callable(api_mod._card_store)
    assert callable(api_mod._graph_store)
    assert callable(api_mod._embedding_store)
    assert callable(api_mod._run_pytest_matrix)
    assert callable(api_mod._build_test_catalog)
