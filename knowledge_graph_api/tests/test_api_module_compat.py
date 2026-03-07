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
