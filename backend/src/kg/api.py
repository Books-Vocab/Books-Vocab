"""FastAPI server for Knowledge Graph — lightweight bridge for BooksBrowser.

Wraps existing KG modules (cards, enrich, link, difficulty, mochi sync)
behind REST endpoints and background pipeline orchestration.

Usage:
    uvicorn kg.api:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

import collections


class _MemoryLogHandler(logging.Handler):
    """Ring-buffer log handler for the admin dashboard."""
    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self._buf: collections.deque = collections.deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from datetime import datetime as _dt
            self._buf.append({
                "ts": _dt.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "name": record.name,
                "msg": record.getMessage(),
            })
        except Exception:
            pass  # handler must never crash the application

    def get(self, n: int = 200, level: str | None = None) -> list[dict]:
        rows = list(self._buf)
        if level:
            rows = [r for r in rows if r["level"] == level]
        return rows[-n:]

_mem_log = _MemoryLogHandler(maxlen=1000)
_mem_log.setLevel(logging.DEBUG)

def _attach_memory_log_handler(logger_name: str) -> None:
    target = logging.getLogger(logger_name)
    if not any(h is _mem_log for h in target.handlers):
        target.addHandler(_mem_log)

_attach_memory_log_handler("")  # root logger
_attach_memory_log_handler("uvicorn")
_attach_memory_log_handler("uvicorn.error")
_attach_memory_log_handler("uvicorn.access")

from .admin_wiring import create_admin_handlers
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
from .route_registration import register_routes
from .runtime_state import (
    runtime_notifications_file,
    runtime_settings,
    runtime_users_file,
    runtime_users_lock_file,
)
from .service_factories import (
    create_card_store,
    create_daily_stats_store,
    create_embedding_store,
    create_gemini_client,
    create_graph_store,
)
from .rate_limit import api_limiter, translate_limiter
from .settings import KGSettings, load_settings
from .translate_handlers import (
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
    load_users_from,
    normalize_users_payload,
    parse_datetime,
    save_users_to,
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

load_dotenv()

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
# Data directory & Multi-User
# ---------------------------------------------------------------------------
DATA_DIR = Path()
USERS_FILE = Path()
USERS_LOCK_FILE = Path()
APP_STORE_NOTIFICATIONS_FILE = Path()

# JWT / auth / admin configuration
JWT_SECRET = ""
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = 60 * 24 * 30  # 30 days
GOOGLE_CLIENT_ID = ""
APPLE_BUNDLE_ID = "com.Max0228.BooksBrowser"
APP_STORE_ALLOW_UNSIGNED_SYNC = False
APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS = False
ADMIN_TOKEN = ""


def configure_runtime(settings: KGSettings) -> KGSettings:
    """Apply settings to the legacy module-level runtime surface."""
    global DATA_DIR
    global USERS_FILE
    global USERS_LOCK_FILE
    global APP_STORE_NOTIFICATIONS_FILE
    global JWT_SECRET
    global JWT_ALGORITHM
    global JWT_EXPIRY_MINUTES
    global GOOGLE_CLIENT_ID
    global APPLE_BUNDLE_ID
    global APP_STORE_ALLOW_UNSIGNED_SYNC
    global APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS
    global ADMIN_TOKEN

    DATA_DIR = settings.data_dir
    USERS_FILE = settings.users_file
    USERS_LOCK_FILE = settings.users_lock_file
    APP_STORE_NOTIFICATIONS_FILE = settings.app_store_notifications_file
    JWT_SECRET = settings.jwt_secret
    JWT_ALGORITHM = settings.jwt_algorithm
    JWT_EXPIRY_MINUTES = settings.jwt_expiry_minutes
    GOOGLE_CLIENT_ID = settings.google_client_id
    APPLE_BUNDLE_ID = settings.apple_bundle_id
    APP_STORE_ALLOW_UNSIGNED_SYNC = settings.app_store_allow_unsigned_sync
    APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS = settings.app_store_allow_unsigned_notifications
    ADMIN_TOKEN = settings.admin_token
    return settings


def _runtime_settings() -> KGSettings:
    """Read the current legacy runtime surface as a single settings object."""
    return runtime_settings(
        data_dir=DATA_DIR,
        jwt_secret=JWT_SECRET,
        jwt_algorithm=JWT_ALGORITHM,
        jwt_expiry_minutes=JWT_EXPIRY_MINUTES,
        google_client_id=GOOGLE_CLIENT_ID,
        apple_bundle_id=APPLE_BUNDLE_ID,
        app_store_allow_unsigned_sync=APP_STORE_ALLOW_UNSIGNED_SYNC,
        app_store_allow_unsigned_notifications=APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS,
        admin_token=ADMIN_TOKEN,
    )


def _runtime_users_file() -> Path:
    return runtime_users_file(explicit_users_file=USERS_FILE, settings=_runtime_settings())


def _runtime_users_lock_file() -> Path:
    return runtime_users_lock_file(explicit_users_lock_file=USERS_LOCK_FILE, settings=_runtime_settings())


def _runtime_notifications_file() -> Path:
    return runtime_notifications_file(
        explicit_notifications_file=APP_STORE_NOTIFICATIONS_FILE,
        settings=_runtime_settings(),
    )


def create_app(settings: KGSettings | None = None) -> FastAPI:
    runtime_settings = configure_runtime(settings or load_settings())

    app = FastAPI(title="Knowledge Graph API", version="0.1.0")
    app.state.kg_settings = runtime_settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://wordnexus.lol",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def limit_request_body(request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 10 * 1024 * 1024:  # 10MB
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)

    _RATE_LIMIT_EXEMPT = {
        "/docs",
        "/openapi.json",
        "/privacy",
        "/support",
        "/terms",
        "/guide",
        "/api/billing/app-store/notifications",
        "/admin",
    }

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _RATE_LIMIT_EXEMPT):
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        key = auth[-16:] if len(auth) > 16 else (request.client.host if request.client else "unknown")

        limiter = translate_limiter if "/api/translate" in path else api_limiter

        if not await limiter.is_allowed(key):
            return JSONResponse(
                {"detail": "Too many requests"},
                status_code=429,
                headers={"Retry-After": str(limiter.window_seconds)},
            )
        return await call_next(request)

    admin_handlers = create_admin_handlers(
        runtime_settings_fn=_runtime_settings,
        runtime_users_lock_file_fn=_runtime_users_lock_file,
        load_users_fn=_load_users,
        save_users_fn=_save_users,
        mem_log_getter=_mem_log.get,
        card_store_factory=_card_store,
        build_entitlements_response_fn=_build_entitlements_response,
        current_admin_grant_record_fn=_current_admin_grant_record,
    )

    register_routes(
        app,
        get_privacy_policy=get_privacy_policy,
        get_support=get_support,
        get_terms=get_terms,
        get_guide=get_guide,
        get_user_config=get_user_config,
        get_user_entitlements=get_user_entitlements,
        get_user_quota=get_user_quota,
        update_user_config=update_user_config,
        delete_user_account=delete_user_account,
        health=health,
        sync_app_store_subscription=sync_app_store_subscription,
        app_store_notifications=app_store_notifications,
        reconcile_app_store_subscription=reconcile_app_store_subscription,
        list_vocab=list_vocab,
        lookup_word=lookup_word,
        archive_word=archive_word,
        delete_word=delete_word,
        get_graph_links=get_graph_links,
        add_vocab=add_vocab,
        push_review=push_review,
        push_daily_stats=push_daily_stats,
        pull_daily_stats=pull_daily_stats,
        run_pipeline=run_pipeline,
        translate_quick=translate_quick,
        translate_phrase=translate_phrase,
        translate_explain=translate_explain,
        auth_verify=auth_verify,
        **admin_handlers,
    )
    return app

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


def _load_users() -> dict[str, dict[str, Any]]:
    return load_users_from(_runtime_users_file(), _normalize_users_payload)

def _save_users(users: dict[str, dict[str, Any]]) -> None:
    save_users_to(_runtime_users_file(), users, _normalize_users_payload)

load_users = _load_users
save_users = _save_users


def _normalize_users_payload(users: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    from .secret_store import encrypt_value
    jwt_secret = _runtime_settings().jwt_secret
    encrypt_fn = (lambda v: encrypt_value(v, jwt_secret)) if jwt_secret else None
    return normalize_users_payload(users, _default_subscription_payload, encrypt_fn=encrypt_fn)

def _parse_datetime(raw: Any) -> datetime | None:
    return parse_datetime(raw)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict[str, Any]:
    return resolve_current_user(
        credentials.credentials,
        settings=_runtime_settings(),
        load_users=_load_users,
        parse_datetime=_parse_datetime,
    )


def _card_store(user_dir: Path):
    return create_card_store(user_dir)


def _daily_stats_store(user_dir: Path):
    return create_daily_stats_store(user_dir)


def _graph_store(user_dir: Path) -> GraphStore:
    return create_graph_store(user_dir)


def _gemini_client():
    return create_gemini_client()


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


def _append_app_store_event(payload: dict[str, Any]) -> None:
    append_app_store_event(_runtime_notifications_file(), payload)


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


def _decode_signed_transaction_info(signed_transaction_info: str) -> dict[str, Any]:
    return decode_signed_transaction_info(
        signed_transaction_info,
        bundle_id=_runtime_settings().apple_bundle_id,
        parse_datetime_fn=_parse_datetime,
        verify_signed_jws=verify_and_decode_signed_jws,
    )


def _decode_notification_payload(req: AppStoreNotificationRequest) -> tuple[dict[str, Any], dict[str, Any] | None]:
    settings = _runtime_settings()
    return decode_notification_payload(
        req,
        bundle_id=settings.apple_bundle_id,
        allow_unsigned_notifications=settings.app_store_allow_unsigned_notifications,
        parse_datetime_fn=_parse_datetime,
        verify_signed_jws=verify_and_decode_signed_jws,
    )


# ---------------------------------------------------------------------------
# GET /api/user/config
# ---------------------------------------------------------------------------
def get_user_config(user: dict = Depends(get_current_user)):
    """Get user configuration."""
    return get_user_config_response(user, jwt_secret=_runtime_settings().jwt_secret)


# ---------------------------------------------------------------------------
# GET /api/user/entitlements
# ---------------------------------------------------------------------------
def get_user_entitlements(user: dict = Depends(get_current_user)):
    """Get the current user's subscription entitlement snapshot."""
    return get_user_entitlements_response(
        user,
        build_entitlements_response=_build_entitlements_response,
    )


