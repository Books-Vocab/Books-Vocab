from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI

from .routers import (
    build_admin_router,
    build_auth_router,
    build_billing_router,
    build_pipeline_router,
    build_static_pages_router,
    build_translate_router,
    build_user_router,
    build_vocab_router,
)


def register_routes(
    app: FastAPI,
    *,
    get_privacy_policy: Callable[..., Any],
    get_support: Callable[..., Any],
    get_terms: Callable[..., Any],
    get_user_config: Callable[..., Any],
    get_user_entitlements: Callable[..., Any],
    get_user_quota: Callable[..., Any],
    update_user_config: Callable[..., Any],
    delete_user_account: Callable[..., Any],
    health: Callable[..., Any],
    sync_app_store_subscription: Callable[..., Any],
    app_store_notifications: Callable[..., Any],
    reconcile_app_store_subscription: Callable[..., Any],
    list_vocab: Callable[..., Any],
    lookup_word: Callable[..., Any],
    delete_word: Callable[..., Any],
    get_graph_links: Callable[..., Any],
    add_vocab: Callable[..., Any],
    push_review: Callable[..., Any],
    run_pipeline: Callable[..., Any],
    translate_quick: Callable[..., Any],
    translate_phrase: Callable[..., Any],
    translate_explain: Callable[..., Any],
    auth_verify: Callable[..., Any],
    admin_ui: Callable[..., Any],
    admin_stats: Callable[..., Any],
    admin_logs: Callable[..., Any],
    admin_user_entitlement: Callable[..., Any],
    admin_grant_pro_access: Callable[..., Any],
    admin_revoke_pro_access: Callable[..., Any],
    admin_run_tests: Callable[..., Any],
    admin_last_test_run: Callable[..., Any],
    admin_test_catalog: Callable[..., Any],
    admin_tests_ui: Callable[..., Any],
) -> None:
    app.include_router(
        build_static_pages_router(
            get_privacy_policy=get_privacy_policy,
            get_support=get_support,
            get_terms=get_terms,
        )
    )
    app.include_router(
        build_user_router(
            get_user_config=get_user_config,
            get_user_entitlements=get_user_entitlements,
            get_user_quota=get_user_quota,
            update_user_config=update_user_config,
            delete_user_account=delete_user_account,
            health=health,
        )
    )
    app.include_router(
        build_billing_router(
            sync_app_store_subscription=sync_app_store_subscription,
            app_store_notifications=app_store_notifications,
            reconcile_app_store_subscription=reconcile_app_store_subscription,
        )
    )
    app.include_router(
        build_vocab_router(
            list_vocab=list_vocab,
            lookup_word=lookup_word,
            delete_word=delete_word,
            get_graph_links=get_graph_links,
            add_vocab=add_vocab,
            push_review=push_review,
        )
    )
    app.include_router(build_pipeline_router(run_pipeline=run_pipeline))
    app.include_router(
        build_translate_router(
            translate_quick=translate_quick,
            translate_phrase=translate_phrase,
            translate_explain=translate_explain,
        )
    )
    app.include_router(build_auth_router(auth_verify=auth_verify))
    app.include_router(
        build_admin_router(
            admin_ui=admin_ui,
            admin_stats=admin_stats,
            admin_logs=admin_logs,
            admin_user_entitlement=admin_user_entitlement,
            admin_grant_pro_access=admin_grant_pro_access,
            admin_revoke_pro_access=admin_revoke_pro_access,
            admin_run_tests=admin_run_tests,
            admin_last_test_run=admin_last_test_run,
            admin_test_catalog=admin_test_catalog,
            admin_tests_ui=admin_tests_ui,
        )
    )
