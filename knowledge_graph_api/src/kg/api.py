"""FastAPI server for Knowledge Graph — lightweight bridge for BooksBrowser.

Wraps existing KG modules (cards, enrich, link, difficulty, mochi sync)
behind REST endpoints with SSE streaming for pipeline progress.

Usage:
    uvicorn kg.api:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
import jwt
from filelock import FileLock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

import collections as _collections

class _MemoryLogHandler(logging.Handler):
    """Ring-buffer log handler for the admin dashboard."""
    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self._buf: collections.deque = _collections.deque(maxlen=maxlen)

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

from .cards import CardStore
from .embeddings import EmbeddingStore
from .graph import GraphStore, LinkKind, LINK_LABELS
from .difficulty import get_tier
from .apple_auth import verify_apple_token
from .app_store import (
    AppStoreConfigurationError,
    AppStoreVerificationError,
    fetch_transaction_info,
    verify_and_decode_signed_jws,
)
from .google_auth import verify_google_token
from .admin_assets import ADMIN_HTML, ADMIN_TESTS_HTML
from .api_models import (
    AdminTestRunRequest,
    AppStoreNotificationRequest,
    AppStoreReconcileRequest,
    AppStoreSyncRequest,
    AuthVerifyRequest,
    AuthVerifyResponse,
    CardLinkSummaryResponse,
    CardResponse,
    DeleteAccountResponse,
    EntitlementsResponse,
    ExplainResponse,
    GraphLinkResponse,
    HealthResponse,
    QuickTranslateResponse,
    SubscriptionStatusResponse,
    TranslateRequest,
    UserConfigRequest,
    UserConfigResponse,
    VocabAddResponse,
    VocabEntry,
)
from .route_registration import register_routes
from .translate_service import (
    run_explain_translate,
    run_phrase_translate,
    run_quick_translate,
)
from .vocab_service import (
    add_vocab_entries,
    build_links_by_kind,
    card_response,
    delete_vocab_word,
    graph_links_payload,
    list_vocab_cards,
    lookup_vocab_word,
)
from .pipeline_service import run_pipeline_background
from .admin_test_matrix import (
    build_test_catalog,
    get_last_test_run,
    run_pytest_matrix,
    store_last_test_run,
)
from .billing_handlers import (
    app_store_notifications_response,
    reconcile_app_store_subscription_response,
    sync_app_store_subscription_response,
)
from .billing import (
    append_app_store_event,
    build_entitlements_response,
    current_subscription_record,
    decode_notification_payload,
    decode_signed_transaction_info,
    default_subscription_payload,
    notification_status,
    require_pro_access,
    resolve_user_id_from_subscription_index,
    write_subscription_snapshot,
)
from .routers import build_billing_router, build_user_router
from .auth_service import create_jwt_token, resolve_and_link_user
from .settings import KGSettings, load_settings
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
JWT_EXPIRY_MINUTES = 60 * 24 * 365 # 1 year
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


def create_app(settings: KGSettings | None = None) -> FastAPI:
    runtime_settings = configure_runtime(settings or load_settings())

    app = FastAPI(title="Knowledge Graph API", version="0.1.0")
    app.state.kg_settings = runtime_settings

    # Allow BooksBrowser (iOS Simulator / device) to connect
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(
        build_user_router(
            get_user_config=get_user_config,
            get_user_entitlements=get_user_entitlements,
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
    register_routes(
        app,
        get_privacy_policy=get_privacy_policy,
        get_support=get_support,
        list_vocab=list_vocab,
        lookup_word=lookup_word,
        delete_word=delete_word,
        get_graph_links=get_graph_links,
        add_vocab=add_vocab,
        run_pipeline=run_pipeline,
        translate_quick=translate_quick,
        translate_phrase=translate_phrase,
        translate_explain=translate_explain,
        auth_verify=auth_verify,
        admin_ui=admin_ui,
        admin_stats=admin_stats,
        admin_logs=admin_logs,
        admin_run_tests=admin_run_tests,
        admin_last_test_run=admin_last_test_run,
        admin_test_catalog=admin_test_catalog,
        admin_tests_ui=admin_tests_ui,
    )
    return app

security = HTTPBearer()

# Global lock per user to prevent concurrent pipeline executions
_USER_LOCKS: dict[str, asyncio.Lock] = {}
_USER_LOCKS_MUTEX: asyncio.Lock | None = None  # initialized lazily after event loop starts

def _get_locks_mutex() -> asyncio.Lock:
    global _USER_LOCKS_MUTEX
    if _USER_LOCKS_MUTEX is None:
        _USER_LOCKS_MUTEX = asyncio.Lock()
    return _USER_LOCKS_MUTEX

async def get_user_lock(user_id: str) -> asyncio.Lock:
    async with _get_locks_mutex():
        if user_id not in _USER_LOCKS:
            _USER_LOCKS[user_id] = asyncio.Lock()
        return _USER_LOCKS[user_id]


def load_users() -> dict[str, dict[str, Any]]:
    return load_users_from(USERS_FILE, _normalize_users_payload)

def save_users(users: dict[str, dict[str, Any]]) -> None:
    save_users_to(USERS_FILE, users, _normalize_users_payload)


def _normalize_users_payload(users: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    return normalize_users_payload(users, _default_subscription_payload)

def _parse_datetime(raw: Any) -> datetime | None:
    return parse_datetime(raw)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict[str, Any]:
    token = credentials.credentials.strip()
    token_iat: datetime | None = None

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Token cannot be empty",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Try JWT first (new format)
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = decoded.get("sub")
        if not user_id:
            raise ValueError("No sub in token")
        token_iat = _parse_datetime(decoded.get("iat")) or datetime.now(tz=timezone.utc)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        # Fallback: treat as direct user_id (for backward compatibility)
        user_id = token

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    users = load_users()
    revoked_before = users.get("_revoked_before", {})
    if isinstance(revoked_before, dict):
        revoked_at = _parse_datetime(revoked_before.get(user_id))
        if revoked_at and (token_iat is None or token_iat <= revoked_at):
            raise HTTPException(
                status_code=401,
                detail="Account was deleted. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    record = users.get(user_id, {})
    if isinstance(record, dict):
        linked_to = record.get("_linked_to")
        if linked_to and isinstance(revoked_before, dict):
            revoked_at = _parse_datetime(revoked_before.get(linked_to))
            if revoked_at and (token_iat is None or token_iat <= revoked_at):
                raise HTTPException(
                    status_code=401,
                    detail="Account was deleted. Please sign in again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    user_dir = DATA_DIR / "users" / user_id
    user_dir.mkdir(parents=True, exist_ok=True)

    return {
        "id": user_id,
        "dir": user_dir,
        "record": record,
        "config": record.get("config", {}),
    }


def _card_store(user_dir: Path) -> CardStore:
    return CardStore(user_dir / "cards.db")


def _graph_store(user_dir: Path) -> GraphStore:
    return GraphStore(user_dir / "graph.json", user_dir / "candidates.json")


def _gemini_client():
    from openai import OpenAI

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(500, "GEMINI_API_KEY not configured on server")
    return OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )


def _embedding_store(user_dir: Path, user_id: str | None = None) -> EmbeddingStore:
    return EmbeddingStore(
        user_dir / "embeddings.npy",
        user_dir / "card_ids.json",
        _gemini_client(),
        user_id=user_id,
    )


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


def _current_subscription_record(user_record: dict[str, Any] | None) -> dict[str, Any]:
    return current_subscription_record(user_record)


def _require_pro_access(user: dict[str, Any], capability: str) -> None:
    require_pro_access(user, capability)


def _append_app_store_event(payload: dict[str, Any]) -> None:
    append_app_store_event(APP_STORE_NOTIFICATIONS_FILE, payload)


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
        bundle_id=APPLE_BUNDLE_ID,
        parse_datetime_fn=_parse_datetime,
        verify_signed_jws=verify_and_decode_signed_jws,
    )


def _decode_notification_payload(req: AppStoreNotificationRequest) -> tuple[dict[str, Any], dict[str, Any] | None]:
    return decode_notification_payload(
        req,
        bundle_id=APPLE_BUNDLE_ID,
        allow_unsigned_notifications=APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS,
        parse_datetime_fn=_parse_datetime,
        verify_signed_jws=verify_and_decode_signed_jws,
    )


# ---------------------------------------------------------------------------
# GET /api/user/config
# ---------------------------------------------------------------------------
def get_user_config(user: dict = Depends(get_current_user)):
    """Get user configuration."""
    return get_user_config_response(user)


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
    return sync_app_store_subscription_response(
        req,
        user,
        allow_unsigned_sync=APP_STORE_ALLOW_UNSIGNED_SYNC,
        users_lock_file=USERS_LOCK_FILE,
        load_users=load_users,
        save_users=save_users,
        decode_signed_transaction_info=_decode_signed_transaction_info,
        write_subscription_snapshot=_write_subscription_snapshot,
        build_entitlements_response=_build_entitlements_response,
    )


# ---------------------------------------------------------------------------
# POST /api/billing/app-store/notifications
# ---------------------------------------------------------------------------
def app_store_notifications(req: AppStoreNotificationRequest):
    """Receive App Store Server Notifications and persist/update subscription state."""
    return app_store_notifications_response(
        req,
        users_lock_file=USERS_LOCK_FILE,
        load_users=load_users,
        save_users=save_users,
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
    return await reconcile_app_store_subscription_response(
        req,
        user,
        apple_bundle_id=APPLE_BUNDLE_ID,
        users_lock_file=USERS_LOCK_FILE,
        load_users=load_users,
        save_users=save_users,
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
    return update_user_config_response(
        req,
        user,
        users_lock_file=USERS_LOCK_FILE,
        load_users=load_users,
        save_users=save_users,
    )


# ---------------------------------------------------------------------------
# DELETE /api/user/account
# ---------------------------------------------------------------------------
def delete_user_account(user: dict = Depends(get_current_user)):
    """Permanently delete the current account and all related user data."""
    return delete_user_account_response(
        user,
        users_lock_file=USERS_LOCK_FILE,
        load_users=load_users,
        save_users=save_users,
        collect_account_ids_for_deletion=_collect_account_ids_for_deletion,
        data_dir=DATA_DIR,
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
    _require_pro_access(user, "knowledge_sync")
    cards_store = _card_store(user["dir"])
    graph = _graph_store(user["dir"])
    return list_vocab_cards(
        since=since,
        cards_store=cards_store,
        graph=graph,
        card_response_builder=lambda card, graph_obj, cards_by_id: _card_response(card, graph_obj, cards_by_id),
    )


# ---------------------------------------------------------------------------
# GET /api/vocab/{word}
# ---------------------------------------------------------------------------
def lookup_word(word: str, user: dict = Depends(get_current_user)):
    """Lookup a word in the current user's card store."""
    _require_pro_access(user, "knowledge_sync")
    cards = _card_store(user["dir"])
    graph = _graph_store(user["dir"])
    return lookup_vocab_word(
        word,
        cards_store=cards,
        graph=graph,
        card_response_builder=lambda card, graph_obj, cards_by_id: _card_response(card, graph_obj, cards_by_id),
    )