# ---------------------------------------------------------------------------
# POST /api/billing/app-store/sync
# ---------------------------------------------------------------------------
def sync_app_store_subscription(req: AppStoreSyncRequest, user: dict = Depends(get_current_user)):
    """Persist the latest App Store subscription snapshot for the current user."""
    settings = _runtime_settings()
    return sync_app_store_subscription_response(
        req,
        user,
        allow_unsigned_sync=settings.app_store_allow_unsigned_sync,
        users_lock_file=_runtime_users_lock_file(),
        load_users=_load_users,
        save_users=_save_users,
        decode_signed_transaction_info=_decode_signed_transaction_info,
        write_subscription_snapshot=_write_subscription_snapshot,
        build_entitlements_response=_build_entitlements_response,
    )


# ---------------------------------------------------------------------------
# POST /api/billing/app-store/notifications
# ---------------------------------------------------------------------------
def app_store_notifications(req: AppStoreNotificationRequest):
    """Receive App Store Server Notifications and persist/update subscription state."""
    _runtime_settings()
    return app_store_notifications_response(
        req,
        users_lock_file=_runtime_users_lock_file(),
        load_users=_load_users,
        save_users=_save_users,
        decode_notification_payload=_decode_notification_payload,
        append_app_store_event=_append_app_store_event,
        resolve_user_id_from_subscription_index=_resolve_user_id_from_subscription_index,
        write_subscription_snapshot=_write_subscription_snapshot,
        build_entitlements_response=_build_entitlements_response,
    )


