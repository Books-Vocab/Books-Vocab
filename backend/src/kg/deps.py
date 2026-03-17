"""Shared dependencies for all routers.

Contains auth infrastructure, factory wrappers, and common helpers.
Routers import from here; api.py re-exports for backward compatibility.
"""

from __future__ import annotations

import asyncio
import collections
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .api_models import CardLinkSummaryResponse, EntitlementsResponse
from .billing import (
    build_entitlements_response,
    current_admin_grant_record,
    current_subscription_record,
    default_subscription_payload,
    notification_status,
    require_pro_access,
    resolve_user_id_from_subscription_index,
    write_subscription_snapshot,
)
from .difficulty import get_tier
from .graph import LINK_LABELS, GraphStore, LinkKind
from .service_factories import (
    create_async_gemini_client,
    create_card_store,
    create_daily_stats_store,
    create_embedding_store,
    create_gemini_client,
    create_graph_store,
    create_notebook_store,
)
from .settings import KGSettings
from .user_context import resolve_current_user
from .user_store import collect_account_ids_for_deletion, parse_datetime
from .vocab_service import build_links_by_kind, card_response

logger = logging.getLogger("kg.api")

# ---------------------------------------------------------------------------
# Auth infrastructure
# ---------------------------------------------------------------------------

def _get_settings(request: Request) -> KGSettings:
    return request.app.state.kg_settings


security = HTTPBearer()

_USER_LOCKS: collections.OrderedDict[str, asyncio.Lock] = collections.OrderedDict()
_MAX_USER_LOCKS = 500
_USER_LOCKS_MUTEX: asyncio.Lock | None = None


def _get_locks_mutex() -> asyncio.Lock:
    global _USER_LOCKS_MUTEX
    if _USER_LOCKS_MUTEX is None:
        _USER_LOCKS_MUTEX = asyncio.Lock()
    return _USER_LOCKS_MUTEX


async def get_user_lock(user_id: str) -> asyncio.Lock:
    async with _get_locks_mutex():
        if user_id in _USER_LOCKS:
            _USER_LOCKS.move_to_end(user_id)
            return _USER_LOCKS[user_id]
        lock = asyncio.Lock()
        _USER_LOCKS[user_id] = lock
        while len(_USER_LOCKS) > _MAX_USER_LOCKS:
            _USER_LOCKS.popitem(last=False)
        return lock


def _parse_datetime(raw: Any) -> datetime | None:
    return parse_datetime(raw)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict[str, Any]:
    settings = request.app.state.kg_settings
    load_users_fn = request.app.state.load_users
    return resolve_current_user(
        credentials.credentials,
        settings=settings,
        load_users=load_users_fn,
        parse_datetime=_parse_datetime,
    )


# ---------------------------------------------------------------------------
# Factory wrappers
# ---------------------------------------------------------------------------

def _card_store(user_dir: Path):
    return create_card_store(user_dir)


def _daily_stats_store(user_dir: Path):
    return create_daily_stats_store(user_dir)


def _graph_store(user_dir: Path, notebook_id: str = "default") -> GraphStore:
    return create_graph_store(user_dir, notebook_id=notebook_id)


def _notebook_store(user_dir: Path):
    return create_notebook_store(user_dir)


def _gemini_client():
    return create_gemini_client()


def _gemini_async_client():
    return create_async_gemini_client()


def _embedding_store(user_dir: Path, user_id: str | None = None, notebook_id: str = "default"):
    return create_embedding_store(user_dir, gemini_client_factory=_gemini_client, user_id=user_id, notebook_id=notebook_id)


def _build_links_by_kind(
    card_id: str, graph: GraphStore, cards_by_id: dict[str, Any],
) -> dict[str, list[CardLinkSummaryResponse]]:
    return build_links_by_kind(
        card_id, graph=graph, cards_by_id=cards_by_id,
        link_kinds=list(LinkKind), link_labels=LINK_LABELS,
    )


def _card_response(card, graph: GraphStore, cards_by_id: dict[str, Any]):
    return card_response(
        card, graph=graph, cards_by_id=cards_by_id,
        tier_getter=get_tier, link_kinds=list(LinkKind), link_labels=LINK_LABELS,
    )


def _collect_account_ids_for_deletion(users: dict[str, dict[str, Any]], user_id: str) -> tuple[str, list[str]]:
    return collect_account_ids_for_deletion(users, user_id)


