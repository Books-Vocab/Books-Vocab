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
import shutil
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
from .user_store import (
    collect_account_ids_for_deletion,
    load_users_from,
    normalize_users_payload,
    parse_datetime,
    save_users_to,
)

load_dotenv()

app = FastAPI(title="Knowledge Graph API", version="0.1.0")

# Allow BooksBrowser (iOS Simulator / device) to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/privacy.html", response_class=FileResponse)
def get_privacy_policy():
    """Serve the static privacy policy HTML."""
    privacy_path = Path(__file__).resolve().parent.parent.parent / "privacy.html"
    if not privacy_path.exists():
        return HTMLResponse("<h1>Privacy Policy Not Found</h1>", status_code=404)
    return FileResponse(privacy_path)

@app.get("/support.html", response_class=FileResponse)
def get_support():
    """Serve the support page HTML."""
    support_path = Path(__file__).resolve().parent.parent.parent / "support.html"
    if not support_path.exists():
        return HTMLResponse("<h1>Support Page Not Found</h1>", status_code=404)
    return FileResponse(support_path)

# ---------------------------------------------------------------------------
# Data directory & Multi-User
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.getenv("KG_DATA_DIR", str(Path(__file__).resolve().parent.parent.parent / "data")))
USERS_FILE = DATA_DIR / "users.json"
USERS_LOCK_FILE = DATA_DIR / "users.json.lock"
APP_STORE_NOTIFICATIONS_FILE = DATA_DIR / "app_store_notifications.ndjson"

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = 60 * 24 * 365 # 1 year
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
APPLE_BUNDLE_ID = os.getenv("APPLE_BUNDLE_ID", "com.Max0228.BooksBrowser")
APP_STORE_ALLOW_UNSIGNED_SYNC = os.getenv("APP_STORE_ALLOW_UNSIGNED_SYNC", "").strip().lower() in {"1", "true", "yes"}
APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS = os.getenv("APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS", "").strip().lower() in {"1", "true", "yes"}

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
    grouped: dict[str, list[CardLinkSummaryResponse]] = {}

    for link in graph.get_links_for(card_id):
        other_id = link.to_id if link.from_id == card_id else link.from_id
        other_card = cards_by_id.get(other_id)
        if not other_card or other_card.is_deleted:
            continue

        kind_key = link.kind.value
        grouped.setdefault(kind_key, []).append(
            CardLinkSummaryResponse(
                id=link.id,
                cardId=other_card.id,
                word=other_card.content,
                kind=kind_key,
                label=LINK_LABELS.get(link.kind, link.kind.value),
                confidence=link.confidence,
                reason=link.reason,
            )
        )

    ordered: dict[str, list[CardLinkSummaryResponse]] = {}
    for kind in LinkKind:
        items = grouped.get(kind.value)
        if items:
            ordered[kind.value] = sorted(items, key=lambda item: item.word.lower())

    return ordered


def _card_response(
    card,
    graph: GraphStore,
    cards_by_id: dict[str, Any],
):
    tier = get_tier(card.content)
    links_by_kind = {}
    if not card.is_deleted:
        links_by_kind = _build_links_by_kind(card.id, graph, cards_by_id)

    return CardResponse(
        id=card.id,
        content=card.content,
        meaning=card.meaning,
        pos=card.pos,
        difficulty=card.difficulty,
        difficultyTier=tier.tag,
        note=card.note,
        examples=card.examples,
        mode=card.mode,
        isDeleted=card.is_deleted,
        inflections=card.inflections or [],
        linksByKind=links_by_kind,
    )


def _collect_account_ids_for_deletion(users: dict[str, dict[str, Any]], user_id: str) -> tuple[str, list[str]]:
    return collect_account_ids_for_deletion(users, user_id)


def _default_subscription_payload() -> dict[str, Any]:
    return {
        "is_active": False,
        "product_id": None,
        "plan_name": "BooksBrowser Pro",
        "price_display": None,
        "status": "inactive",
        "is_trial": False,
        "trial_days": 7,
        "will_renew": False,
        "expires_at": None,
        "source": "app_store",
        "last_synced_at": None,
    }


def _build_entitlements_response(user_record: dict[str, Any] | None) -> EntitlementsResponse:
    record = user_record if isinstance(user_record, dict) else {}
    raw_subscription = record.get("subscription")
    subscription = _default_subscription_payload()
    if isinstance(raw_subscription, dict):
        subscription.update(raw_subscription)
    return EntitlementsResponse(
        pro=SubscriptionStatusResponse(**subscription)
    )


def _current_subscription_record(user_record: dict[str, Any] | None) -> dict[str, Any]:
    record = user_record if isinstance(user_record, dict) else {}
    raw_subscription = record.get("subscription")
    subscription = _default_subscription_payload()
    if isinstance(raw_subscription, dict):
        subscription.update(raw_subscription)
    return subscription


def _require_pro_access(user: dict[str, Any], capability: str) -> None:
    subscription = _current_subscription_record(user.get("record"))
    if subscription.get("is_active"):
        return
    raise HTTPException(
        status_code=402,
        detail={
            "code": "pro_required",
            "capability": capability,
            "message": "BooksBrowser Pro subscription required.",
        },
    )


def _append_app_store_event(payload: dict[str, Any]) -> None:
    APP_STORE_NOTIFICATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with APP_STORE_NOTIFICATIONS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _upsert_subscription_index(users: dict[str, Any], user_id: str, original_transaction_id: str | None, transaction_id: str | None) -> None:
    index = users.get("_subscription_index")
    if not isinstance(index, dict):
        index = {}
        users["_subscription_index"] = index

    if isinstance(original_transaction_id, str) and original_transaction_id.strip():
        index[original_transaction_id.strip()] = user_id
    if isinstance(transaction_id, str) and transaction_id.strip():
        index[transaction_id.strip()] = user_id


def _resolve_user_id_from_subscription_index(users: dict[str, Any], original_transaction_id: str | None, transaction_id: str | None) -> str | None:
    index = users.get("_subscription_index")
    if not isinstance(index, dict):
        return None
    for candidate in (original_transaction_id, transaction_id):
        if isinstance(candidate, str) and candidate.strip():
            resolved = index.get(candidate.strip())
            if isinstance(resolved, str) and resolved:
                return resolved
    return None


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
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    record = users.setdefault(user_id, {})
    subscription = _default_subscription_payload()
    existing = record.get("subscription")
    if isinstance(existing, dict):
        subscription.update(existing)

    normalized_status = status.strip() or "active"
    subscription.update({
        "is_active": normalized_status in {"active", "trial", "grace_period"},
        "product_id": product_id.strip(),
        "plan_name": "BooksBrowser Pro",
        "price_display": price_display.strip() if isinstance(price_display, str) and price_display.strip() else subscription.get("price_display"),
        "status": normalized_status,
        "is_trial": is_trial,
        "trial_days": subscription.get("trial_days") or 7,
        "will_renew": will_renew,
        "expires_at": expires_at,
        "source": source,
        "last_synced_at": now_iso,
        "transaction_id": transaction_id,
        "original_transaction_id": original_transaction_id,
        "environment": environment,
    })
    record["subscription"] = subscription
    _upsert_subscription_index(users, user_id, original_transaction_id, transaction_id)
    return record