# ---------------------------------------------------------------------------
# POST /api/billing/app-store/reconcile
# ---------------------------------------------------------------------------
async def reconcile_app_store_subscription(req: AppStoreReconcileRequest, user: dict = Depends(get_current_user)):
    """Fetch transaction state from Apple's App Store Server API and persist it."""
    settings = _runtime_settings()
    return await reconcile_app_store_subscription_response(
        req,
        user,
        apple_bundle_id=settings.apple_bundle_id,
        users_lock_file=_runtime_users_lock_file(),
        load_users=_load_users,
        save_users=_save_users,
        fetch_transaction_info=fetch_transaction_info,
        decode_signed_transaction_info=_decode_signed_transaction_info,
        resolve_user_id_from_subscription_index=_resolve_user_id_from_subscription_index,
        write_subscription_snapshot=_write_subscription_snapshot,
        build_entitlements_response=_build_entitlements_response,
    )


# ---------------------------------------------------------------------------
# PUT /api/user/config
# ---------------------------------------------------------------------------
def update_user_config(req: UserConfigRequest, user: dict = Depends(get_current_user)):
    """Update user configuration."""
    settings = _runtime_settings()
    return update_user_config_response(
        req,
        user,
        users_lock_file=_runtime_users_lock_file(),
        load_users=_load_users,
        save_users=_save_users,
        jwt_secret=settings.jwt_secret,
    )


