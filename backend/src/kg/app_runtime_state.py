from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import FastAPI

from .settings import KGSettings
from .types import SubscriptionRecord, UsersPayload
from .user_store import CachedUserStore, migrate_users_file, normalize_users_payload

UsersLoader = Callable[[], UsersPayload]
UsersSaver = Callable[[UsersPayload], None]
NormalizeUsersPayload = Callable[[UsersPayload], tuple[UsersPayload, bool]]
DefaultSubscriptionPayloadFn = Callable[[], SubscriptionRecord]


@dataclass(frozen=True)
class RuntimeUserState:
    user_store: CachedUserStore
    load_users: UsersLoader
    save_users: UsersSaver
    normalize_users_payload: NormalizeUsersPayload


@dataclass(frozen=True)
class RuntimeUserStateDependencies:
    app: FastAPI
    settings: KGSettings
    default_subscription_payload_fn: DefaultSubscriptionPayloadFn


def install_runtime_user_state_from_dependencies(
    *,
    dependencies: RuntimeUserStateDependencies,
) -> RuntimeUserState:
    app = dependencies.app
    settings = dependencies.settings
    default_subscription_payload_fn = dependencies.default_subscription_payload_fn

    def _normalize_users_payload_fn(users: UsersPayload) -> tuple[UsersPayload, bool]:
        from .secret_store import encrypt_value

        encrypt_fn = (lambda v: encrypt_value(v, settings.jwt_secret)) if settings.jwt_secret else None
        return normalize_users_payload(
            users,
            default_subscription_payload_fn,
            encrypt_fn=encrypt_fn,
        )

    migrate_users_file(
        settings.users_file,
        settings.users_lock_file,
        _normalize_users_payload_fn,
    )
    user_store = CachedUserStore(settings.users_file, _normalize_users_payload_fn)

    def _load_users_fn() -> UsersPayload:
        return user_store.load()

    def _save_users_fn(users: UsersPayload) -> None:
        user_store.save(users)

    bindings = RuntimeUserState(
        user_store=user_store,
        load_users=_load_users_fn,
        save_users=_save_users_fn,
        normalize_users_payload=_normalize_users_payload_fn,
    )
    app.state.user_store = bindings.user_store
    app.state.load_users = bindings.load_users
    app.state.save_users = bindings.save_users
    app.state.normalize_users_payload = bindings.normalize_users_payload
    return bindings


def install_runtime_user_state(
    app: FastAPI,
    settings: KGSettings,
    *,
    default_subscription_payload_fn: DefaultSubscriptionPayloadFn,
) -> RuntimeUserState:
    """Backward-compatible wrapper around :func:`install_runtime_user_state_from_dependencies`."""
    return install_runtime_user_state_from_dependencies(
        dependencies=RuntimeUserStateDependencies(
            app=app,
            settings=settings,
            default_subscription_payload_fn=default_subscription_payload_fn,
        )
    )