def _notification_status(notification_type: str | None, subtype: str | None) -> str:
    kind = (notification_type or "").upper()
    sub = (subtype or "").upper()
    if kind in {"SUBSCRIBED", "OFFER_REDEEMED", "DID_RENEW"}:
        return "trial" if sub == "INITIAL_BUY" else "active"
    if kind == "GRACE_PERIOD_EXPIRED":
        return "expired"
    if kind == "DID_FAIL_TO_RENEW":
        return "grace_period"
    if kind in {"EXPIRED", "REVOKE"}:
        return "expired"
    return "active"


def _normalize_ms_timestamp(raw: Any) -> str | None:
    if raw is None:
        return None
    try:
        timestamp_ms = int(raw)
    except (TypeError, ValueError):
        return _parse_datetime(raw).isoformat() if _parse_datetime(raw) else None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def _bool_from_any(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    return default


def _status_from_transaction_payload(payload: dict[str, Any], renewal_payload: dict[str, Any] | None = None) -> str:
    if payload.get("revocationDate"):
        return "expired"
    expires_at = _parse_datetime(_normalize_ms_timestamp(payload.get("expiresDate")))
    if expires_at and expires_at <= datetime.now(tz=timezone.utc):
        return "expired"
    grace = renewal_payload.get("gracePeriodExpiresDate") if isinstance(renewal_payload, dict) else None
    if grace:
        grace_dt = _parse_datetime(_normalize_ms_timestamp(grace))
        if grace_dt and grace_dt > datetime.now(tz=timezone.utc):
            return "grace_period"
    offer_type = payload.get("offerType")
    offer_discount_type = str(payload.get("offerDiscountType") or "").upper()
    if offer_type == 1 or offer_discount_type == "FREE_TRIAL":
        return "trial"
    return "active"


def _verified_transaction_snapshot(
    payload: dict[str, Any],
    *,
    renewal_payload: dict[str, Any] | None = None,
    price_display: str | None = None,
) -> dict[str, Any]:
    product_id = payload.get("productId")
    if not isinstance(product_id, str) or not product_id.strip():
        raise HTTPException(status_code=400, detail="Verified App Store transaction is missing productId")

    environment = str(payload.get("environment") or "production").lower()
    transaction_id = payload.get("transactionId")
    original_transaction_id = payload.get("originalTransactionId")
    status = _status_from_transaction_payload(payload, renewal_payload)
    auto_renew_status = None
    if isinstance(renewal_payload, dict):
        auto_renew_status = renewal_payload.get("autoRenewStatus")

    return {
        "product_id": product_id.strip(),
        "transaction_id": str(transaction_id) if transaction_id is not None else None,
        "original_transaction_id": str(original_transaction_id) if original_transaction_id is not None else None,
        "environment": environment,
        "status": status,
        "is_trial": status == "trial",
        "expires_at": _normalize_ms_timestamp(payload.get("expiresDate")),
        "will_renew": _bool_from_any(auto_renew_status, default=status in {"active", "trial", "grace_period"}),
        "price_display": price_display,
    }


def _decode_signed_transaction_info(signed_transaction_info: str) -> dict[str, Any]:
    verified = verify_and_decode_signed_jws(signed_transaction_info, bundle_id=APPLE_BUNDLE_ID)
    return _verified_transaction_snapshot(verified.payload)


def _decode_notification_payload(req: AppStoreNotificationRequest) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not req.signed_payload:
        if APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS:
            return ({
                "product_id": req.product_id,
                "transaction_id": req.transaction_id,
                "original_transaction_id": req.original_transaction_id,
                "environment": req.environment,
                "status": req.status or _notification_status(req.notification_type, req.subtype),
                "is_trial": req.is_trial,
                "expires_at": req.expires_at,
                "will_renew": req.will_renew if req.will_renew is not None else True,
                "price_display": None,
            }, req.raw_payload)
        raise HTTPException(status_code=400, detail="signed_payload is required for App Store notifications")

    verified_notification = verify_and_decode_signed_jws(req.signed_payload, bundle_id=APPLE_BUNDLE_ID)
    notification_payload = verified_notification.payload
    data = notification_payload.get("data", {})
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="App Store notification data payload is malformed")

    signed_transaction_info = data.get("signedTransactionInfo")
    signed_renewal_info = data.get("signedRenewalInfo")
    if not isinstance(signed_transaction_info, str) or not signed_transaction_info:
        raise HTTPException(status_code=400, detail="App Store notification missing signedTransactionInfo")

    transaction_verified = verify_and_decode_signed_jws(signed_transaction_info, bundle_id=APPLE_BUNDLE_ID)
    renewal_payload = None
    if isinstance(signed_renewal_info, str) and signed_renewal_info:
        renewal_payload = verify_and_decode_signed_jws(signed_renewal_info, bundle_id=APPLE_BUNDLE_ID).payload

    snapshot = _verified_transaction_snapshot(
        transaction_verified.payload,
        renewal_payload=renewal_payload,
    )
    return snapshot, notification_payload


# ---------------------------------------------------------------------------
# GET /api/user/config
# ---------------------------------------------------------------------------
@app.get("/api/user/config", response_model=UserConfigResponse)
def get_user_config(user: dict = Depends(get_current_user)):
    """Get user configuration."""
    return UserConfigResponse(
        mochi_api_key=user["config"].get("mochi_api_key")
    )


# ---------------------------------------------------------------------------
# GET /api/user/entitlements
# ---------------------------------------------------------------------------
@app.get("/api/user/entitlements", response_model=EntitlementsResponse)
def get_user_entitlements(user: dict = Depends(get_current_user)):
    """Get the current user's subscription entitlement snapshot."""
    return _build_entitlements_response(user.get("record"))


