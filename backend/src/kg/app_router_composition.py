from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI

from .admin_wiring import create_admin_handlers
from .routers import (
    auth_router,
    billing_router,
    notebook_router,
    pipeline_router,
    podcast_router,
    static_pages_router,
    system_router,
    translate_router,
    user_router,
    vocab_router,
    web_auth_router,
)
from .routers.admin import AdminRouters, build_admin_routers


@dataclass(frozen=True)
class AppRouters:
    domain: tuple[APIRouter, ...]
    admin: AdminRouters


def build_domain_routers() -> tuple[APIRouter, ...]:
    return (
        system_router,
        static_pages_router,
        user_router,
        billing_router,
        vocab_router,
        notebook_router,
        pipeline_router,
        translate_router,
        auth_router,
        web_auth_router,
        podcast_router,
    )


def build_app_routers(
    *,
    runtime_settings_fn: Callable[[], Any],
    runtime_users_lock_file_fn: Callable[[], Path],
    load_users_fn: Callable[[], dict[str, dict[str, Any]]],
    save_users_fn: Callable[[dict[str, dict[str, Any]]], None],
    mem_log_getter: Callable[..., list[dict[str, Any]]],
    card_store_factory: Callable[..., Any],
    build_entitlements_response_fn: Callable[[dict[str, Any] | None], Any],
    current_admin_grant_record_fn: Callable[[dict[str, Any] | None], dict[str, Any]],
) -> AppRouters:
    admin_handlers = create_admin_handlers(
        runtime_settings_fn=runtime_settings_fn,
        runtime_users_lock_file_fn=runtime_users_lock_file_fn,
        load_users_fn=load_users_fn,
        save_users_fn=save_users_fn,
        mem_log_getter=mem_log_getter,
        card_store_factory=card_store_factory,
        build_entitlements_response_fn=build_entitlements_response_fn,
        current_admin_grant_record_fn=current_admin_grant_record_fn,
    )
    admin_routers = build_admin_routers(
        admin_ui=admin_handlers.admin_ui,
        admin_stats=admin_handlers.admin_stats,
        admin_logs=admin_handlers.admin_logs,
        admin_user_entitlement=admin_handlers.admin_user_entitlement,
        admin_grant_pro_access=admin_handlers.admin_grant_pro_access,
        admin_revoke_pro_access=admin_handlers.admin_revoke_pro_access,
        admin_run_tests=admin_handlers.admin_run_tests,
        admin_last_test_run=admin_handlers.admin_last_test_run,
        admin_test_catalog=admin_handlers.admin_test_catalog,
        admin_tests_ui=admin_handlers.admin_tests_ui,
        admin_graph_density=admin_handlers.admin_graph_density,
        admin_graph_playback=admin_handlers.admin_graph_playback,
        admin_pipeline_runs=admin_handlers.admin_pipeline_runs,
        admin_judge_stats=admin_handlers.admin_judge_stats,
        admin_translate_history=admin_handlers.admin_translate_history,
        admin_user_activity=admin_handlers.admin_user_activity,
        admin_user_usage=admin_handlers.admin_user_usage,
        admin_user_cost_summary=admin_handlers.admin_user_cost_summary,
        admin_host_metrics=admin_handlers.admin_host_metrics,
        admin_users_search=admin_handlers.admin_users_search,
        admin_observability=admin_handlers.admin_observability,
        admin_stats_trends=admin_handlers.admin_stats_trends,
        admin_log_retention_run=admin_handlers.admin_log_retention_run,
        admin_audit=admin_handlers.admin_audit,
        admin_orphans_scan=admin_handlers.admin_orphans_scan,
        admin_user_detail_ui=admin_handlers.admin_user_detail_ui,
        runtime_settings_fn=runtime_settings_fn,
    )
    return AppRouters(
        domain=build_domain_routers(),
        admin=admin_routers,
    )


def include_app_routers(app: FastAPI, routers: AppRouters) -> None:
    for router in routers.domain:
        app.include_router(router)
    app.include_router(routers.admin.login)
    app.include_router(routers.admin.html)
    app.include_router(routers.admin.api)
