from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, FastAPI

from .admin_wiring import (
    AdminGrantRecordReader,
    AdminHandlerDependencies,
    CardStoreFactory,
    EntitlementsBuilder,
    MemLogGetter,
    create_admin_handlers_from_dependencies,
)
from .routers import (
    auth_router,
    billing_router,
    dictionary_router,
    library_router,
    notebook_router,
    pipeline_router,
    podcast_router,
    shared_decks_router,
    static_pages_router,
    system_router,
    translate_router,
    user_router,
    vocab_router,
    web_auth_router,
)
from .routers.admin import (
    AdminRouters,
    SupportsAdminSettings,
    build_admin_route_handlers,
    build_admin_routers_from_handlers,
)
from .types import UsersPayload

RuntimeSettingsFn = Callable[[], SupportsAdminSettings]


@dataclass(frozen=True)
class AppRouters:
    domain: tuple[APIRouter, ...]
    admin: AdminRouters


@dataclass(frozen=True)
class AppRouterDependencies:
    runtime_settings_fn: RuntimeSettingsFn
    runtime_users_lock_file_fn: Callable[[], Path]
    load_users_fn: Callable[[], UsersPayload]
    save_users_fn: Callable[[UsersPayload], None]
    mem_log_getter: MemLogGetter
    card_store_factory: CardStoreFactory
    build_entitlements_response_fn: EntitlementsBuilder
    current_admin_grant_record_fn: AdminGrantRecordReader


def build_domain_routers() -> tuple[APIRouter, ...]:
    return (
        system_router,
        static_pages_router,
        user_router,
        billing_router,
        dictionary_router,
        vocab_router,
        notebook_router,
        library_router,
        pipeline_router,
        translate_router,
        auth_router,
        web_auth_router,
        podcast_router,
        shared_decks_router,
    )


def build_app_routers_from_dependencies(
    *,
    dependencies: AppRouterDependencies,
) -> AppRouters:
    runtime_settings_fn = dependencies.runtime_settings_fn
    admin_handlers = create_admin_handlers_from_dependencies(
        dependencies=AdminHandlerDependencies(
            runtime_settings_fn=runtime_settings_fn,
            runtime_users_lock_file_fn=dependencies.runtime_users_lock_file_fn,
            load_users_fn=dependencies.load_users_fn,
            save_users_fn=dependencies.save_users_fn,
            mem_log_getter=dependencies.mem_log_getter,
            card_store_factory=dependencies.card_store_factory,
            build_entitlements_response_fn=dependencies.build_entitlements_response_fn,
            current_admin_grant_record_fn=dependencies.current_admin_grant_record_fn,
        )
    )
    admin_routers = build_admin_routers_from_handlers(
        handlers=build_admin_route_handlers(admin_handlers),
        runtime_settings_fn=runtime_settings_fn,
    )
    return AppRouters(
        domain=build_domain_routers(),
        admin=admin_routers,
    )


def build_app_routers(
    *,
    runtime_settings_fn: RuntimeSettingsFn,
    runtime_users_lock_file_fn: Callable[[], Path],
    load_users_fn: Callable[[], UsersPayload],
    save_users_fn: Callable[[UsersPayload], None],
    mem_log_getter: MemLogGetter,
    card_store_factory: CardStoreFactory,
    build_entitlements_response_fn: EntitlementsBuilder,
    current_admin_grant_record_fn: AdminGrantRecordReader,
) -> AppRouters:
    """Backward-compatible wrapper around :func:`build_app_routers_from_dependencies`."""
    return build_app_routers_from_dependencies(
        dependencies=AppRouterDependencies(
            runtime_settings_fn=runtime_settings_fn,
            runtime_users_lock_file_fn=runtime_users_lock_file_fn,
            load_users_fn=load_users_fn,
            save_users_fn=save_users_fn,
            mem_log_getter=mem_log_getter,
            card_store_factory=card_store_factory,
            build_entitlements_response_fn=build_entitlements_response_fn,
            current_admin_grant_record_fn=current_admin_grant_record_fn,
        )
    )


def include_app_routers(app: FastAPI, routers: AppRouters) -> None:
    for router in routers.domain:
        app.include_router(router)
    app.include_router(routers.admin.login)
    app.include_router(routers.admin.html)
    app.include_router(routers.admin.api)