# ---------------------------------------------------------------------------
# POST /api/billing/app-store/sync
# ---------------------------------------------------------------------------
@app.post("/api/billing/app-store/sync", response_model=EntitlementsResponse)
def sync_app_store_subscription(req: AppStoreSyncRequest, user: dict = Depends(get_current_user)):
    """Persist the latest App Store subscription snapshot for the current user."""
    try:
        if req.signed_transaction_info:
            snapshot = _decode_signed_transaction_info(req.signed_transaction_info)
            if req.transaction_id and snapshot["transaction_id"] and req.transaction_id != snapshot["transaction_id"]:
                raise HTTPException(status_code=400, detail="transaction_id does not match signed_transaction_info")
            if req.original_transaction_id and snapshot["original_transaction_id"] and req.original_transaction_id != snapshot["original_transaction_id"]:
                raise HTTPException(status_code=400, detail="original_transaction_id does not match signed_transaction_info")
        else:
            if not APP_STORE_ALLOW_UNSIGNED_SYNC and req.environment.lower() != "xcode":
                raise HTTPException(status_code=400, detail="signed_transaction_info is required for production App Store sync")
            snapshot = {
                "product_id": req.product_id,
                "transaction_id": req.transaction_id,
                "original_transaction_id": req.original_transaction_id,
                "environment": req.environment,
                "status": req.status,
                "is_trial": req.is_trial,
                "expires_at": req.expires_at,
                "will_renew": req.will_renew,
                "price_display": req.price_display,
            }
    except AppStoreConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except AppStoreVerificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with FileLock(str(USERS_LOCK_FILE)):
        users = load_users()
        record = _write_subscription_snapshot(
            users,
            user["id"],
            product_id=snapshot["product_id"],
            status=snapshot["status"],
            is_trial=snapshot["is_trial"],
            expires_at=snapshot["expires_at"],
            will_renew=snapshot["will_renew"],
            environment=snapshot["environment"],
            transaction_id=snapshot["transaction_id"],
            original_transaction_id=snapshot["original_transaction_id"],
            price_display=snapshot["price_display"],
            source="app_store",
        )
        save_users(users)

    return _build_entitlements_response(record)


# ---------------------------------------------------------------------------
# POST /api/billing/app-store/notifications
# ---------------------------------------------------------------------------
@app.post("/api/billing/app-store/notifications")
def app_store_notifications(req: AppStoreNotificationRequest):
    """Receive App Store Server Notifications and persist/update subscription state."""
    try:
        snapshot, decoded_payload = _decode_notification_payload(req)
    except AppStoreConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except AppStoreVerificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    event = {
        "received_at": datetime.now(tz=timezone.utc).isoformat(),
        "notification_type": req.notification_type,
        "subtype": req.subtype,
        "product_id": snapshot["product_id"],
        "transaction_id": snapshot["transaction_id"],
        "original_transaction_id": snapshot["original_transaction_id"],
        "environment": snapshot["environment"],
        "status": snapshot["status"],
        "is_trial": snapshot["is_trial"],
        "expires_at": snapshot["expires_at"],
        "will_renew": snapshot["will_renew"],
        "signed_payload": req.signed_payload,
        "raw_payload": decoded_payload or req.raw_payload,
    }
    _append_app_store_event(event)

    with FileLock(str(USERS_LOCK_FILE)):
        users = load_users()
        user_id = _resolve_user_id_from_subscription_index(
            users,
            snapshot["original_transaction_id"],
            snapshot["transaction_id"],
        )
        if not user_id:
            return {"status": "accepted", "updated": False, "reason": "unmapped_transaction"}
        record = _write_subscription_snapshot(
            users,
            user_id,
            product_id=snapshot["product_id"],
            status=snapshot["status"],
            is_trial=snapshot["is_trial"],
            expires_at=snapshot["expires_at"],
            will_renew=snapshot["will_renew"],
            environment=snapshot["environment"],
            transaction_id=snapshot["transaction_id"],
            original_transaction_id=snapshot["original_transaction_id"],
            price_display=None,
            source="app_store_notification",
        )
        save_users(users)

    return {
        "status": "accepted",
        "updated": True,
        "user_id": user_id,
        "entitlements": _build_entitlements_response(record).model_dump(),
    }


# ---------------------------------------------------------------------------
# POST /api/billing/app-store/reconcile
# ---------------------------------------------------------------------------
@app.post("/api/billing/app-store/reconcile", response_model=EntitlementsResponse)
async def reconcile_app_store_subscription(req: AppStoreReconcileRequest, user: dict = Depends(get_current_user)):
    """Fetch transaction state from Apple's App Store Server API and persist it."""
    try:
        server_response = await fetch_transaction_info(
            req.transaction_id,
            bundle_id=APPLE_BUNDLE_ID,
            environment=req.environment,
        )
        signed_transaction_info = server_response.get("signedTransactionInfo")
        if not isinstance(signed_transaction_info, str) or not signed_transaction_info:
            raise HTTPException(status_code=502, detail="App Store transaction lookup did not return signedTransactionInfo")
        snapshot = _decode_signed_transaction_info(signed_transaction_info)
    except AppStoreConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except AppStoreVerificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"App Store API lookup failed: HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"App Store API lookup failed: {exc}") from exc

    with FileLock(str(USERS_LOCK_FILE)):
        users = load_users()
        resolved_user_id = _resolve_user_id_from_subscription_index(
            users,
            snapshot["original_transaction_id"],
            snapshot["transaction_id"],
        ) or user["id"]
        record = _write_subscription_snapshot(
            users,
            resolved_user_id,
            product_id=snapshot["product_id"],
            status=snapshot["status"],
            is_trial=snapshot["is_trial"],
            expires_at=snapshot["expires_at"],
            will_renew=snapshot["will_renew"],
            environment=snapshot["environment"],
            transaction_id=snapshot["transaction_id"],
            original_transaction_id=snapshot["original_transaction_id"],
            price_display=None,
            source="app_store_server_api",
        )
        save_users(users)

    return _build_entitlements_response(record)


# ---------------------------------------------------------------------------
# PUT /api/user/config
# ---------------------------------------------------------------------------
@app.put("/api/user/config", response_model=UserConfigResponse)
def update_user_config(req: UserConfigRequest, user: dict = Depends(get_current_user)):
    """Update user configuration."""
    with FileLock(str(USERS_LOCK_FILE)):
        users = load_users()
        user_id = user["id"]

        if user_id not in users:
            users[user_id] = {}

        if "config" not in users[user_id]:
            users[user_id]["config"] = {}

        if req.mochi_api_key is not None:
            users[user_id]["config"]["mochi_api_key"] = req.mochi_api_key.strip()

        save_users(users)

    return UserConfigResponse(
        mochi_api_key=users[user_id]["config"].get("mochi_api_key")
    )


