"""Endpoint definitions, factory wrappers, and auth infrastructure.

Extracted from api.py to keep it focused on app factory + middleware.
"""

from __future__ import annotations

import asyncio
import collections
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .api_models import (
    AppStoreNotificationRequest,
    AppStoreReconcileRequest,
    AppStoreSyncRequest,
    ArchiveWordRequest,
    AuthVerifyRequest,
    CardLinkSummaryResponse,
    DailyReviewStatsPushRequest,
    EntitlementsResponse,
    ReviewStatePushRequest,
    TranslateRequest,
    UserConfigRequest,
    VocabEntry,
)
from .app_store import (
    fetch_transaction_info,
    verify_and_decode_signed_jws,
)
from .apple_auth import verify_apple_token
from .auth_handlers import auth_verify_response
from .auth_service import create_jwt_token, resolve_and_link_user
from .billing import (
    append_app_store_event,
    build_entitlements_response,
    current_admin_grant_record,
    current_subscription_record,
    decode_notification_payload,
    decode_signed_transaction_info,
    default_subscription_payload,
    notification_status,
    require_pro_access,
    resolve_user_id_from_subscription_index,
    write_subscription_snapshot,
)
from .billing_handlers import (
    app_store_notifications_response,
    reconcile_app_store_subscription_response,
    sync_app_store_subscription_response,
)
from .difficulty import get_tier
from .google_auth import verify_google_token
from .graph import LINK_LABELS, GraphStore, LinkKind
from .pipeline_handlers import queue_pipeline_response
from .pipeline_service import run_pipeline_background
from .service_factories import (
    create_async_gemini_client,
    create_card_store,
    create_daily_stats_store,
    create_embedding_store,
    create_gemini_client,
    create_graph_store,
)
from .settings import KGSettings
from .translate_handlers import (
    async_translate_explain_response,
    async_translate_phrase_response,
    async_translate_quick_response,
    translate_explain_response,
    translate_phrase_response,
    translate_quick_response,
)
from .user_context import resolve_current_user
from .user_handlers import (
    delete_user_account_response,
    get_user_config_response,
    get_user_entitlements_response,
    health_response,
    update_user_config_response,
)
from .user_store import (
    collect_account_ids_for_deletion,
    parse_datetime,
)
from .vocab_handlers import (
    add_vocab_response,
    archive_word_response,
    delete_word_response,
    get_graph_links_response,
    list_vocab_response,
    lookup_word_response,
    pull_daily_stats_response,
    push_daily_stats_response,
    push_review_response,
)
from .vocab_service import (
    build_links_by_kind,
    card_response,
)

logger = logging.getLogger("kg.api")

# ---------------------------------------------------------------------------
# Static page helpers
# ---------------------------------------------------------------------------

def get_privacy_policy():
    """Serve the static privacy policy HTML."""
    privacy_path = Path(__file__).resolve().parent.parent.parent / "privacy.html"
    if not privacy_path.exists():
        return HTMLResponse("<h1>Privacy Policy Not Found</h1>", status_code=404)
    return FileResponse(privacy_path)


def get_support():
    """Serve the support page HTML."""
    support_path = Path(__file__).resolve().parent.parent.parent / "support.html"
    if not support_path.exists():
        return HTMLResponse("<h1>Support Page Not Found</h1>", status_code=404)
    return FileResponse(support_path)


def get_terms():
    """Serve the terms of service HTML."""
    terms_path = Path(__file__).resolve().parent.parent.parent / "terms.html"
    if not terms_path.exists():
        return HTMLResponse("<h1>Terms of Service Not Found</h1>", status_code=404)
    return FileResponse(terms_path)


def get_guide():
    """Serve the guide HTML."""
    guide_path = Path(__file__).resolve().parent.parent.parent / "guide.html"
    if not guide_path.exists():
        return HTMLResponse("<h1>Guide Not Found</h1>", status_code=404)
    return FileResponse(guide_path)


# ---------------------------------------------------------------------------
# Auth infrastructure
# ---------------------------------------------------------------------------

def _get_settings(request: Request) -> KGSettings:
    return request.app.state.kg_settings


security = HTTPBearer()