# ---------------------------------------------------------------------------
# DELETE /api/vocab/{word}
# ---------------------------------------------------------------------------
def delete_word(word: str, user: dict = Depends(get_current_user)):
    """Delete a word from the current user's card store."""
    _require_pro_access(user, "knowledge_sync")
    cards = _card_store(user["dir"])
    return delete_vocab_word(word, cards_store=cards)

# ---------------------------------------------------------------------------
# GET /api/graph/links
# ---------------------------------------------------------------------------
def get_graph_links(user: dict = Depends(get_current_user)):
    """Get all active graph connections for the user."""
    _require_pro_access(user, "knowledge_graph")
    graph = _graph_store(user["dir"])
    return graph_links_payload(graph=graph)

# ---------------------------------------------------------------------------
# POST /api/vocab  — Batch add from BooksBrowser
# ---------------------------------------------------------------------------
def add_vocab(entries: list[VocabEntry], user: dict = Depends(get_current_user)):
    """Add vocabulary entries from BooksBrowser → KG Cards."""
    _require_pro_access(user, "knowledge_sync")
    cards = _card_store(user["dir"])
    return add_vocab_entries(
        entries,
        user=user,
        cards=cards,
        embeddings=_embedding_store(user["dir"], user_id=user["id"]),
        graph=_graph_store(user["dir"]),
        logger=logger,
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
    )