# ---------------------------------------------------------------------------
# DELETE /api/user/account
# ---------------------------------------------------------------------------
@app.delete("/api/user/account", response_model=DeleteAccountResponse)
def delete_user_account(user: dict = Depends(get_current_user)):
    """Permanently delete the current account and all related user data."""
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    user_id = user["id"]

    with FileLock(str(USERS_LOCK_FILE)):
        users = load_users()
        canonical_id, ids_to_delete = _collect_account_ids_for_deletion(users, user_id)

        revoked_before = users.get("_revoked_before")
        if not isinstance(revoked_before, dict):
            revoked_before = {}
        for uid in ids_to_delete:
            revoked_before[uid] = now_iso
        users["_revoked_before"] = revoked_before

        email_index = users.get("_email_index")
        if isinstance(email_index, dict):
            stale_emails = [email for email, mapped_uid in email_index.items() if mapped_uid in ids_to_delete]
            for email in stale_emails:
                email_index.pop(email, None)
            if not email_index:
                users.pop("_email_index", None)

        for uid in ids_to_delete:
            users.pop(uid, None)

        save_users(users)

    deleted_dirs: list[str] = []
    for uid in ids_to_delete:
        user_dir = DATA_DIR / "users" / uid
        if not user_dir.exists():
            continue
        try:
            shutil.rmtree(user_dir)
            deleted_dirs.append(uid)
        except Exception as e:
            logger.exception("Failed to delete user directory %s: %s", user_dir, e)
            raise HTTPException(status_code=500, detail=f"Failed to remove user data for {uid}")

    return DeleteAccountResponse(
        deleted_user_id=canonical_id,
        linked_ids=[uid for uid in ids_to_delete if uid != canonical_id],
        deleted_dirs=deleted_dirs,
    )


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------
@app.get("/api/health", response_model=HealthResponse)
def health(user: dict = Depends(get_current_user)):
    """Server health + stats per user."""
    cards = _card_store(user["dir"])
    graph = _graph_store(user["dir"])

    # Last modified time of cards.json
    cards_path = user["dir"] / "cards.json"
    last_mod = None
    if cards_path.exists():
        ts = cards_path.stat().st_mtime
        last_mod = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    return HealthResponse(
        status="ok",
        cards=cards.count(),
        links=graph.link_count(),
        pendingCandidates=graph.candidate_count(),
        lastModified=last_mod,
    )


# ---------------------------------------------------------------------------
# GET /api/vocab
# ---------------------------------------------------------------------------
@app.get("/api/vocab")
def list_vocab(since: str | None = None, user: dict = Depends(get_current_user)):
    """List all cards for the current user, optionally filtered by a since timestamp."""
    _require_pro_access(user, "knowledge_sync")
    cards_store = _card_store(user["dir"])
    graph = _graph_store(user["dir"])
    if since:
        try:
            # Parse ISO 8601 (e.g. 2026-02-27T10:00:00Z)
            # Remove Z if present because fromisoformat in <3.11 expects proper +00:00, 
            # but Python 3.11+ handles Z natively.
            parsed_since = datetime.fromisoformat(since.replace("Z", "+00:00"))
            cards = cards_store.get_modified_since(parsed_since)
        except ValueError:
            raise HTTPException(400, "Invalid since timestamp format. Expected ISO 8601.")
    else:
        # Initial full sync avoids deleted cards
        cards = list(cards_store.all())

    cards_by_id = {card.id: card for card in cards_store.all(include_deleted=True)}
    return [_card_response(card, graph, cards_by_id) for card in cards]


# ---------------------------------------------------------------------------
# GET /api/vocab/{word}
# ---------------------------------------------------------------------------
@app.get("/api/vocab/{word}")
def lookup_word(word: str, user: dict = Depends(get_current_user)):
    """Lookup a word in the current user's card store."""
    _require_pro_access(user, "knowledge_sync")
    cards = _card_store(user["dir"])
    graph = _graph_store(user["dir"])
    cards_by_id = {card.id: card for card in cards.all(include_deleted=True)}
    for card in cards.all():
        if card.content.lower() == word.lower():
            return _card_response(card, graph, cards_by_id)
    raise HTTPException(404, f"Word '{word}' not found")


# ---------------------------------------------------------------------------
# DELETE /api/vocab/{word}
# ---------------------------------------------------------------------------
@app.delete("/api/vocab/{word}")
def delete_word(word: str, user: dict = Depends(get_current_user)):
    """Delete a word from the current user's card store."""
    _require_pro_access(user, "knowledge_sync")
    cards = _card_store(user["dir"])
    for card in cards.all():
        if card.content.lower() == word.lower():
            card_id = card.id
            cards.delete(card_id)
            return {"deleted": word, "id": card_id}
    raise HTTPException(404, f"Word '{word}' not found")

# ---------------------------------------------------------------------------
# GET /api/graph/links
# ---------------------------------------------------------------------------
@app.get("/api/graph/links", response_model=list[GraphLinkResponse])
def get_graph_links(user: dict = Depends(get_current_user)):
    """Get all active graph connections for the user."""
    _require_pro_access(user, "knowledge_graph")
    graph = _graph_store(user["dir"])
    links = []
    
    for link in graph._links.values():
        if link.status != "active":
            continue
        links.append(GraphLinkResponse(
            id=link.id,
            fromId=link.from_id,
            toId=link.to_id,
            kind=link.kind.value,
            confidence=link.confidence,
            reason=link.reason
        ))
            
    return links

# ---------------------------------------------------------------------------
# POST /api/vocab  — Batch add from BooksBrowser
# ---------------------------------------------------------------------------
@app.post("/api/vocab", response_model=VocabAddResponse)
def add_vocab(entries: list[VocabEntry], user: dict = Depends(get_current_user)):
    """Add vocabulary entries from BooksBrowser → KG Cards."""
    _require_pro_access(user, "knowledge_sync")
    cards = _card_store(user["dir"])
    existing = {c.content.lower() for c in cards.all()}

    created = 0
    skipped = 0
    duplicates: list[str] = []
    card_ids: dict[str, str] = {}

    for entry in entries:
        word = entry.word.strip()
        if word.lower() in existing:
            skipped += 1
            duplicates.append(word)
            # Still return the existing card ID
            for c in cards.all():
                if c.content.lower() == word.lower():
                    card_ids[word] = c.id
                    break
            continue

        # Build example with **word** marking
        example = ""
        if entry.context:
            # Try to wrap the word in the context with **bold**
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            if pattern.search(entry.context):
                example = pattern.sub(f"**{word}**", entry.context, count=1)
            else:
                example = entry.context

        # 片語（含空格）不做 inflection 展開
        inflections: list[str] = []
        root = None
        if " " not in word:
            root = (entry.root_form or "").strip().lower() or None
            if root:
                try:
                    from lemminflect import getAllInflections
                    infl_map = getAllInflections(root)
                    # 若 lemminflect 完全查不到此 root，代表 AI 給的是非法單字，fallback 到原字
                    if not infl_map:
                        logger.warning("lemminflect found no inflections for root '%s', falling back to '%s'", root, word)
                        root = word.lower()
                        infl_map = getAllInflections(root)
                    seen = {word.lower()}
                    for forms in infl_map.values():
                        for f in forms:
                            fl = f.lower()
                            if fl not in seen:
                                inflections.append(fl)
                                seen.add(fl)
                except Exception as e:
                    logger.warning("lemminflect failed for root '%s': %s", root, e)

        card = cards.add(
            content=word,
            meaning=entry.translation.strip(),
            examples=[example] if example else [],
            root_form=root,
            inflections=inflections,
        )
        card_ids[word] = card.id
        existing.add(word.lower())
        created += 1

    if created > 0:
        embeddings = _embedding_store(user["dir"], user_id=user["id"])
        graph = _graph_store(user["dir"])
        for entry in entries:
            word = entry.word.strip()
            cid = card_ids.get(word)
            card = cards.get(cid) if cid else None
            if card and not embeddings.has(card.id):
                try:
                    embeddings.add(card.id, card.embed_text())
                    # Find similarity candidates
                    similar = embeddings.find_similar(card.id, k=3)
                    for other_id, score in similar:
                        if score > 0.655:
                            graph.add_candidate(card.id, other_id, score)
                except Exception as e:
                    logger.warning("Failed to generate embedding for '%s': %s", word, e)
                    continue

    return VocabAddResponse(
        created=created,
        skipped=skipped,
        duplicates=duplicates,
        cardIds=card_ids,
    )


