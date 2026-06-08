from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from .settings import KGSettings
from .user_store import CachedUserStore, normalize_users_payload


@dataclass(frozen=True)
class RuntimeUserState:
    user_store: CachedUserStore
    load_users: Callable[[], dict[str, dict[str, Any]]]
    save_users: Callable[[dict[str, dict[str, Any]]], None]
    normalize_users_payload: Callable[[dict[str, Any]], tuple[dict[str, Any], bool]]


def install_runtime_user_state(
    app: FastAPI,
    settings: KGSettings,
    *,
    default_subscription_payload_fn: Callable[[], dict[str, Any]],
) -> RuntimeUserState:
    def _normalize_users_payload_fn(users: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        from .secret_store import encrypt_value

        encrypt_fn = (lambda v: encrypt_value(v, settings.jwt_secret)) if settings.jwt_secret else None
        return normalize_users_payload(
            users,
            default_subscription_payload_fn,
            encrypt_fn=encrypt_fn,
        )

    user_store = CachedUserStore(settings.users_file, _normalize_users_payload_fn)

    def _load_users_fn() -> dict[str, dict[str, Any]]:
        return user_store.load()

    def _save_users_fn(users: dict[str, dict[str, Any]]) -> None:
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