# ---------------------------------------------------------------------------
# DELETE /api/user/account
# ---------------------------------------------------------------------------
def delete_user_account(user: dict = Depends(get_current_user)):
    """Permanently delete the current account and all related user data."""
    settings = _runtime_settings()
    return delete_user_account_response(
        user,
        users_lock_file=_runtime_users_lock_file(),
        load_users=_load_users,
        save_users=_save_users,
        collect_account_ids_for_deletion=_collect_account_ids_for_deletion,
        data_dir=settings.data_dir,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------
def health(user: dict = Depends(get_current_user)):
    """Server health + stats per user."""
    return health_response(
        user,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
    )


# ---------------------------------------------------------------------------
# GET /api/vocab
# ---------------------------------------------------------------------------
def list_vocab(since: str | None = None, user: dict = Depends(get_current_user)):
    """List all cards for the current user, optionally filtered by a since timestamp."""
    return list_vocab_response(
        since=since,
        user=user,
        require_pro_access=_require_pro_access,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        card_response_builder=lambda card, graph_obj, cards_by_id: _card_response(card, graph_obj, cards_by_id),
    )


# ---------------------------------------------------------------------------
# GET /api/vocab/{word}
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
# PATCH /api/vocab/{word}/archive  — Archive or unarchive a word
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
# DELETE /api/vocab/{word}
# ---------------------------------------------------------------------------
def delete_word(word: str, user: dict = Depends(get_current_user)):
    """Delete a word from the current user's card store."""
    return delete_word_response(
        word,
        user,
        require_pro_access=_require_pro_access,
        card_store_factory=_card_store,
    )

# ---------------------------------------------------------------------------
# GET /api/graph/links
# ---------------------------------------------------------------------------
def get_graph_links(user: dict = Depends(get_current_user)):
    """Get all active graph connections for the user."""
    return get_graph_links_response(
        user,
        require_pro_access=_require_pro_access,
        graph_store_factory=_graph_store,
    )

# ---------------------------------------------------------------------------
# POST /api/vocab  — Batch add from BooksBrowser
# ---------------------------------------------------------------------------
def add_vocab(entries: list[VocabEntry], user: dict = Depends(get_current_user)):
    """Add vocabulary entries from BooksBrowser → KG Cards."""
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
# PATCH /api/vocab/review  — Push review state from client
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
# PATCH /api/vocab/daily-stats  — Push daily review stats from client
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
# GET /api/vocab/daily-stats  — Pull daily review stats
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
# POST /api/pipeline  — Run full pipeline in background
# ---------------------------------------------------------------------------
async def _run_pipeline_background(user: dict):
    await run_pipeline_background(
        user,
        get_user_lock_fn=get_user_lock,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        embedding_store_factory=_embedding_store,
        gemini_client_factory=_gemini_client,
        logger=logger,
        link_kind_enum=LinkKind,
        jwt_secret=_runtime_settings().jwt_secret,
    )


async def run_pipeline(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """Run enrich → link → difficulty → sync pipeline for the user in the background.

    Returns immediately with accepted status.
    """
    return queue_pipeline_response(
        background_tasks,
        user,
        require_pro_access=_require_pro_access,
        run_pipeline_background_fn=_run_pipeline_background,
    )

# ---------------------------------------------------------------------------
# POST /api/translate/quick & /api/translate/explain
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
    """共用 quota 檢查 + header 注入邏輯。"""
    from .quota_service import check_quota, get_quota_state
    pro = _is_pro(user)
    quota = check_quota(user["id"], call_type, is_pro=pro)
    if quota["exceeded"]:
        raise HTTPException(
            429,
            detail={"code": "quota_exhausted", "reset_seconds": quota["reset_seconds"]},
            headers={"X-Quota-Fraction": "0.0", "X-Quota-Reset": str(quota["reset_seconds"])},
        )
    result = handler()
    state = get_quota_state(user["id"], is_pro=pro)
    if response is not None:
        response.headers["X-Quota-Fraction"] = str(state["fraction"])
        response.headers["X-Quota-Reset"] = str(state["reset_seconds"])
    return result

def translate_quick(req: TranslateRequest, user: dict = Depends(get_current_user), response: Response = None):
    """Perform a quick UI translation via Gemini API (proxy)."""
    return _with_quota_check(user, "translate_quick", response, lambda: translate_quick_response(
        req, user, require_pro_access=_require_pro_access, gemini_client_factory=_gemini_client, logger=logger,
    ))

def translate_phrase(req: TranslateRequest, user: dict = Depends(get_current_user), response: Response = None):
    """Translate a multi-word phrase or expression. Returns translation only."""
    return _with_quota_check(user, "translate_phrase", response, lambda: translate_phrase_response(
        req, user, require_pro_access=_require_pro_access, gemini_client_factory=_gemini_client,
    ))

def translate_explain(req: TranslateRequest, user: dict = Depends(get_current_user), response: Response = None):
    """Generate a 1-2 sentence context explanation via Gemini API (proxy)."""
    return _with_quota_check(user, "translate_explain", response, lambda: translate_explain_response(
        req, user, require_pro_access=_require_pro_access, gemini_client_factory=_gemini_client,
    ))


# ---------------------------------------------------------------------------
# GET /api/user/quota
# ---------------------------------------------------------------------------
def get_user_quota(user: dict = Depends(get_current_user)):
    """Return quota fraction for the current user."""
    from .quota_service import get_quota_state
    return get_quota_state(user["id"], is_pro=_is_pro(user))


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _create_jwt_token(user_id: str, provider: str) -> str:
    settings = _runtime_settings()
    return create_jwt_token(
        user_id,
        provider,
        jwt_secret=settings.jwt_secret,
        jwt_algorithm=settings.jwt_algorithm,
        jwt_expiry_minutes=settings.jwt_expiry_minutes,
    )


def _resolve_and_link_user(provider_user_id: str, provider: str, email: str | None = None) -> str:
    return resolve_and_link_user(
        provider_user_id,
        provider,
        users_lock_file=str(_runtime_users_lock_file()),
        load_users_fn=_load_users,
        save_users_fn=_save_users,
        email=email,
    )


async def auth_verify(req: AuthVerifyRequest):
    """Verify Google/Apple token and return JWT access token.

    Request:
        {
            "provider": "google" | "apple",
            "token": "<provider-issued-token>",
            "email": "<optional-email>"
        }

    Response:
        {
            "access_token": "<jwt>",
            "token_type": "bearer",
            "user_id": "<canonical-user-id>",
            "expires_in": 900
        }
    """
    settings = _runtime_settings()
    return await auth_verify_response(
        req,
        google_client_id=settings.google_client_id,
        apple_bundle_id=settings.apple_bundle_id,
        jwt_expiry_minutes=settings.jwt_expiry_minutes,
        verify_google_token=verify_google_token,
        verify_apple_token=verify_apple_token,
        resolve_and_link_user=_resolve_and_link_user,
        create_jwt_token=_create_jwt_token,
    )


app = create_app()