# ---------------------------------------------------------------------------
# POST /api/pipeline  — Run full pipeline in background
# ---------------------------------------------------------------------------
async def _run_pipeline_background(user: dict):
    uid = user["id"]
    lock = await get_user_lock(uid)
    if lock.locked():
        logger.info("[%s] Pipeline already running, skipping.", uid)
        return

    async with lock:
        try:
            logger.info("[%s] Pipeline started.", uid)

            # --- Step 1: Enrich ---
            try:
                logger.info("[%s] Step 1: Enrich", uid)
                cards = _card_store(user["dir"])
                all_cards = list(cards.all())
                targets = [c for c in all_cards if not c.pos or not c.note]

                if targets:
                    from .enrich import enrich_cards_stream
                    client = _gemini_client()
                    logger.info("[%s] Enriching %d cards...", uid, len(targets))

                    updated = 0
                    async for msg in enrich_cards_stream(client, targets, user_id=uid, batch_size=20, max_workers=5):
                        if msg.get("status") == "error":
                            logger.warning("[%s] Enrichment batch error: %s", uid, msg.get("detail"))

                        if msg.get("results"):
                            result_map = {r["word"].lower(): r for r in msg["results"]}
                            for card in targets:
                                enrichment = result_map.get(card.content.lower())
                                if not enrichment:
                                    continue

                                kwargs = {}
                                if enrichment.get("pos") and not card.pos:
                                    kwargs["pos"] = enrichment["pos"]
                                if enrichment.get("note") and not card.note:
                                    kwargs["note"] = enrichment["note"]

                                if kwargs:
                                    updated_card = cards.update(card.id, **kwargs)
                                    if updated_card:
                                        card.pos = updated_card.pos
                                        card.note = updated_card.note
                                        updated += 1

                    logger.info("[%s] Enriched %d cards", uid, updated)
                else:
                    logger.info("[%s] All cards already enriched", uid)
            except Exception as e:
                logger.error("[%s] Step 1 (Enrich) failed: %s", uid, e, exc_info=True)

            # --- Step 1b: Backfill missing embeddings ---
            # Cards created when embedding API was down have no embedding;
            # without this they are permanently excluded from graph linking.
            try:
                cards = _card_store(user["dir"])
                embeddings = _embedding_store(user["dir"], user_id=uid)
                graph = _graph_store(user["dir"])
                missing = [c for c in cards.all() if not embeddings.has(c.id)]
                if missing:
                    logger.info("[%s] Backfilling embeddings for %d cards", uid, len(missing))
                    backfilled = 0
                    for card in missing:
                        try:
                            embeddings.add(card.id, card.embed_text())
                            similar = embeddings.find_similar(card.id, k=3)
                            for other_id, score in similar:
                                if score > 0.655:
                                    graph.add_candidate(card.id, other_id, score)
                            backfilled += 1
                        except Exception as e:
                            logger.warning("[%s] Embedding backfill failed for '%s': %s", uid, card.content, e)
                    logger.info("[%s] Backfilled %d embeddings", uid, backfilled)
            except Exception as e:
                logger.error("[%s] Step 1b (Embedding backfill) failed: %s", uid, e, exc_info=True)

            # --- Step 2: Link ---
            try:
                logger.info("[%s] Step 2: Link", uid)
                graph = _graph_store(user["dir"])
                candidates = graph.pop_candidates()

                if candidates:
                    from .judge import Judge
                    client = _gemini_client()
                    judge = Judge(client)
                    created_links = 0
                    cards = _card_store(user["dir"])
                    i = 0

                    try:
                        for i, candidate in enumerate(candidates):
                            card_a = cards.get(candidate.from_id)
                            card_b = cards.get(candidate.to_id)
                            if not card_a or not card_b or card_a.is_deleted or card_b.is_deleted:
                                continue

                            loop = asyncio.get_event_loop()
                            result = await loop.run_in_executor(
                                None,
                                lambda a=card_a, b=card_b: judge.evaluate(
                                    a.content, a.meaning, b.content, b.meaning, user_id=uid
                                ),
                            )

                            if result:
                                graph.add_link(
                                    candidate.from_id,
                                    candidate.to_id,
                                    LinkKind(result.link),
                                    result.confidence,
                                    result.reason,
                                )
                                created_links += 1
                    except Exception as e:
                        # Rescue unprocessed candidates back to queue
                        graph.requeue_candidates(candidates[i:])
                        raise e
                    logger.info("[%s] Created %d links", uid, created_links)
                else:
                    logger.info("[%s] No pending candidates", uid)
            except Exception as e:
                logger.error("[%s] Step 2 (Link) failed: %s", uid, e, exc_info=True)

            # --- Step 3: Difficulty ---
            try:
                logger.info("[%s] Step 3: Difficulty", uid)
                from .difficulty import get_zipf
                cards = _card_store(user["dir"])
                all_cards = list(cards.all(include_deleted=False))
                scored = 0
                for card in all_cards:
                    z = get_zipf(card.content)
                    difficulty = round(z, 2)
                    if card.difficulty != difficulty:
                        cards.update(card.id, difficulty=difficulty)
                        scored += 1
                logger.info("[%s] Scored %d cards", uid, scored)
            except Exception as e:
                logger.error("[%s] Step 3 (Difficulty) failed: %s", uid, e, exc_info=True)

            # --- Step 4: Sync to Mochi ---
            try:
                logger.info("[%s] Step 4: Mochi Sync", uid)
                mochi_key = user["config"].get("mochi_api_key")
                if not mochi_key:
                    logger.info("[%s] Mochi API key not set, skipping sync", uid)
                else:
                    from .mochi import MochiClient, MochiSync
                    from .renderer import RenderIntent
                    cards = _card_store(user["dir"])
                    graph = _graph_store(user["dir"])
                    mochi_client = MochiClient(mochi_key)
                    syncer = MochiSync(
                        mochi_client,
                        cards,
                        graph,
                        map_path=user["dir"] / "mochi_map.json",
                    )

                    loop = asyncio.get_running_loop()

                    def _run_sync():
                        return syncer.sync(RenderIntent.FULL, dry_run=False)

                    stats = await loop.run_in_executor(None, _run_sync)
                    logger.info(
                        "[%s] Mochi Sync: %d created, %d updated, %d deleted",
                        uid, stats["created"], stats["updated"], stats["deleted"],
                    )
            except Exception as e:
                logger.error("[%s] Step 4 (Mochi Sync) failed: %s", uid, e, exc_info=True)

            logger.info("[%s] Pipeline completed.", uid)

        except Exception as e:
            logger.error("[%s] Pipeline unexpected error: %s", uid, e, exc_info=True)