def _default_subscription_payload() -> dict[str, Any]:
    return default_subscription_payload()


def _build_entitlements_response(user_record: dict[str, Any] | None) -> EntitlementsResponse:
    return build_entitlements_response(user_record)


def _current_admin_grant_record(user_record: dict[str, Any] | None) -> dict[str, Any]:
    return current_admin_grant_record(user_record)


def _current_subscription_record(user_record: dict[str, Any] | None) -> dict[str, Any]:
    return current_subscription_record(user_record)


def _require_pro_access(user: dict[str, Any], capability: str) -> None:
    require_pro_access(user, capability)


def _resolve_user_id_from_subscription_index(
    users: dict[str, Any], original_transaction_id: str | None, transaction_id: str | None,
) -> str | None:
    return resolve_user_id_from_subscription_index(users, original_transaction_id, transaction_id)


def _write_subscription_snapshot(
    users: dict[str, Any], user_id: str, *,
    product_id: str, status: str, is_trial: bool, expires_at: str | None,
    will_renew: bool, environment: str, transaction_id: str | None,
    original_transaction_id: str | None, price_display: str | None, source: str,
) -> dict[str, Any]:
    return write_subscription_snapshot(
        users, user_id, product_id=product_id, status=status,
        is_trial=is_trial, expires_at=expires_at, will_renew=will_renew,
        environment=environment, transaction_id=transaction_id,
        original_transaction_id=original_transaction_id,
        price_display=price_display, source=source,
    )


def _notification_status(notification_type: str | None, subtype: str | None) -> str:
    return notification_status(notification_type, subtype)


# ---------------------------------------------------------------------------
# Quota helpers
# ---------------------------------------------------------------------------

def _is_pro(user: dict) -> bool:
    from .billing import current_pro_entitlement_record
    return bool(current_pro_entitlement_record(user.get("record")).get("is_active"))


def _with_quota_check(
    user: dict, call_type: str, response: Response | None, handler: Callable[[], Any],
) -> Any:
    from .quota_service import check_and_get_quota
    pro = _is_pro(user)
    quota = check_and_get_quota(user["id"], call_type, is_pro=pro)
    if quota["exceeded"]:
        raise HTTPException(
            429,
            detail={"code": "quota_exhausted", "reset_seconds": quota["reset_seconds"]},
            headers={"X-Quota-Fraction": "0.0", "X-Quota-Reset": str(quota["reset_seconds"])},
        )
    result = handler()
    if response is not None:
        response.headers["X-Quota-Fraction"] = str(quota["fraction"])
        response.headers["X-Quota-Reset"] = str(quota["reset_seconds"])
    return result


def _check_quota(user: dict, call_type: str, response: Response | None) -> dict:
    from .quota_service import check_and_get_quota
    pro = _is_pro(user)
    quota = check_and_get_quota(user["id"], call_type, is_pro=pro)
    if quota["exceeded"]:
        raise HTTPException(
            429,
            detail={"code": "quota_exhausted", "reset_seconds": quota["reset_seconds"]},
            headers={"X-Quota-Fraction": "0.0", "X-Quota-Reset": str(quota["reset_seconds"])},
        )
    return quota


def _apply_quota_headers(response: Response | None, quota: dict) -> None:
    if response is not None:
        response.headers["X-Quota-Fraction"] = str(quota["fraction"])
        response.headers["X-Quota-Reset"] = str(quota["reset_seconds"])


# ---------------------------------------------------------------------------
# Auth helpers (used by auth router)
# ---------------------------------------------------------------------------

from .auth_service import create_jwt_token, resolve_and_link_user


def _create_jwt_token(user_id: str, provider: str, *, settings: KGSettings) -> str:
    return create_jwt_token(
        user_id, provider,
        jwt_secret=settings.jwt_secret, jwt_algorithm=settings.jwt_algorithm,
        jwt_expiry_minutes=settings.jwt_expiry_minutes,
    )


def _resolve_and_link_user(
    provider_user_id: str, provider: str, email: str | None = None, *,
    settings: KGSettings, load_users_fn: Callable, save_users_fn: Callable,
) -> str:
    return resolve_and_link_user(
        provider_user_id, provider,
        users_lock_file=str(settings.users_lock_file),
        load_users_fn=load_users_fn, save_users_fn=save_users_fn, email=email,
    )