async def run_pipeline(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """Run enrich → link → difficulty → sync pipeline for the user in the background.

    Returns immediately with accepted status.
    """
    _require_pro_access(user, "knowledge_sync")
    background_tasks.add_task(_run_pipeline_background, user)
    return {"status": "queued", "message": "Pipeline started in the background"}

# ---------------------------------------------------------------------------
# POST /api/translate/quick & /api/translate/explain
# ---------------------------------------------------------------------------
def translate_quick(req: TranslateRequest, user: dict = Depends(get_current_user)):
    """Perform a quick UI translation via Gemini API (proxy)."""
    _require_pro_access(user, "reader_ai")
    client = _gemini_client()
    try:
        return run_quick_translate(req, user, client=client, logger=logger)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("translate/quick failed: %s", e, exc_info=True)
        raise HTTPException(500, f"Quick translation failed: {e}")

def translate_phrase(req: TranslateRequest, user: dict = Depends(get_current_user)):
    """Translate a multi-word phrase or expression. Returns translation only."""
    _require_pro_access(user, "reader_ai")
    client = _gemini_client()
    try:
        return run_phrase_translate(req, user, client=client)
    except Exception as e:
        raise HTTPException(500, f"Phrase translation failed: {e}")

def translate_explain(req: TranslateRequest, user: dict = Depends(get_current_user)):
    """Generate a 1-2 sentence context explanation via Gemini API (proxy)."""
    _require_pro_access(user, "reader_ai")
    client = _gemini_client()
    try:
        return run_explain_translate(req, user, client=client)
    except Exception as e:
        raise HTTPException(500, f"Explanation failed: {e}")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _create_jwt_token(user_id: str, provider: str) -> str:
    return create_jwt_token(
        user_id,
        provider,
        jwt_secret=JWT_SECRET,
        jwt_algorithm=JWT_ALGORITHM,
        jwt_expiry_minutes=JWT_EXPIRY_MINUTES,
    )


def _resolve_and_link_user(provider_user_id: str, provider: str, email: str | None = None) -> str:
    return resolve_and_link_user(
        provider_user_id,
        provider,
        users_lock_file=str(USERS_LOCK_FILE),
        load_users_fn=load_users,
        save_users_fn=save_users,
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
    if req.provider == "google":
        if not GOOGLE_CLIENT_ID:
            raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not configured")
        provider_user_id = await verify_google_token(req.token, GOOGLE_CLIENT_ID)
    elif req.provider == "apple":
        provider_user_id = verify_apple_token(req.token, APPLE_BUNDLE_ID)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {req.provider}")

    # Resolve and link user by email
    canonical_user_id = _resolve_and_link_user(provider_user_id, req.provider, req.email)

    # Create JWT token with canonical user_id
    access_token = _create_jwt_token(canonical_user_id, req.provider)

    return AuthVerifyResponse(
        access_token=access_token,
        user_id=canonical_user_id,
        expires_in=JWT_EXPIRY_MINUTES * 60,
    )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

def _check_admin(token: str | None):
    if not ADMIN_TOKEN:
        raise HTTPException(403, "ADMIN_TOKEN not configured")
    if token != ADMIN_TOKEN:
        raise HTTPException(403, "Forbidden")


def _build_test_catalog() -> dict[str, Any]:
    return build_test_catalog()


def _run_pytest_matrix(selected_items: list[str] | None = None) -> dict[str, Any]:
    return run_pytest_matrix(selected_items=selected_items)


def admin_ui(token: str | None = None):
    """Admin dashboard UI."""
    _check_admin(token)
    return HTMLResponse(ADMIN_HTML)


def admin_stats(token: str | None = None):
    """Return per-user token + vocab stats for admin dashboard."""
    _check_admin(token)

    from .token_tracker import get_all_stats

    users_data = load_users()
    token_stats = get_all_stats()

    IN_PER_M = 0.10
    OUT_PER_M = 0.40
    EMB_PER_M = 0.00025

    result = []
    for uid, info in users_data.items():
        if uid.startswith("_"):
            continue

        # Vocab count from cards.db
        user_dir = DATA_DIR / "users" / uid
        vocab_count = 0
        try:
            store = _card_store(user_dir)
            vocab_count = sum(1 for c in store.all() if not c.is_deleted)
        except Exception:
            pass

        utoken = token_stats.get(uid, {})
        total_input = sum(d["input_tokens"] for d in utoken.values())
        total_output = sum(d["output_tokens"] for d in utoken.values())

        est_cost = 0.0
        for call_type, d in utoken.items():
            if call_type == "embed":
                est_cost += (d["input_tokens"] / 1_000_000) * EMB_PER_M
            else:
                est_cost += (d["input_tokens"] / 1_000_000) * IN_PER_M
                est_cost += (d["output_tokens"] / 1_000_000) * OUT_PER_M

        config = info.get("config", {}) if isinstance(info, dict) else {}
        result.append({
            "user_id": uid,
            "email": info.get("email") if isinstance(info, dict) else None,
            "provider": info.get("provider") if isinstance(info, dict) else None,
            "last_login": info.get("last_login") if isinstance(info, dict) else None,
            "vocab_count": vocab_count,
            "has_mochi": bool(config.get("mochi_api_key")),
            "tokens": utoken,
            "total_input": total_input,
            "total_output": total_output,
            "est_cost_usd": round(est_cost, 6),
        })

    result.sort(key=lambda x: x["vocab_count"], reverse=True)
    return {"users": result}


def admin_logs(token: str | None = None, n: int = 200, level: str | None = None):
    """Return recent in-memory log entries for the admin dashboard."""
    _check_admin(token)
    return {"logs": _mem_log.get(n=n, level=level or None)}


def admin_run_tests(req: AdminTestRunRequest | None = None, token: str | None = None):
    """Run test suite and return matrix view data."""
    _check_admin(token)
    selected = req.itemIds if req else []
    return store_last_test_run(_run_pytest_matrix(selected_items=selected))


def admin_last_test_run(token: str | None = None):
    """Get latest test run result for matrix page."""
    _check_admin(token)
    last_run = get_last_test_run()
    if last_run is None:
        return {"status": "idle"}
    return last_run


def admin_test_catalog(token: str | None = None):
    """Return clickable test-matrix catalog."""
    _check_admin(token)
    return _build_test_catalog()



def admin_tests_ui(token: str | None = None):
    """Minimal grayscale test matrix dashboard."""
    _check_admin(token)
    return HTMLResponse(ADMIN_TESTS_HTML)


app = create_app()