@app.post("/api/pipeline")
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
@app.post("/api/translate/quick", response_model=QuickTranslateResponse)
def translate_quick(req: TranslateRequest, user: dict = Depends(get_current_user)):
    """Perform a quick UI translation via Gemini API (proxy)."""
    _require_pro_access(user, "reader_ai")
    client = _gemini_client()
    prompt = f'''英→繁中。給出翻譯、詞性、字典原形（lemma）。
詞性限定: n. / v. / adj. / adv. / conj. / prep.
字: "{req.word}"
句: "{req.context[:300]}"

lemma（r）規則：
- 必須是合法英文字，可在字典查到
- 禁止跨詞性（形容詞 lemma 仍是形容詞，非其衍生名詞）
- 動詞屈折形→動詞原形（例：hurrying→hurry, gazed→gaze）
- 名詞複數→單數（例：berries→berry）；無單數形式則回傳原字
- 形容詞/副詞若本身即原形，r 回傳原字
- 不確定時 r 回傳原字；絕不捏造不存在的英文字

輸出純 JSON（無 Markdown）：{{ "t": "...", "p": "...", "r": "..." }}'''

    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash-lite",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        if not response.choices:
            logger.error("translate/quick: Gemini returned empty choices. Full response: %s", response)
            raise HTTPException(500, "Gemini returned empty response")
        if response.usage:
            from .token_tracker import record as _track
            _track(user["id"], "translate_quick",
                   getattr(response.usage, "prompt_tokens", 0) or 0,
                   getattr(response.usage, "completion_tokens", 0) or 0)
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        if isinstance(data, list):
            data = data[0] if data else {}
        return QuickTranslateResponse(
            t=data.get("t", ""),
            p=data.get("p"),
            r=data.get("r"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("translate/quick failed: %s", e, exc_info=True)
        raise HTTPException(500, f"Quick translation failed: {e}")

@app.post("/api/translate/phrase", response_model=dict)
def translate_phrase(req: TranslateRequest, user: dict = Depends(get_current_user)):
    """Translate a multi-word phrase or expression. Returns translation only."""
    _require_pro_access(user, "reader_ai")
    client = _gemini_client()
    prompt = f'''將以下英文片語/短語翻譯成繁體中文，給出最精確的中文對應。
片語: "{req.word}"
語境句子: "{req.context[:300]}"
輸出純 JSON（無 Markdown）：{{ "t": "..." }}'''

    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash-lite",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        if response.usage:
            from .token_tracker import record as _track
            _track(user["id"], "translate_phrase",
                   getattr(response.usage, "prompt_tokens", 0) or 0,
                   getattr(response.usage, "completion_tokens", 0) or 0)
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        if isinstance(data, list):
            data = data[0] if data else {}
        return {"t": data.get("t", "")}
    except Exception as e:
        raise HTTPException(500, f"Phrase translation failed: {e}")

@app.post("/api/translate/explain", response_model=ExplainResponse)
def translate_explain(req: TranslateRequest, user: dict = Depends(get_current_user)):
    """Generate a 1-2 sentence context explanation via Gemini API (proxy)."""
    _require_pro_access(user, "reader_ai")
    client = _gemini_client()
    prompt = f'''用繁體中文簡短說明「{req.word}」在以下語境中的含義（1-2句）。
語境: "{req.context[:300]}"
請以純 JSON 格式回答，包含一個 key: "e" 為解釋內容。不要包含任何 Markdown 標記，直接輸出 {{ "e": "..." }}'''

    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash-lite",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        if response.usage:
            from .token_tracker import record as _track
            _track(user["id"], "translate_explain",
                   getattr(response.usage, "prompt_tokens", 0) or 0,
                   getattr(response.usage, "completion_tokens", 0) or 0)
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        if isinstance(data, list):
            data = data[0] if data else {}
        return ExplainResponse(e=data.get("e", ""))
    except Exception as e:
        raise HTTPException(500, f"Explanation failed: {e}")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _create_jwt_token(user_id: str, provider: str) -> str:
    """Create a JWT access token."""
    now = datetime.now(tz=timezone.utc)
    expires = now + timedelta(minutes=JWT_EXPIRY_MINUTES)

    payload = {
        "sub": user_id,
        "provider": provider,
        "iat": now,
        "exp": expires,
    }

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _resolve_and_link_user(provider_user_id: str, provider: str, email: str | None = None) -> str:
    """Resolve and link user accounts by email. Returns canonical user_id."""
    with FileLock(str(USERS_LOCK_FILE)):
        users = load_users()

        # Ensure _email_index exists
        if "_email_index" not in users:
            users["_email_index"] = {}

        canonical_id = None
        now = datetime.now(tz=timezone.utc).isoformat()

        # Case 1: Email exists and is in index → account merge
        if email and email in users["_email_index"]:
            canonical_id = users["_email_index"][email]

            # If this is a different provider, link it
            if canonical_id != provider_user_id:
                # Ensure linked_ids list exists in canonical user
                if "linked_ids" not in users[canonical_id]:
                    users[canonical_id]["linked_ids"] = []

                # Add provider_user_id to linked accounts if not already there
                if provider_user_id not in users[canonical_id]["linked_ids"]:
                    users[canonical_id]["linked_ids"].append(provider_user_id)

                # Create stub entry for provider_user_id pointing to canonical
                if provider_user_id not in users:
                    users[provider_user_id] = {}
                users[provider_user_id]["_linked_to"] = canonical_id

        # Case 2: No email or email not in index → use provider_user_id as canonical
        else:
            canonical_id = provider_user_id
            if canonical_id not in users:
                users[canonical_id] = {}

            # Add email to index if present
            if email:
                users["_email_index"][email] = canonical_id

        # Update canonical user metadata
        if canonical_id not in users:
            users[canonical_id] = {}

        users[canonical_id].update({
            "provider": provider,
            "email": email,
            "last_login": now,
        })

        revoked_before = users.get("_revoked_before")
        if isinstance(revoked_before, dict):
            revoked_before.pop(canonical_id, None)
            revoked_before.pop(provider_user_id, None)
            if not revoked_before:
                users.pop("_revoked_before", None)

        save_users(users)
        return canonical_id


@app.post("/auth/verify", response_model=AuthVerifyResponse)
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

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


def _check_admin(token: str | None):
    if not ADMIN_TOKEN:
        raise HTTPException(403, "ADMIN_TOKEN not configured")
    if token != ADMIN_TOKEN:
        raise HTTPException(403, "Forbidden")


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_ui(token: str | None = None):
    """Admin dashboard UI."""
    _check_admin(token)
    return HTMLResponse(ADMIN_HTML)


@app.get("/api/admin/stats", include_in_schema=False)
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


@app.get("/api/admin/logs", include_in_schema=False)
def admin_logs(token: str | None = None, n: int = 200, level: str | None = None):
    """Return recent in-memory log entries for the admin dashboard."""
    _check_admin(token)
    return {"logs": _mem_log.get(n=n, level=level or None)}


_LAST_TEST_RUN: dict[str, Any] | None = None
_CASE_LINE_RE = re.compile(
    r"^(?P<case>tests/\S+::\S+)\s+(?P<status>PASSED|FAILED|ERROR|SKIPPED|XFAILED|XPASSED)\b"
)
_TEST_MATRIX_COLUMNS = ["Unit", "Integration", "Robustness", "Contract"]
_TEST_MATRIX_ITEMS: list[dict[str, Any]] = [
    {
        "id": "renderer_truncation",
        "domain": "Rendering",
        "column": "Unit",
        "label": "Renderer Truncation",
        "summary": "Fast renderer-only check for text truncation behavior.",
        "nodeids": ["tests/test_renderer_truncation.py"],
    },
    {
        "id": "vocab_graph",
        "domain": "Vocab/Graph",
        "column": "Integration",
        "label": "Vocab + Graph API",
        "summary": "Covers vocab lifecycle sync and graph-link API behavior together.",
        "nodeids": [
            "tests/test_api_surface.py::test_vocab_lifecycle_and_since_sync",
            "tests/test_api_surface.py::test_graph_links_returns_active_only",
        ],
    },
    {
        "id": "translate_contract",
        "domain": "Vocab/Graph",
        "column": "Contract",
        "label": "Translate API Contract",
        "summary": "Checks response shape and error handling for translate endpoints.",
        "nodeids": ["tests/test_api_surface.py::test_translate_endpoints_success_and_error"],
    },
    {
        "id": "auth_linking",
        "domain": "User/Auth",
        "column": "Integration",
        "label": "Auth Linking",
        "summary": "Validates Google and Apple identity linking on the same user.",
        "nodeids": ["tests/test_api_surface.py::test_auth_verify_links_google_and_apple_by_email"],
    },
    {
        "id": "account_robustness",
        "domain": "User/Auth",
        "column": "Robustness",
        "label": "Config + Account Robustness",
        "summary": "Stresses config persistence, account deletion, and integrity behavior.",
        "nodeids": [
            "tests/test_robustness.py::TestBatchA_UsersJsonLock",
            "tests/test_robustness.py::TestBatchA_AccountDeletion",
        ],
    },
    {
        "id": "storage_backfill",
        "domain": "Storage",
        "column": "Integration",
        "label": "Embedding Backfill",
        "summary": "Verifies cards without embeddings are detected and backfilled correctly.",
        "nodeids": ["tests/test_robustness.py::TestBatchC_EmbeddingBackfill"],
    },
    {
        "id": "storage_atomicity",
        "domain": "Storage",
        "column": "Robustness",
        "label": "Mochi + CardStore Atomicity",
        "summary": "Protects atomic writes, counts, and migration behavior for stored data.",
        "nodeids": [
            "tests/test_robustness.py::TestBatchB_MochiAtomicStorage",
            "tests/test_robustness.py::TestBatchC_CardStoreCount",
        ],
    },
    {
        "id": "pipeline_locking",
        "domain": "Pipeline",
        "column": "Robustness",
        "label": "Pipeline Locking",
        "summary": "Checks per-user lock creation and skip behavior under contention.",
        "nodeids": ["tests/test_robustness.py::TestBatchD_UserLockAtomic"],
    },
    {
        "id": "admin_contract",
        "domain": "Admin",
        "column": "Contract",
        "label": "Admin Endpoints",
        "summary": "Confirms admin token enforcement and test-matrix APIs stay intact.",
        "nodeids": [
            "tests/test_api_surface.py::test_admin_endpoints_enforce_token_and_return_stats",
            "tests/test_api_surface.py::test_admin_test_matrix_endpoints",
        ],
    },
    {
        "id": "auth_contract",
        "domain": "User/Auth",
        "column": "Contract",
        "label": "Auth API Contract",
        "summary": "Checks auth verify payload shape and revoked-token rejection behavior.",
        "nodeids": [
            "tests/test_api_surface.py::test_auth_verify_response_contract",
            "tests/test_api_surface.py::test_revoked_token_rejected",
        ],
    },
    {
        "id": "vocab_concurrent",
        "domain": "Vocab/Graph",
        "column": "Robustness",
        "label": "Vocab Concurrent Write",
        "summary": "Stresses concurrent vocab writes to catch lost-update issues.",
        "nodeids": ["tests/test_robustness.py::TestBatchE_VocabConcurrentWrite"],
    },
    {
        "id": "pipeline_integration",
        "domain": "Pipeline",
        "column": "Integration",
        "label": "Pipeline Integration",
        "summary": "Runs pipeline flow end-to-end and checks response schema coverage.",
        "nodeids": ["tests/test_pipeline_integration.py::TestPipelineIntegration"],
    },
]
_TEST_MATRIX_ITEM_MAP = {item["id"]: item for item in _TEST_MATRIX_ITEMS}


def _bucket_status(status: str) -> str:
    s = status.upper()
    if s in {"FAILED", "XPASSED"}:
        return "failed"
    if s == "ERROR":
        return "errors"
    if s in {"SKIPPED", "XFAILED"}:
        return "skipped"
    return "passed"


def _selected_nodeids(item_ids: list[str]) -> list[str]:
    nodeids: list[str] = []
    seen: set[str] = set()
    for item_id in item_ids:
        item = _TEST_MATRIX_ITEM_MAP.get(item_id)
        if not item:
            continue
        for nodeid in item["nodeids"]:
            if nodeid not in seen:
                nodeids.append(nodeid)
                seen.add(nodeid)
    return nodeids


def _item_results(cases: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_item: list[dict[str, Any]] = []
    for item in _TEST_MATRIX_ITEMS:
        matched = [c for c in cases if any(c["id"].startswith(prefix) for prefix in item["nodeids"])]
        counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
        for c in matched:
            counts[c["bucket"]] += 1
        if not matched:
            status = "not_run"
        elif counts["failed"] > 0 or counts["errors"] > 0:
            status = "failed"
        elif counts["passed"] > 0:
            status = "passed"
        else:
            status = "skipped"
        by_item.append({
            "id": item["id"],
            "status": status,
            "counts": counts,
            "total": len(matched),
        })
    return by_item


def _build_test_catalog() -> dict[str, Any]:
    domains = list(dict.fromkeys(item["domain"] for item in _TEST_MATRIX_ITEMS))
    rows: list[dict[str, Any]] = []
    for domain in domains:
        row_cells: list[dict[str, Any] | None] = []
        for column in _TEST_MATRIX_COLUMNS:
            cell = next(
                (item for item in _TEST_MATRIX_ITEMS if item["domain"] == domain and item["column"] == column),
                None,
            )
            row_cells.append(cell)
        rows.append({"domain": domain, "cells": row_cells})
    return {"columns": _TEST_MATRIX_COLUMNS, "rows": rows, "items": _TEST_MATRIX_ITEMS}


def _run_pytest_matrix(selected_items: list[str] | None = None) -> dict[str, Any]:
    """Run pytest and build matrix data grouped by test module."""
    project_root = Path(__file__).resolve().parent.parent.parent
    started = datetime.now(tz=timezone.utc)
    run_id = started.strftime("%Y%m%d%H%M%S")
    tests_dir = project_root / "tests"
    selected_items = selected_items or []
    nodeids = _selected_nodeids(selected_items)

    if not tests_dir.exists():
        finished = datetime.now(tz=timezone.utc)
        return {
            "runId": run_id,
            "startedAt": started.isoformat(),
            "finishedAt": finished.isoformat(),
            "durationSeconds": round((finished - started).total_seconds(), 3),
            "returnCode": 127,
            "outcome": "failed",
            "totals": {"passed": 0, "failed": 0, "errors": 1, "skipped": 0, "total": 1},
            "matrix": [],
            "cases": [],
            "selectedItems": selected_items,
            "itemResults": _item_results([]),
            "stdoutTail": [],
            "stderrTail": [f"tests directory not found at {tests_dir}"],
        }

    cmd = [sys.executable, "-m", "pytest", "-vv", "--maxfail=0", "--disable-warnings"]
    if nodeids:
        cmd.extend(nodeids)
    else:
        cmd.append("tests")

    try:
        proc = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ, "PY_COLORS": "0"},
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        return_code = proc.returncode
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ""
        stderr = e.stderr or ""
        return_code = 124
    except Exception as e:
        finished = datetime.now(tz=timezone.utc)
        return {
            "runId": run_id,
            "startedAt": started.isoformat(),
            "finishedAt": finished.isoformat(),
            "durationSeconds": round((finished - started).total_seconds(), 3),
            "returnCode": 127,
            "outcome": "failed",
            "totals": {"passed": 0, "failed": 0, "errors": 1, "skipped": 0, "total": 1},
            "matrix": [],
            "cases": [],
            "selectedItems": selected_items,
            "itemResults": _item_results([]),
            "stdoutTail": [],
            "stderrTail": [f"{type(e).__name__}: {e}"],
        }

    finished = datetime.now(tz=timezone.utc)
    duration = round((finished - started).total_seconds(), 3)

    cases: list[dict[str, str]] = []
    matrix: dict[str, dict[str, Any]] = {}
    for line in (stdout + "\n" + stderr).splitlines():
        m = _CASE_LINE_RE.match(line.strip())
        if not m:
            continue
        case_id = m.group("case")
        status = m.group("status")
        module = case_id.split("::", 1)[0]
        bucket = _bucket_status(status)
        cases.append({
            "id": case_id,
            "module": module,
            "status": status,
            "bucket": bucket,
        })
        if module not in matrix:
            matrix[module] = {
                "module": module,
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "total": 0,
            }
        matrix[module][bucket] += 1
        matrix[module]["total"] += 1

    matrix_rows = sorted(matrix.values(), key=lambda row: row["module"])
    totals = {
        "passed": sum(r["passed"] for r in matrix_rows),
        "failed": sum(r["failed"] for r in matrix_rows),
        "errors": sum(r["errors"] for r in matrix_rows),
        "skipped": sum(r["skipped"] for r in matrix_rows),
    }
    totals["total"] = totals["passed"] + totals["failed"] + totals["errors"] + totals["skipped"]

    outcome = "passed" if return_code == 0 else "failed"
    return {
        "runId": run_id,
        "startedAt": started.isoformat(),
        "finishedAt": finished.isoformat(),
        "durationSeconds": duration,
        "returnCode": return_code,
        "outcome": outcome,
        "totals": totals,
        "selectedItems": selected_items,
        "matrix": matrix_rows,
        "cases": cases,
        "itemResults": _item_results(cases),
        "stdoutTail": (stdout.splitlines()[-60:] if stdout else []),
        "stderrTail": (stderr.splitlines()[-60:] if stderr else []),
    }


@app.post("/api/admin/tests/run", include_in_schema=False)
def admin_run_tests(req: AdminTestRunRequest | None = None, token: str | None = None):
    """Run test suite and return matrix view data."""
    _check_admin(token)
    global _LAST_TEST_RUN
    selected = req.itemIds if req else []
    _LAST_TEST_RUN = _run_pytest_matrix(selected_items=selected)
    return _LAST_TEST_RUN


@app.get("/api/admin/tests/last", include_in_schema=False)
def admin_last_test_run(token: str | None = None):
    """Get latest test run result for matrix page."""
    _check_admin(token)
    if _LAST_TEST_RUN is None:
        return {"status": "idle"}
    return _LAST_TEST_RUN


@app.get("/api/admin/tests/catalog", include_in_schema=False)
def admin_test_catalog(token: str | None = None):
    """Return clickable test-matrix catalog."""
    _check_admin(token)
    return _build_test_catalog()



@app.get("/admin/tests", response_class=HTMLResponse, include_in_schema=False)
def admin_tests_ui(token: str | None = None):
    """Minimal grayscale test matrix dashboard."""
    _check_admin(token)
    return HTMLResponse(ADMIN_TESTS_HTML)