# Global lock per user to prevent concurrent pipeline executions
_USER_LOCKS: collections.OrderedDict[str, asyncio.Lock] = collections.OrderedDict()
_MAX_USER_LOCKS = 500
_USER_LOCKS_MUTEX: asyncio.Lock | None = None  # initialized lazily after event loop starts


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


def _graph_store(user_dir: Path) -> GraphStore:
    return create_graph_store(user_dir)


def _gemini_client():
    return create_gemini_client()


def _gemini_async_client():
    return create_async_gemini_client()


def _embedding_store(user_dir: Path, user_id: str | None = None):
    return create_embedding_store(user_dir, gemini_client_factory=_gemini_client, user_id=user_id)


def _build_links_by_kind(
    card_id: str,
    graph: GraphStore,
    cards_by_id: dict[str, Any],
) -> dict[str, list[CardLinkSummaryResponse]]:
    return build_links_by_kind(
        card_id,
        graph=graph,
        cards_by_id=cards_by_id,
        link_kinds=list(LinkKind),
        link_labels=LINK_LABELS,
    )


def _card_response(
    card,
    graph: GraphStore,
    cards_by_id: dict[str, Any],
):
    return card_response(
        card,
        graph=graph,
        cards_by_id=cards_by_id,
        tier_getter=get_tier,
        link_kinds=list(LinkKind),
        link_labels=LINK_LABELS,
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


def _resolve_user_id_from_subscription_index(users: dict[str, Any], original_transaction_id: str | None, transaction_id: str | None) -> str | None:
    return resolve_user_id_from_subscription_index(users, original_transaction_id, transaction_id)


def _write_subscription_snapshot(
    users: dict[str, Any],
    user_id: str,
    *,
    product_id: str,
    status: str,
    is_trial: bool,
    expires_at: str | None,
    will_renew: bool,
    environment: str,
    transaction_id: str | None,
    original_transaction_id: str | None,
    price_display: str | None,
    source: str,
) -> dict[str, Any]:
    return write_subscription_snapshot(
        users,
        user_id,
        product_id=product_id,
        status=status,
        is_trial=is_trial,
        expires_at=expires_at,
        will_renew=will_renew,
        environment=environment,
        transaction_id=transaction_id,
        original_transaction_id=original_transaction_id,
        price_display=price_display,
        source=source,
    )


def _notification_status(notification_type: str | None, subtype: str | None) -> str:
    return notification_status(notification_type, subtype)


# ---------------------------------------------------------------------------
# Endpoint: GET /api/user/config
# ---------------------------------------------------------------------------
def get_user_config(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Get user configuration."""
    settings = request.app.state.kg_settings
    return get_user_config_response(user, jwt_secret=settings.jwt_secret)


# ---------------------------------------------------------------------------
# Endpoint: GET /api/user/entitlements
# ---------------------------------------------------------------------------
def get_user_entitlements(user: dict = Depends(get_current_user)):
    """Get the current user's subscription entitlement snapshot."""
    return get_user_entitlements_response(
        user,
        build_entitlements_response=_build_entitlements_response,
    )


# ---------------------------------------------------------------------------
# Endpoint: POST /api/billing/app-store/sync
# ---------------------------------------------------------------------------
def sync_app_store_subscription(
    req: AppStoreSyncRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Persist the latest App Store subscription snapshot for the current user."""
    settings = request.app.state.kg_settings

    def _decode_signed_txn(signed_transaction_info: str) -> dict[str, Any]:
        return decode_signed_transaction_info(
            signed_transaction_info,
            bundle_id=settings.apple_bundle_id,
            parse_datetime_fn=_parse_datetime,
            verify_signed_jws=verify_and_decode_signed_jws,
        )

    return sync_app_store_subscription_response(
        req,
        user,
        allow_unsigned_sync=settings.app_store_allow_unsigned_sync,
        users_lock_file=settings.users_lock_file,
        load_users=request.app.state.load_users,
        save_users=request.app.state.save_users,
        decode_signed_transaction_info=_decode_signed_txn,
        write_subscription_snapshot=_write_subscription_snapshot,
        build_entitlements_response=_build_entitlements_response,
    )


# ---------------------------------------------------------------------------
# Endpoint: POST /api/billing/app-store/notifications
# ---------------------------------------------------------------------------
def app_store_notifications(req: AppStoreNotificationRequest, request: Request):
    """Receive App Store Server Notifications and persist/update subscription state."""
    settings = request.app.state.kg_settings

    def _decode_notif_payload(r: AppStoreNotificationRequest) -> tuple[dict[str, Any], dict[str, Any] | None]:
        return decode_notification_payload(
            r,
            bundle_id=settings.apple_bundle_id,
            allow_unsigned_notifications=settings.app_store_allow_unsigned_notifications,
            parse_datetime_fn=_parse_datetime,
            verify_signed_jws=verify_and_decode_signed_jws,
        )

    def _append_event(payload: dict[str, Any]) -> None:
        append_app_store_event(settings.app_store_notifications_file, payload)

    return app_store_notifications_response(
        req,
        users_lock_file=settings.users_lock_file,
        load_users=request.app.state.load_users,
        save_users=request.app.state.save_users,
        decode_notification_payload=_decode_notif_payload,
        append_app_store_event=_append_event,
        resolve_user_id_from_subscription_index=_resolve_user_id_from_subscription_index,
        write_subscription_snapshot=_write_subscription_snapshot,
        build_entitlements_response=_build_entitlements_response,
    )


# ---------------------------------------------------------------------------
# Endpoint: POST /api/billing/app-store/reconcile
# ---------------------------------------------------------------------------
async def reconcile_app_store_subscription(
    req: AppStoreReconcileRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Fetch transaction state from Apple's App Store Server API and persist it."""
    settings = request.app.state.kg_settings

    def _decode_signed_txn(signed_transaction_info: str) -> dict[str, Any]:
        return decode_signed_transaction_info(
            signed_transaction_info,
            bundle_id=settings.apple_bundle_id,
            parse_datetime_fn=_parse_datetime,
            verify_signed_jws=verify_and_decode_signed_jws,
        )

    return await reconcile_app_store_subscription_response(
        req,
        user,
        apple_bundle_id=settings.apple_bundle_id,
        users_lock_file=settings.users_lock_file,
        load_users=request.app.state.load_users,
        save_users=request.app.state.save_users,
        fetch_transaction_info=fetch_transaction_info,
        decode_signed_transaction_info=_decode_signed_txn,
        resolve_user_id_from_subscription_index=_resolve_user_id_from_subscription_index,
        write_subscription_snapshot=_write_subscription_snapshot,
        build_entitlements_response=_build_entitlements_response,
    )


# ---------------------------------------------------------------------------
# Endpoint: PUT /api/user/config
# ---------------------------------------------------------------------------
def update_user_config(
    req: UserConfigRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Update user configuration."""
    settings = request.app.state.kg_settings
    return update_user_config_response(
        req,
        user,
        users_lock_file=settings.users_lock_file,
        load_users=request.app.state.load_users,
        save_users=request.app.state.save_users,
        jwt_secret=settings.jwt_secret,
    )


# ---------------------------------------------------------------------------
# Endpoint: DELETE /api/user/account
# ---------------------------------------------------------------------------
def delete_user_account(request: Request, user: dict = Depends(get_current_user)):
    """Permanently delete the current account and all related user data."""
    settings = request.app.state.kg_settings
    return delete_user_account_response(
        user,
        users_lock_file=settings.users_lock_file,
        load_users=request.app.state.load_users,
        save_users=request.app.state.save_users,
        collect_account_ids_for_deletion=_collect_account_ids_for_deletion,
        data_dir=settings.data_dir,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# Endpoint: GET /api/health
# ---------------------------------------------------------------------------
def health(user: dict = Depends(get_current_user)):
    """Server health + stats per user."""
    return health_response(
        user,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
    )


# ---------------------------------------------------------------------------
# Endpoint: GET /api/vocab
# ---------------------------------------------------------------------------
def list_vocab(since: str | None = None, limit: int = 5000, user: dict = Depends(get_current_user)):
    """List all cards for the current user, optionally filtered by a since timestamp."""
    return list_vocab_response(
        since=since,
        limit=limit,
        user=user,
        require_pro_access=_require_pro_access,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        card_response_builder=lambda card, graph_obj, cards_by_id: _card_response(card, graph_obj, cards_by_id),
    )


# ---------------------------------------------------------------------------
# Endpoint: GET /api/vocab/{word}
# ---------------------------------------------------------------------------
def lookup_word(word: str, user: dict = Depends(get_current_user)):
    """Lookup a word in the current user's card store."""
    return lookup_word_response(
        word,
        user,
        require_pro_access=_require_pro_access,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        card_response_builder=lambda card, graph_obj, cards_by_id: _card_response(card, graph_obj, cards_by_id),
    )


# ---------------------------------------------------------------------------
# Endpoint: PATCH /api/vocab/{word}/archive
# ---------------------------------------------------------------------------
def archive_word(word: str, req: ArchiveWordRequest, user: dict = Depends(get_current_user)):
    """Set or clear the archived flag on a card."""
    return archive_word_response(
        word,
        req,
        user,
        require_pro_access=_require_pro_access,
        card_store_factory=_card_store,
    )


# ---------------------------------------------------------------------------
# Endpoint: DELETE /api/vocab/{word}
# ---------------------------------------------------------------------------
def delete_word(word: str, user: dict = Depends(get_current_user)):
    """Delete a word from the current user's card store."""
    return delete_word_response(
        word,
        user,
        require_pro_access=_require_pro_access,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
    )


# ---------------------------------------------------------------------------
# Endpoint: GET /api/graph/links
# ---------------------------------------------------------------------------
def get_graph_links(user: dict = Depends(get_current_user)):
    """Get all active graph connections for the user."""
    return get_graph_links_response(
        user,
        require_pro_access=_require_pro_access,
        graph_store_factory=_graph_store,
    )


# ---------------------------------------------------------------------------
# Endpoint: POST /api/vocab
# ---------------------------------------------------------------------------
def add_vocab(entries: list[VocabEntry], user: dict = Depends(get_current_user)):
    """Add vocabulary entries from BooksBrowser -> KG Cards."""
    return add_vocab_response(
        entries,
        user,
        require_pro_access=_require_pro_access,
        card_store_factory=_card_store,
        embedding_store_factory=_embedding_store,
        graph_store_factory=_graph_store,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# Endpoint: PATCH /api/vocab/review
# ---------------------------------------------------------------------------
def push_review(req: ReviewStatePushRequest, user: dict = Depends(get_current_user)):
    """Merge client-side spaced repetition state into server cards."""
    return push_review_response(
        req,
        user,
        require_pro_access=_require_pro_access,
        card_store_factory=_card_store,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# Endpoint: PATCH /api/vocab/daily-stats
# ---------------------------------------------------------------------------
def push_daily_stats(req: DailyReviewStatsPushRequest, user: dict = Depends(get_current_user)):
    """Merge client daily review stats into server."""
    return push_daily_stats_response(
        req,
        user,
        require_pro_access=_require_pro_access,
        daily_stats_store_factory=_daily_stats_store,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# Endpoint: GET /api/vocab/daily-stats
# ---------------------------------------------------------------------------
def pull_daily_stats(since: str | None = None, user: dict = Depends(get_current_user)):
    """Return daily review stats, optionally filtered by since day_key."""
    return pull_daily_stats_response(
        since,
        user,
        require_pro_access=_require_pro_access,
        daily_stats_store_factory=_daily_stats_store,
    )


# ---------------------------------------------------------------------------
# Endpoint: POST /api/pipeline
# ---------------------------------------------------------------------------
async def _run_pipeline_background(user: dict, *, settings: KGSettings):
    await run_pipeline_background(
        user,
        get_user_lock_fn=get_user_lock,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        embedding_store_factory=_embedding_store,
        gemini_client_factory=_gemini_client,
        logger=logger,
        link_kind_enum=LinkKind,
        jwt_secret=settings.jwt_secret,
    )


async def run_pipeline(
    background_tasks: BackgroundTasks,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Run enrich -> link -> difficulty -> sync pipeline for the user in the background."""
    settings = request.app.state.kg_settings

    async def _bg(u: dict) -> None:
        await _run_pipeline_background(u, settings=settings)

    return queue_pipeline_response(
        background_tasks,
        user,
        require_pro_access=_require_pro_access,
        run_pipeline_background_fn=_bg,
    )


# ---------------------------------------------------------------------------
# Translate endpoints + quota
# ---------------------------------------------------------------------------
def _is_pro(user: dict) -> bool:
    from .billing import current_pro_entitlement_record
    return bool(current_pro_entitlement_record(user.get("record")).get("is_active"))


def _with_quota_check(
    user: dict,
    call_type: str,
    response: Response | None,
    handler: Callable[[], Any],
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


async def translate_quick(req: TranslateRequest, user: dict = Depends(get_current_user), response: Response = None):
    """Perform a quick UI translation via Gemini API (proxy)."""
    quota = _check_quota(user, "translate_quick", response)
    result = await async_translate_quick_response(
        req, user, require_pro_access=_require_pro_access, gemini_client_factory=_gemini_async_client, logger=logger,
    )
    _apply_quota_headers(response, quota)
    return result


async def translate_phrase(req: TranslateRequest, user: dict = Depends(get_current_user), response: Response = None):
    """Translate a multi-word phrase or expression. Returns translation only."""
    quota = _check_quota(user, "translate_phrase", response)
    result = await async_translate_phrase_response(
        req, user, require_pro_access=_require_pro_access, gemini_client_factory=_gemini_async_client,
    )
    _apply_quota_headers(response, quota)
    return result


async def translate_explain(req: TranslateRequest, user: dict = Depends(get_current_user), response: Response = None):
    """Generate a 1-2 sentence context explanation via Gemini API (proxy)."""
    quota = _check_quota(user, "translate_explain", response)
    result = await async_translate_explain_response(
        req, user, require_pro_access=_require_pro_access, gemini_client_factory=_gemini_async_client,
    )
    _apply_quota_headers(response, quota)
    return result


# ---------------------------------------------------------------------------
# Endpoint: GET /api/user/quota
# ---------------------------------------------------------------------------
def get_user_quota(user: dict = Depends(get_current_user)):
    """Return quota fraction for the current user."""
    from .quota_service import get_quota_state
    return get_quota_state(user["id"], is_pro=_is_pro(user))


# ---------------------------------------------------------------------------
# Authentication endpoint
# ---------------------------------------------------------------------------
def _create_jwt_token(user_id: str, provider: str, *, settings: KGSettings) -> str:
    return create_jwt_token(
        user_id,
        provider,
        jwt_secret=settings.jwt_secret,
        jwt_algorithm=settings.jwt_algorithm,
        jwt_expiry_minutes=settings.jwt_expiry_minutes,
    )


def _resolve_and_link_user(
    provider_user_id: str,
    provider: str,
    email: str | None = None,
    *,
    settings: KGSettings,
    load_users_fn: Callable,
    save_users_fn: Callable,
) -> str:
    return resolve_and_link_user(
        provider_user_id,
        provider,
        users_lock_file=str(settings.users_lock_file),
        load_users_fn=load_users_fn,
        save_users_fn=save_users_fn,
        email=email,
    )


async def auth_verify(req: AuthVerifyRequest, request: Request):
    """Verify Google/Apple token and return JWT access token."""
    settings = request.app.state.kg_settings
    load_users_fn = request.app.state.load_users
    save_users_fn = request.app.state.save_users

    def _jwt_token(user_id: str, provider: str) -> str:
        return _create_jwt_token(user_id, provider, settings=settings)

    def _link_user(provider_user_id: str, provider: str, email: str | None = None) -> str:
        return _resolve_and_link_user(
            provider_user_id, provider, email,
            settings=settings, load_users_fn=load_users_fn, save_users_fn=save_users_fn,
        )

    return await auth_verify_response(
        req,
        google_client_id=settings.google_client_id,
        apple_bundle_id=settings.apple_bundle_id,
        jwt_expiry_minutes=settings.jwt_expiry_minutes,
        verify_google_token=verify_google_token,
        verify_apple_token=verify_apple_token,
        resolve_and_link_user=_link_user,
        create_jwt_token=_jwt_token,
    )
