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
    if not USERS_FILE.exists():
        return {}
    data = json.loads(USERS_FILE.read_text())
    normalized, _ = _normalize_users_payload(data)
    return normalized

def save_users(users: dict[str, dict[str, Any]]) -> None:
    normalized, _ = _normalize_users_payload(users)
    tmp_path = USERS_FILE.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(normalized, indent=2))
    tmp_path.replace(USERS_FILE)


def _normalize_users_payload(users: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    normalized: dict[str, Any] = {}

    for user_id, record in users.items():
        if not isinstance(record, dict) or user_id.startswith("_"):
            normalized[user_id] = record
            continue

        normalized_record = dict(record)
        had_config = isinstance(normalized_record.get("config"), dict)
        config = dict(normalized_record.get("config", {})) if had_config else {}
        legacy_mochi_key = normalized_record.pop("mochi_api_key", None)
        subscription = normalized_record.get("subscription")

        if "mochi_api_key" in record:
            changed = True
            if isinstance(legacy_mochi_key, str):
                legacy_mochi_key = legacy_mochi_key.strip()
            if legacy_mochi_key and not config.get("mochi_api_key"):
                config["mochi_api_key"] = legacy_mochi_key

        if had_config or config:
            if normalized_record.get("config") != config:
                changed = True
            normalized_record["config"] = config
        elif "config" in normalized_record:
            normalized_record.pop("config", None)
            changed = True

        if subscription is not None:
            if isinstance(subscription, dict):
                normalized_subscription = _default_subscription_payload()
                normalized_subscription.update(subscription)
                if normalized_subscription != subscription:
                    changed = True
                normalized_record["subscription"] = normalized_subscription
            else:
                normalized_record.pop("subscription", None)
                changed = True

        normalized[user_id] = normalized_record

    return normalized, changed

def _parse_datetime(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            try:
                return datetime.fromtimestamp(float(raw), tz=timezone.utc)
            except ValueError:
                return None
    return None

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
    """Return canonical id + all related ids that must be purged."""
    record = users.get(user_id, {})
    canonical_id = user_id
    if isinstance(record, dict):
        linked_to = record.get("_linked_to")
        if isinstance(linked_to, str) and linked_to:
            canonical_id = linked_to

    ids: set[str] = {canonical_id, user_id}
    canonical_record = users.get(canonical_id, {})
    if isinstance(canonical_record, dict):
        linked_ids = canonical_record.get("linked_ids", [])
        if isinstance(linked_ids, list):
            ids.update(uid for uid in linked_ids if isinstance(uid, str) and uid)

    for uid, info in users.items():
        if uid.startswith("_"):
            continue
        if isinstance(info, dict) and info.get("_linked_to") == canonical_id:
            ids.add(uid)

    return canonical_id, sorted(ids)


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

_ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WordNexus Admin</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Noto+Sans+TC:wght@300;400&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #f8f7f4;
  --surface: #fcfbfa;
  --border: #dbd6cd;
  --border-l: #e8e4db;
  --ink: #2a2520;
  --sub: #7a756c;
  --ink-light: #5a5550;
  --dev: #c0392b;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Noto Sans TC', sans-serif;
  background: var(--bg);
  color: var(--ink);
  font-size: 14px;
  line-height: 1.86;
  min-height: 100vh;
}
/* Top nav */
.nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  height: 52px;
  padding: 0 16px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 10;
}
.brand {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  letter-spacing: .12em;
  text-transform: uppercase;
  white-space: nowrap;
}
.dev-dot {
  margin-left: 8px;
  color: var(--dev);
  border: 1px solid var(--dev);
  padding: 1px 5px;
  border-radius: 2px;
  font-size: 10px;
}
.nav-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
#ts {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--sub);
  letter-spacing: .08em;
  text-transform: uppercase;
}
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: transparent;
  color: var(--ink-light);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: .10em;
  text-transform: uppercase;
  text-decoration: none;
  cursor: pointer;
  white-space: nowrap;
}
.btn:hover { border-color: var(--ink); color: var(--ink); }
.btn-cta {
  height: 48px;
  padding: 0 16px;
  border: 1px solid var(--ink);
  background: var(--ink);
  color: #fff;
  letter-spacing: .12em;
  transition: transform .12s ease, box-shadow .12s ease;
}
.btn-cta:hover {
  transform: translateY(-2px);
  box-shadow: 0 5px 0 rgba(42, 37, 32, .25);
}
/* Tabs */
.tabs {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.tab {
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: transparent;
  color: var(--ink-light);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: .08em;
  text-transform: uppercase;
  display: inline-flex;
  align-items: center;
  cursor: pointer;
}
.tab.active {
  background: var(--ink);
  border-color: var(--ink);
  color: #fff;
}
/* Main layout */
.main {
  max-width: 1320px;
  padding: 16px;
  margin: 0 auto 42px;
}
/* Panel */
.panel { display: none; }
.panel.active { display: block; }
/* Section title */
.section-title {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: .14em;
  margin-bottom: 12px;
}
/* Stat cards */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 8px;
  margin-bottom: 24px;
}
.stat {
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--surface);
  padding: 10px 12px;
}
.stat .v {
  font-family: 'JetBrains Mono', monospace;
  font-size: 24px;
  line-height: 1.2;
  letter-spacing: .04em;
  color: var(--ink);
}
.stat .l {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--sub);
  margin-top: 2px;
  letter-spacing: .12em;
  text-transform: uppercase;
}
/* Table */
.table-wrap {
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--surface);
  overflow-x: auto;
}
table { width: 100%; border-collapse: collapse; }
thead { background: #f3f0ea; }
th {
  text-align: left;
  padding: 9px 12px;
  border-right: 1px solid var(--border-l);
  border-bottom: 1px solid var(--border-l);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--sub);
  white-space: nowrap;
  letter-spacing: .08em;
  text-transform: uppercase;
}
th:last-child, td:last-child { border-right: 0; }
td {
  padding: 10px 12px;
  border-right: 1px solid var(--border-l);
  border-bottom: 1px solid var(--border-l);
  vertical-align: top;
}
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover td { background: #f6f4ef; }
.uid { color: var(--ink); }
.email { font-size: 12px; color: var(--sub); margin-top: 2px; }
.badge {
  display: inline-block;
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 1px 7px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--ink-light);
}
.b-apple, .b-google, .b-manual { background: transparent; }
.mochi-yes { color: var(--ink); }
.mochi-no  { color: var(--sub); }
.bar-wrap { display: flex; align-items: center; gap: 8px; }
.bar {
  flex: 1;
  height: 5px;
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: 3px;
  overflow: hidden;
  min-width: 64px;
}
.bar-fill { height: 100%; background: var(--ink-light); transition: width .3s ease; }
.bar-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--sub);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.cost {
  font-family: 'JetBrains Mono', monospace;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.chip {
  display: inline-flex; align-items: center; gap: 5px;
  border: 1px solid var(--border); border-radius: 2px;
  padding: 3px 8px; font-size: 11px; white-space: nowrap;
}
.chip-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ink-light);
  flex-shrink: 0;
}
.chip-name {
  font-family: 'JetBrains Mono', monospace;
  color: var(--sub);
  font-size: 10px;
}
.chip-val  {
  font-family: 'JetBrains Mono', monospace;
  color: var(--ink);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}
.chip-calls {
  font-family: 'JetBrains Mono', monospace;
  color: var(--sub);
  font-size: 10px;
}
.no-data {
  color: var(--sub);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: .05em;
}
/* Log panel */
.log-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.log-filter-group { display: flex; gap: 4px; }
.log-filter {
  height: 30px;
  padding: 0 10px;
  border-radius: 2px;
  border: 1px solid var(--border);
  background: transparent;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  cursor: pointer;
  color: var(--ink-light);
  letter-spacing: .08em;
  text-transform: uppercase;
}
.log-filter.active { background: var(--ink); color: #fff; border-color: var(--ink); }
.log-search {
  flex: 1;
  min-width: 180px;
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: 2px;
  font-size: 13px;
  font-family: 'Noto Sans TC', sans-serif;
  color: var(--ink);
  outline: none;
  background: var(--surface);
}
.log-search:focus { border-color: var(--ink); }
.log-sep { flex: 1; }
.log-auto {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--sub);
  cursor: pointer;
  user-select: none;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.log-auto input { cursor: pointer; }
.log-box {
  border: 1px solid var(--border);
  border-radius: 3px;
  overflow-y: auto;
  height: 500px;
  background: var(--surface);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11.5px;
  line-height: 1.6;
}
.log-entry {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 5px 14px;
  border-bottom: 1px solid var(--border-l);
}
.log-entry:last-child { border-bottom: none; }
.log-entry:hover { background: #f6f4ef; }
.log-ts { color: var(--sub); flex-shrink: 0; font-size: 10.5px; }
.log-lv {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 500;
  padding: 1px 5px;
  border: 1px solid var(--border);
  border-radius: 2px;
  letter-spacing: .08em;
  color: var(--ink-light);
  text-transform: uppercase;
  background: transparent;
}
.log-name {
  color: var(--sub);
  flex-shrink: 0;
  font-size: 10.5px;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.log-msg { color: var(--ink); word-break: break-all; }
.log-empty {
  padding: 40px;
  text-align: center;
  color: var(--sub);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: .08em;
}
/* Loading */
#loading {
  color: var(--sub);
  padding: 30px 16px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: .10em;
  text-transform: uppercase;
}
</style>
</head>
<body>

<div class="nav">
  <div class="brand">
    WordNexus Admin <span class="dev-dot">DEV</span>
  </div>
  <div class="nav-actions">
    <span id="ts"></span>
    <a class="btn" id="admin-tests-link" href="/admin/tests?token=">Admin Test</a>
    <button class="btn btn-cta" onclick="refreshCurrent()">Refresh</button>
  </div>
</div>

<div class="tabs">
  <div class="tab active" data-tab="users" onclick="switchTab('users')">Users</div>
  <div class="tab" data-tab="logs" onclick="switchTab('logs')">Logs</div>
</div>

<div id="loading">載入中…</div>

<div id="app" class="main" style="display:none">

  <!-- ── Users panel ── -->
  <div class="panel active" id="panel-users">
    <div class="section-title">總覽</div>
    <div class="stats" id="summary"></div>
    <div class="section-title">用戶明細</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>用戶</th><th>Provider</th><th>最後登入</th>
          <th>單字數</th><th>Mochi</th>
          <th>Token 用量</th><th>預估費用</th><th>各功能明細</th>
        </tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
  </div>

  <!-- ── Logs panel ── -->
  <div class="panel" id="panel-logs">
    <div class="log-toolbar">
      <div class="log-filter-group">
        <button class="log-filter active" data-lv="" onclick="setFilter(this,'')">ALL</button>
        <button class="log-filter" data-lv="INFO" onclick="setFilter(this,'INFO')">INFO</button>
        <button class="log-filter" data-lv="WARNING" onclick="setFilter(this,'WARNING')">WARN</button>
        <button class="log-filter" data-lv="ERROR" onclick="setFilter(this,'ERROR')">ERROR</button>
      </div>
      <input class="log-search" id="log-search" type="text" placeholder="搜尋…" oninput="renderLogs()">
      <div class="log-sep"></div>
      <label class="log-auto">
        <input type="checkbox" id="log-auto" onchange="toggleAuto(this)"> 自動刷新
      </label>
    </div>
    <div class="log-box" id="log-box"></div>
  </div>

</div>

<script>
const TOKEN = new URLSearchParams(location.search).get('token') || '';
document.getElementById('admin-tests-link').href = '/admin/tests?token=' + encodeURIComponent(TOKEN);
let _tab = 'users';
let _logLevel = '';
let _logs = [];
let _autoTimer = null;

/* ── Tabs ── */
function switchTab(tab) {
  _tab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + tab));
  if (tab === 'logs') loadLogs();
}

function refreshCurrent() {
  if (_tab === 'users') loadStats();
  else loadLogs();
}

/* Stats */
function fmt(n) {
  n = n || 0;
  if (n >= 1e6) return (n/1e6).toFixed(2)+'M';
  if (n >= 1000) return (n/1000).toFixed(1)+'k';
  return n.toLocaleString();
}
function fmtDate(iso) {
  if (!iso) return '<span class="mochi-no">—</span>';
  return new Date(iso).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
}

async function loadStats() {
  document.getElementById('loading').style.display = '';
  document.getElementById('app').style.display = 'none';
  try {
    const r = await fetch('/api/admin/stats?token=' + TOKEN);
    if (!r.ok) { document.getElementById('loading').textContent='Error '+r.status+': '+await r.text(); return; }
    renderStats(await r.json());
    stamp();
  } catch(e) { document.getElementById('loading').textContent='Error: '+e; }
}

function renderStats(data) {
  document.getElementById('loading').style.display = 'none';
  document.getElementById('app').style.display = '';
  const ti=data.users.reduce((s,u)=>s+u.total_input,0);
  const to=data.users.reduce((s,u)=>s+u.total_output,0);
  const tc=data.users.reduce((s,u)=>s+u.est_cost_usd,0);
  const tv=data.users.reduce((s,u)=>s+u.vocab_count,0);
  document.getElementById('summary').innerHTML=`
    <div class="stat"><div class="v">${data.users.length}</div><div class="l">用戶數</div></div>
    <div class="stat"><div class="v">${tv.toLocaleString()}</div><div class="l">總單字數</div></div>
    <div class="stat"><div class="v">${fmt(ti+to)}</div><div class="l">總 Token 用量</div></div>
    <div class="stat"><div class="v">${fmt(ti)}</div><div class="l">輸入 tokens</div></div>
    <div class="stat"><div class="v">${fmt(to)}</div><div class="l">輸出 tokens</div></div>
    <div class="stat"><div class="v">$${tc.toFixed(4)}</div><div class="l">預估費用 USD</div></div>`;
  const maxTok=Math.max(...data.users.map(u=>u.total_input+u.total_output),1);
  document.getElementById('rows').innerHTML=data.users.map(u=>{
    const pc=u.provider||'manual';
    const total=u.total_input+u.total_output;
    const pct=Math.round((total/maxTok)*100);
    const chips=Object.entries(u.tokens||{}).map(([t,d])=>{
      return `<span class="chip"><span class="chip-dot"></span><span class="chip-name">${t.replace('translate_','tr.')}</span><span class="chip-val">${fmt(d.input_tokens)}↑${fmt(d.output_tokens)}↓</span><span class="chip-calls">×${d.calls}</span></span>`;
    }).join('');
    return `<tr>
      <td><div class="uid">${u.user_id}</div>${u.email?`<div class="email">${u.email}</div>`:''}</td>
      <td><span class="badge b-${pc}">${pc}</span></td>
      <td style="color:var(--ink-light);font-size:12px">${fmtDate(u.last_login)}</td>
      <td style="font-variant-numeric:tabular-nums">${u.vocab_count.toLocaleString()}</td>
      <td>${u.has_mochi?'<span class="mochi-yes">✓</span>':'<span class="mochi-no">—</span>'}</td>
      <td style="min-width:160px">
        <div class="bar-wrap"><div class="bar"><div class="bar-fill" style="width:${pct}%"></div></div><span class="bar-label">${fmt(total)}</span></div>
        <div style="font-size:11px;color:var(--sub);margin-top:3px">${fmt(u.total_input)}↑ / ${fmt(u.total_output)}↓</div>
      </td>
      <td class="cost">$${u.est_cost_usd.toFixed(4)}</td>
      <td><div class="chips">${chips||'<span class="no-data">無紀錄</span>'}</div></td>
    </tr>`;
  }).join('');
}

/* ── Logs ── */
function setFilter(btn, lv) {
  _logLevel = lv;
  document.querySelectorAll('.log-filter').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderLogs();
}

function toggleAuto(cb) {
  if (_autoTimer) { clearInterval(_autoTimer); _autoTimer = null; }
  if (cb.checked) { _autoTimer = setInterval(loadLogs, 3000); }
}

async function loadLogs() {
  try {
    const r = await fetch('/api/admin/logs?token=' + TOKEN + '&n=300');
    if (!r.ok) return;
    _logs = (await r.json()).logs;
    renderLogs();
    stamp();
  } catch(e) {}
}

function renderLogs() {
  const q = document.getElementById('log-search').value.toLowerCase();
  const box = document.getElementById('log-box');
  let rows = _logs;
  if (_logLevel) rows = rows.filter(r => r.level === _logLevel);
  if (q) rows = rows.filter(r => r.msg.toLowerCase().includes(q) || r.name.toLowerCase().includes(q));
  if (!rows.length) { box.innerHTML = '<div class="log-empty">無符合的日誌</div>'; return; }
  box.innerHTML = [...rows].reverse().map(r =>
    `<div class="log-entry lv-${r.level}">
      <span class="log-ts">${r.ts}</span>
      <span class="log-lv">${r.level}</span>
      <span class="log-name" title="${r.name}">${r.name.replace('kg.','')}</span>
      <span class="log-msg">${r.msg.replace(/</g,'&lt;')}</span>
    </div>`
  ).join('');
}

function stamp() {
  document.getElementById('ts').textContent = '更新於 ' + new Date().toLocaleTimeString('zh-TW', { hour12: false });
}

loadStats();
</script>
</body>
</html>"""


def _check_admin(token: str | None):
    if not ADMIN_TOKEN:
        raise HTTPException(403, "ADMIN_TOKEN not configured")
    if token != ADMIN_TOKEN:
        raise HTTPException(403, "Forbidden")


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_ui(token: str | None = None):
    """Admin dashboard UI."""
    _check_admin(token)
    return HTMLResponse(_ADMIN_HTML)


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


_ADMIN_TESTS_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>KG Test Matrix</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Noto+Sans+TC:wght@300;400;500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #f4f1eb;
      --surface: rgba(255, 252, 247, .92);
      --surface-strong: #fffdfa;
      --border: #d8d0c2;
      --border-light: #e8e1d6;
      --ink: #241f19;
      --ink-soft: #5d554b;
      --sub: #7c7266;
      --accent: #8a5a26;
      --accent-soft: rgba(138, 90, 38, .10);
      --passed: #256246;
      --passed-soft: rgba(37, 98, 70, .10);
      --failed: #a7372a;
      --failed-soft: rgba(167, 55, 42, .10);
      --warn: #9b6b16;
      --warn-soft: rgba(155, 107, 22, .10);
      --idle: #69727d;
      --idle-soft: rgba(105, 114, 125, .10);
      --shadow: 0 18px 40px rgba(63, 47, 30, .08);
      --dev: #c0392b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "Noto Sans TC", sans-serif;
      line-height: 1.6;
      background:
        radial-gradient(circle at top left, rgba(138, 90, 38, .10), transparent 30%),
        linear-gradient(180deg, #f7f3ec 0%, var(--bg) 45%, #efe7dc 100%);
      min-height: 100vh;
    }
    button, input {
      font: inherit;
    }
    .nav {
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 18px;
      background: rgba(255, 252, 247, .84);
      backdrop-filter: blur(18px);
      border-bottom: 1px solid rgba(216, 208, 194, .75);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-family: "JetBrains Mono", monospace;
      font-size: 12px;
      letter-spacing: .12em;
      text-transform: uppercase;
    }
    .dev-dot {
      color: var(--dev);
      border: 1px solid rgba(192, 57, 43, .4);
      padding: 2px 6px;
      font-size: 10px;
      border-radius: 999px;
      background: rgba(192, 57, 43, .08);
    }
    .nav-link {
      text-decoration: none;
      color: var(--ink-soft);
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      letter-spacing: .08em;
      text-transform: uppercase;
      border: 1px solid var(--border);
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255, 255, 255, .45);
    }
    .wrap {
      max-width: 1240px;
      margin: 0 auto;
      padding: 28px 18px 56px;
    }
    .panel {
      border: 1px solid rgba(216, 208, 194, .95);
      background: var(--surface);
      border-radius: 24px;
      padding: 20px;
      box-shadow: var(--shadow);
      margin-bottom: 16px;
    }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(320px, 1fr);
      gap: 18px;
      align-items: stretch;
    }
    .eyebrow,
    .section-kicker {
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      letter-spacing: .14em;
      text-transform: uppercase;
      color: var(--sub);
    }
    .hero h1 {
      margin: 10px 0 12px;
      font-size: clamp(30px, 4vw, 46px);
      line-height: 1.04;
      letter-spacing: -.03em;
    }
    .hero p {
      margin: 0;
      color: var(--ink-soft);
      font-size: 15px;
      max-width: 66ch;
    }
    .guide {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 18px;
    }
    .guide-card {
      border: 1px solid var(--border-light);
      border-radius: 18px;
      padding: 12px 14px;
      background: rgba(255, 255, 255, .54);
    }
    .guide-card strong {
      display: block;
      margin-bottom: 6px;
      font-size: 13px;
    }
    .guide-card span {
      display: block;
      color: var(--ink-soft);
      font-size: 13px;
    }
    .hero-side {
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 14px;
      padding: 18px;
      border: 1px solid rgba(138, 90, 38, .16);
      border-radius: 20px;
      background: linear-gradient(180deg, rgba(138, 90, 38, .12) 0%, rgba(255, 255, 255, .62) 100%);
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    .cta,
    .secondary,
    .tertiary,
    .filter-btn,
    .search-input {
      border-radius: 999px;
      border: 1px solid var(--border);
    }
    .cta,
    .secondary,
    .tertiary {
      min-height: 42px;
      padding: 0 16px;
      cursor: pointer;
      transition: transform .14s ease, box-shadow .14s ease, border-color .14s ease, background .14s ease;
    }
    .cta {
      border-color: var(--ink);
      background: var(--ink);
      color: #fff;
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      letter-spacing: .12em;
      text-transform: uppercase;
      box-shadow: 0 10px 24px rgba(36, 31, 25, .18);
    }
    .secondary,
    .tertiary {
      background: rgba(255, 255, 255, .64);
      color: var(--ink-soft);
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      letter-spacing: .10em;
      text-transform: uppercase;
    }
    .cta:hover:not(:disabled),
    .secondary:hover:not(:disabled),
    .tertiary:hover:not(:disabled),
    .run-item-btn:hover:not(:disabled),
    .filter-btn:hover:not(.active) {
      transform: translateY(-1px);
      box-shadow: 0 8px 18px rgba(36, 31, 25, .08);
      border-color: var(--ink);
    }
    .cta:disabled,
    .secondary:disabled,
    .tertiary:disabled,
    .run-item-btn:disabled {
      opacity: .58;
      cursor: not-allowed;
      transform: none;
      box-shadow: none;
    }
    .status-line {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    .run-badge,
    .pill,
    .status-pill,
    .case-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      font-family: "JetBrains Mono", monospace;
      font-size: 10px;
      letter-spacing: .08em;
      text-transform: uppercase;
      border: 1px solid transparent;
      white-space: nowrap;
    }
    .run-badge.idle,
    .status-pill.idle,
    .pill.idle {
      color: var(--idle);
      background: var(--idle-soft);
      border-color: rgba(105, 114, 125, .16);
    }
    .run-badge.passed,
    .status-pill.passed,
    .pill.passed,
    .case-badge.passed {
      color: var(--passed);
      background: var(--passed-soft);
      border-color: rgba(37, 98, 70, .18);
    }
    .run-badge.failed,
    .status-pill.failed,
    .status-pill.errors,
    .pill.failed,
    .pill.errors,
    .case-badge.failed,
    .case-badge.errors {
      color: var(--failed);
      background: var(--failed-soft);
      border-color: rgba(167, 55, 42, .18);
    }
    .run-badge.skipped,
    .status-pill.skipped,
    .pill.skipped,
    .case-badge.skipped {
      color: var(--warn);
      background: var(--warn-soft);
      border-color: rgba(155, 107, 22, .18);
    }
    .pill.type {
      color: var(--accent);
      background: var(--accent-soft);
      border-color: rgba(138, 90, 38, .18);
    }
    .pill.neutral {
      color: var(--sub);
      background: rgba(124, 114, 102, .10);
      border-color: rgba(124, 114, 102, .16);
    }
    .hero-meta {
      color: var(--ink-soft);
      font-size: 14px;
    }
    .notice {
      min-height: 24px;
      color: var(--sub);
      font-size: 13px;
    }
    .notice.error {
      color: var(--failed);
    }
    .summary-grid,
    .stats,
    .module-grid,
    .check-grid,
    .output-grid {
      display: grid;
      gap: 12px;
    }
    .summary-grid {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
    .summary-card,
    .stat,
    .module-card,
    .check-card,
    .output-card {
      border: 1px solid var(--border-light);
      border-radius: 18px;
      background: rgba(255, 255, 255, .62);
    }
    .summary-card,
    .stat,
    .module-card,
    .output-card {
      padding: 14px 16px;
    }
    .summary-k,
    .stat-k {
      font-family: "JetBrains Mono", monospace;
      font-size: 10px;
      letter-spacing: .12em;
      text-transform: uppercase;
      color: var(--sub);
    }
    .summary-v,
    .stat-v {
      margin-top: 8px;
      font-family: "JetBrains Mono", monospace;
      font-size: 24px;
      letter-spacing: -.02em;
    }
    .summary-v.scope {
      font-family: "Noto Sans TC", sans-serif;
      font-size: 18px;
      line-height: 1.4;
      letter-spacing: 0;
    }
    .summary-note,
    .stat-note,
    .module-note,
    .section-copy,
    .output-note,
    .empty {
      color: var(--ink-soft);
      font-size: 13px;
    }
    .stats {
      grid-template-columns: repeat(5, minmax(0, 1fr));
      margin-top: 0;
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      margin-bottom: 16px;
    }
    .section-head h2 {
      margin: 6px 0 8px;
      font-size: 24px;
      line-height: 1.15;
      letter-spacing: -.03em;
    }
    .section-copy {
      max-width: 70ch;
    }
    .check-groups {
      display: grid;
      gap: 16px;
    }
    .domain-block {
      border: 1px solid var(--border-light);
      border-radius: 20px;
      padding: 14px;
      background: rgba(255, 255, 255, .52);
    }
    .domain-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .domain-head h3 {
      margin: 0;
      font-size: 18px;
      letter-spacing: -.02em;
    }
    .check-grid {
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    }
    .check-card {
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      min-height: 220px;
      transition: border-color .14s ease, transform .14s ease, box-shadow .14s ease;
    }
    .check-card.included {
      border-color: rgba(138, 90, 38, .28);
      box-shadow: 0 12px 24px rgba(138, 90, 38, .10);
    }
    .check-card.failed {
      border-color: rgba(167, 55, 42, .24);
    }
    .card-top,
    .card-actions,
    .filter-row,
    .search-row,
    .module-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }
    .card-title {
      margin: 0;
      font-size: 17px;
      line-height: 1.28;
      letter-spacing: -.02em;
    }
    .card-summary {
      margin: 0;
      color: var(--ink-soft);
      font-size: 13px;
      flex: 1;
    }
    .card-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .run-item-btn {
      min-height: 38px;
      padding: 0 14px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, .82);
      color: var(--ink);
      cursor: pointer;
      font-family: "JetBrains Mono", monospace;
      font-size: 10px;
      letter-spacing: .10em;
      text-transform: uppercase;
      transition: transform .14s ease, box-shadow .14s ease, border-color .14s ease;
    }
    .module-grid {
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      margin-bottom: 14px;
    }
    .module-card.alert {
      border-color: rgba(167, 55, 42, .24);
    }
    .module-name {
      font-family: "JetBrains Mono", monospace;
      font-size: 12px;
      color: var(--ink);
      word-break: break-all;
    }
    .module-metrics {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 10px;
    }
    .filter-row {
      margin-bottom: 10px;
    }
    .filter-group {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .filter-btn {
      min-height: 34px;
      padding: 0 12px;
      cursor: pointer;
      background: rgba(255, 255, 255, .72);
      color: var(--ink-soft);
      font-family: "JetBrains Mono", monospace;
      font-size: 10px;
      letter-spacing: .10em;
      text-transform: uppercase;
    }
    .filter-btn.active {
      background: var(--ink);
      color: #fff;
      border-color: var(--ink);
    }
    .search-input {
      width: min(320px, 100%);
      min-height: 40px;
      padding: 0 14px;
      background: rgba(255, 255, 255, .78);
      color: var(--ink);
      outline: none;
      font-size: 14px;
    }
    .search-input:focus {
      border-color: var(--ink);
    }
    .cases {
      display: grid;
      gap: 10px;
      max-height: 520px;
      overflow: auto;
      padding-right: 2px;
    }
    .case-row {
      border: 1px solid var(--border-light);
      border-radius: 16px;
      padding: 12px 14px;
      background: rgba(255, 255, 255, .7);
    }
    .case-row.failed,
    .case-row.errors {
      border-color: rgba(167, 55, 42, .22);
      background: rgba(167, 55, 42, .05);
    }
    .case-row.skipped {
      border-color: rgba(155, 107, 22, .22);
      background: rgba(155, 107, 22, .05);
    }
    .case-title {
      margin: 10px 0 6px;
      font-size: 15px;
      line-height: 1.35;
    }
    .case-path,
    .meta,
    .log-box {
      font-family: "JetBrains Mono", monospace;
    }
    .case-path {
      color: var(--sub);
      font-size: 11px;
      line-height: 1.5;
      word-break: break-all;
    }
    .meta {
      font-size: 11px;
      color: var(--sub);
      letter-spacing: .06em;
      text-transform: uppercase;
    }
    .output-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .log-box {
      margin-top: 12px;
      border: 1px solid var(--border-light);
      border-radius: 16px;
      background: #211c17;
      color: #f6efe6;
      padding: 14px;
      min-height: 240px;
      max-height: 340px;
      overflow: auto;
      font-size: 11.5px;
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .empty {
      padding: 24px 0;
    }
    @media (max-width: 1120px) {
      .hero,
      .summary-grid,
      .stats,
      .output-grid {
        grid-template-columns: 1fr 1fr;
      }
    }
    @media (max-width: 820px) {
      .hero,
      .summary-grid,
      .stats,
      .output-grid {
        grid-template-columns: 1fr;
      }
      .guide {
        grid-template-columns: 1fr;
      }
      .wrap {
        padding-left: 14px;
        padding-right: 14px;
      }
      .panel {
        padding: 16px;
        border-radius: 18px;
      }
      .section-head,
      .domain-head {
        flex-direction: column;
        align-items: flex-start;
      }
      .search-input {
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <div class="nav">
    <div class="brand">KG Test Matrix <span class="dev-dot">DEV</span></div>
    <a class="nav-link" href="/admin?token=" id="back-link">Admin</a>
  </div>

  <main class="wrap">
    <section class="panel hero">
      <div>
        <div class="eyebrow">Admin Test Console</div>
        <h1>先看結果，再決定要跑哪一組測試。</h1>
        <p>這個面板現在會直接告訴你目前顯示的是全量還是局部結果、哪個模組最需要注意，還能把 stdout / stderr 尾段放在同一頁，讓你不用先理解 pytest 結構才敢操作。</p>
        <div class="guide">
          <div class="guide-card">
            <strong>1. 選驗證範圍</strong>
            <span>跑完整包，或只跑某個高風險檢查卡片。</span>
          </div>
          <div class="guide-card">
            <strong>2. 看 scope 與結果</strong>
            <span>先確認你現在看到的是哪次、哪個範圍的結果。</span>
          </div>
          <div class="guide-card">
            <strong>3. 失敗先看模組</strong>
            <span>先看 module summary，再下鑽 case 與輸出尾段。</span>
          </div>
        </div>
      </div>
      <div class="hero-side">
        <div>
          <div class="section-kicker">Quick Actions</div>
          <div class="actions">
            <button id="run-all-btn" class="cta">Run Full Suite</button>
            <button id="rerun-btn" class="secondary" disabled>Rerun Last Scope</button>
            <button id="reload-btn" class="tertiary">Reload Last Result</button>
          </div>
        </div>
        <div class="status-line">
          <span id="run-badge" class="run-badge idle">Idle</span>
          <span id="meta" class="meta">尚未執行測試</span>
        </div>
        <div id="notice" class="notice">卡片上的狀態會跟著目前這一份結果更新；如果只跑局部，未包含的檢查會清楚標示。</div>
      </div>
    </section>

    <section class="panel">
      <div id="summary" class="summary-grid"></div>
    </section>

    <section class="panel">
      <div id="stats" class="stats"></div>
    </section>

    <section class="panel">
      <div class="section-head">
        <div>
          <div class="section-kicker">Choose Checks</div>
          <h2>依風險選擇測試，而不是硬看 matrix。</h2>
          <div class="section-copy">每張卡片都會告訴你它驗證哪個產品面、屬於哪種測試類型，以及在目前結果裡是否有被包含。</div>
        </div>
        <div id="catalog-meta" class="meta"></div>
      </div>
      <div id="catalog" class="check-groups">
        <div class="empty">Loading checks...</div>
      </div>
    </section>

    <section class="panel">
      <div class="section-head">
        <div>
          <div class="section-kicker">Results</div>
          <h2>先看模組，再看單一 case。</h2>
          <div class="section-copy">如果這次是局部執行，這裡只顯示該範圍內真正被跑到的模組與案例。</div>
        </div>
      </div>
      <div id="modules" class="module-grid"></div>
      <div class="filter-row">
        <div class="filter-group" id="case-filters">
          <button class="filter-btn active" data-filter="all">All</button>
          <button class="filter-btn" data-filter="errors">Errors</button>
          <button class="filter-btn" data-filter="failed">Failed</button>
          <button class="filter-btn" data-filter="skipped">Skipped</button>
          <button class="filter-btn" data-filter="passed">Passed</button>
        </div>
        <input id="case-search" class="search-input" type="text" placeholder="搜尋 case 名稱或 module..." />
      </div>
      <div id="cases" class="cases">
        <div class="empty">No case data.</div>
      </div>
    </section>

    <section class="output-grid">
      <section class="panel output-card">
        <div class="section-kicker">Stdout Tail</div>
        <div class="output-note">顯示伺服器記住的最後 60 行 stdout，適合快速看 pytest 摘要。</div>
        <pre id="stdout" class="log-box"></pre>
      </section>
      <section class="panel output-card">
        <div class="section-kicker">Stderr Tail</div>
        <div class="output-note">如果有錯誤或 traceback，會優先出現在這裡。</div>
        <pre id="stderr" class="log-box"></pre>
      </section>
    </section>
  </main>

  <script>
    const token = new URLSearchParams(location.search).get("token") || "";
    document.getElementById("back-link").href = "/admin?token=" + encodeURIComponent(token);

    const state = {
      catalog: null,
      run: null,
      caseFilter: "all",
      isBusy: false,
    };

    const runAllBtn = document.getElementById("run-all-btn");
    const rerunBtn = document.getElementById("rerun-btn");
    const reloadBtn = document.getElementById("reload-btn");
    const runBadgeEl = document.getElementById("run-badge");
    const metaEl = document.getElementById("meta");
    const noticeEl = document.getElementById("notice");
    const summaryEl = document.getElementById("summary");
    const statsEl = document.getElementById("stats");
    const catalogEl = document.getElementById("catalog");
    const catalogMetaEl = document.getElementById("catalog-meta");
    const modulesEl = document.getElementById("modules");
    const casesEl = document.getElementById("cases");
    const stdoutEl = document.getElementById("stdout");
    const stderrEl = document.getElementById("stderr");
    const caseSearchEl = document.getElementById("case-search");

    function escapeHtml(value) {
      return String(value == null ? "" : value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function getItems() {
      return (state.catalog && state.catalog.items) || [];
    }

    function getRows() {
      return (state.catalog && state.catalog.rows) || [];
    }

    function getItemById(itemId) {
      return getItems().find((item) => item.id === itemId) || null;
    }

    function getItemResultMap() {
      const map = {};
      const itemResults = (state.run && state.run.itemResults) || [];
      itemResults.forEach((item) => {
        map[item.id] = item;
      });
      return map;
    }

    function bucketOrder(bucket) {
      return { errors: 0, failed: 1, skipped: 2, passed: 3 }[bucket] ?? 4;
    }

    function statusClass(status) {
      if (status === "failed" || status === "errors") return "failed";
      if (status === "passed") return "passed";
      if (status === "skipped") return "skipped";
      return "idle";
    }

    function statusLabel(status) {
      if (status === "failed") return "Failed";
      if (status === "errors") return "Errors";
      if (status === "passed") return "Passed";
      if (status === "skipped") return "Skipped";
      return "Not Included";
    }

    function formatDateTime(value) {
      if (!value) return "—";
      return new Date(value).toLocaleString("zh-TW", {
        timeZone: "Asia/Taipei",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    }

    function formatDuration(seconds) {
      if (seconds == null) return "—";
      if (seconds < 1) return `${seconds.toFixed(2)}s`;
      if (seconds < 10) return `${seconds.toFixed(1)}s`;
      return `${Math.round(seconds)}s`;
    }

    function shortCaseName(nodeid) {
      if (!nodeid) return "Unknown case";
      const parts = nodeid.split("::");
      return parts[parts.length - 1];
    }

    function scopeParts(data) {
      if (!data || data.status === "idle") return [];
      const selected = data.selectedItems || [];
      if (!selected.length) return ["Full suite"];
      return selected
        .map((itemId) => {
          const item = getItemById(itemId);
          return item ? item.label : itemId;
        });
    }

    function scopeLabel(data) {
      const parts = scopeParts(data);
      if (!parts.length) return "尚未執行";
      if (parts.length === 1) return parts[0];
      if (parts.length <= 3) return parts.join(" + ");
      return `${parts.slice(0, 2).join(" + ")} +${parts.length - 2} more`;
    }

    function totalChecksInScope(data) {
      const selected = (data && data.selectedItems) || [];
      if (!state.catalog) return selected.length;
      return selected.length || getItems().length;
    }

    function statCard(label, value, note) {
      return `
        <div class="stat">
          <div class="stat-k">${escapeHtml(label)}</div>
          <div class="stat-v">${escapeHtml(value)}</div>
          <div class="stat-note">${escapeHtml(note || "")}</div>
        </div>
      `;
    }

    function summaryCard(label, value, note, extraClass = "") {
      return `
        <div class="summary-card">
          <div class="summary-k">${escapeHtml(label)}</div>
          <div class="summary-v ${extraClass}">${escapeHtml(value)}</div>
          <div class="summary-note">${escapeHtml(note || "")}</div>
        </div>
      `;
    }

    function renderTopSummary() {
      const data = state.run;
      if (!data || data.status === "idle") {
        runBadgeEl.className = "run-badge idle";
        runBadgeEl.textContent = "Idle";
        metaEl.textContent = "尚未執行測試";
        noticeEl.className = "notice";
        noticeEl.textContent = "先載入最近一次結果，或直接執行完整測試。";
        summaryEl.innerHTML = [
          summaryCard("Current Scope", "尚未執行", "目前沒有可顯示的結果。", "scope"),
          summaryCard("Run Started", "—", "最近執行時間會顯示在這裡。"),
          summaryCard("Duration", "—", "方便判斷這組測試的大概成本。"),
          summaryCard("Checks In Scope", "0", "執行後會顯示全量或局部覆蓋範圍。"),
        ].join("");
        statsEl.innerHTML = [
          statCard("Total", "0", "No cases"),
          statCard("Passed", "0", "No data"),
          statCard("Failed", "0", "No data"),
          statCard("Errors", "0", "No data"),
          statCard("Skipped", "0", "No data"),
        ].join("");
        rerunBtn.disabled = true;
        return;
      }

      const totals = data.totals || { total: 0, passed: 0, failed: 0, errors: 0, skipped: 0 };
      const outcomeClassName = statusClass(data.outcome || "idle");
      runBadgeEl.className = `run-badge ${outcomeClassName}`;
      runBadgeEl.textContent = `${(data.outcome || "idle").toUpperCase()}`;
      metaEl.textContent = `run ${data.runId} • ${formatDateTime(data.finishedAt || data.startedAt)}`;
      rerunBtn.disabled = false;

      const partial = (data.selectedItems || []).length > 0;
      noticeEl.className = "notice";
      noticeEl.textContent = partial
        ? "目前顯示的是局部結果。未包含的檢查卡片會標示 Not Included，避免和完整測試混淆。"
        : "目前顯示的是完整測試結果。卡片狀態可當作整包健康度總覽。";

      summaryEl.innerHTML = [
        summaryCard("Current Scope", scopeLabel(data), partial ? "這不是完整 suite；只反映你選到的檢查。" : "這次結果來自完整 suite。", "scope"),
        summaryCard("Run Started", formatDateTime(data.startedAt), "使用 Asia/Taipei 顯示時間。"),
        summaryCard("Duration", formatDuration(data.durationSeconds), `Return code ${data.returnCode}`),
        summaryCard("Checks In Scope", String(totalChecksInScope(data)), `${partial ? "Selected checks only" : "All available checks"}`),
      ].join("");

      statsEl.innerHTML = [
        statCard("Total", String(totals.total || 0), "Cases in current result"),
        statCard("Passed", String(totals.passed || 0), totals.passed ? "Healthy" : "No pass cases"),
        statCard("Failed", String(totals.failed || 0), totals.failed ? "Needs attention" : "No failed cases"),
        statCard("Errors", String(totals.errors || 0), totals.errors ? "Unexpected execution issue" : "No runtime errors"),
        statCard("Skipped", String(totals.skipped || 0), totals.skipped ? "Skipped by test logic" : "No skipped cases"),
      ].join("");
    }

    function renderCatalog() {
      if (!state.catalog) {
        catalogEl.innerHTML = `<div class="empty">Loading checks...</div>`;
        return;
      }

      const itemResultMap = getItemResultMap();
      const rows = getRows();
      catalogMetaEl.textContent = `${getItems().length} checks across ${rows.length} domains`;

      catalogEl.innerHTML = rows.map((row) => {
        const cells = (row.cells || []).filter(Boolean);
        return `
          <section class="domain-block">
            <div class="domain-head">
              <h3>${escapeHtml(row.domain)}</h3>
              <span class="meta">${cells.length} checks</span>
            </div>
            <div class="check-grid">
              ${cells.map((item) => {
                const result = itemResultMap[item.id];
                const tone = statusClass(result ? result.status : "idle");
                const selected = result && result.status !== "not_run";
                const selectors = item.nodeids ? item.nodeids.length : 0;
                return `
                  <article class="check-card ${selected ? "included" : ""} ${tone}">
                    <div class="card-top">
                      <div class="card-meta">
                        <span class="pill type">${escapeHtml(item.column)}</span>
                        <span class="pill neutral">${selectors} selector${selectors === 1 ? "" : "s"}</span>
                      </div>
                      <span class="status-pill ${tone}">${escapeHtml(result ? statusLabel(result.status) : "Not Included")}</span>
                    </div>
                    <div>
                      <h4 class="card-title">${escapeHtml(item.label)}</h4>
                      <p class="card-summary">${escapeHtml(item.summary || "No summary available.")}</p>
                    </div>
                    <div class="card-actions">
                      <span class="meta">${result && result.status !== "not_run" ? `${result.total} case${result.total === 1 ? "" : "s"} in current result` : "Not part of current result"}</span>
                      <button class="run-item-btn" data-item-id="${escapeHtml(item.id)}">Run This Check</button>
                    </div>
                  </article>
                `;
              }).join("")}
            </div>
          </section>
        `;
      }).join("");

      catalogEl.querySelectorAll(".run-item-btn").forEach((btn) => {
        btn.addEventListener("click", () => runTests([btn.dataset.itemId]));
      });
      setBusy(state.isBusy);
    }

    function renderModules() {
      const data = state.run;
      const rows = (data && data.matrix) || [];
      if (!rows.length) {
        modulesEl.innerHTML = `<div class="empty">No module summary yet.</div>`;
        return;
      }

      const ordered = [...rows].sort((a, b) => {
        const scoreA = (a.errors || 0) * 2 + (a.failed || 0);
        const scoreB = (b.errors || 0) * 2 + (b.failed || 0);
        if (scoreB !== scoreA) return scoreB - scoreA;
        return (b.total || 0) - (a.total || 0);
      });

      modulesEl.innerHTML = ordered.map((row) => {
        const alert = (row.failed || 0) > 0 || (row.errors || 0) > 0;
        return `
          <div class="module-card ${alert ? "alert" : ""}">
            <div class="module-head">
              <div class="summary-k">Module</div>
              <span class="status-pill ${alert ? "failed" : "passed"}">${alert ? "Needs Attention" : "Healthy"}</span>
            </div>
            <div class="module-name">${escapeHtml(row.module)}</div>
            <div class="module-metrics">
              <span class="pill neutral">total ${row.total || 0}</span>
              <span class="pill ${row.passed ? "passed" : "idle"}">passed ${row.passed || 0}</span>
              <span class="pill ${row.failed ? "failed" : "idle"}">failed ${row.failed || 0}</span>
              <span class="pill ${row.errors ? "failed" : "idle"}">errors ${row.errors || 0}</span>
              <span class="pill ${row.skipped ? "skipped" : "idle"}">skipped ${row.skipped || 0}</span>
            </div>
          </div>
        `;
      }).join("");
    }

    function filteredCases() {
      const data = state.run;
      const cases = (data && data.cases) || [];
      const needle = caseSearchEl.value.trim().toLowerCase();
      return [...cases]
        .sort((a, b) => {
          const bucketDelta = bucketOrder(a.bucket) - bucketOrder(b.bucket);
          if (bucketDelta !== 0) return bucketDelta;
          return a.id.localeCompare(b.id);
        })
        .filter((item) => state.caseFilter === "all" || item.bucket === state.caseFilter)
        .filter((item) => {
          if (!needle) return true;
          return item.id.toLowerCase().includes(needle) || item.module.toLowerCase().includes(needle);
        });
    }

    function renderCases() {
      const visible = filteredCases();
      if (!visible.length) {
        casesEl.innerHTML = `<div class="empty">No cases match the current filter.</div>`;
        return;
      }

      casesEl.innerHTML = visible.slice(0, 400).map((item) => `
        <article class="case-row ${escapeHtml(item.bucket)}">
          <div class="card-top">
            <span class="case-badge ${escapeHtml(item.bucket)}">${escapeHtml(item.status)}</span>
            <span class="meta">${escapeHtml(item.module)}</span>
          </div>
          <div class="case-title">${escapeHtml(shortCaseName(item.id))}</div>
          <div class="case-path">${escapeHtml(item.id)}</div>
        </article>
      `).join("");
    }

    function renderOutput() {
      const data = state.run;
      const stdout = data && data.stdoutTail && data.stdoutTail.length ? data.stdoutTail.join("\\n") : "No stdout tail captured.";
      const stderr = data && data.stderrTail && data.stderrTail.length ? data.stderrTail.join("\\n") : "No stderr tail captured.";
      stdoutEl.textContent = stdout;
      stderrEl.textContent = stderr;
    }

    function renderAll() {
      renderTopSummary();
      renderCatalog();
      renderModules();
      renderCases();
      renderOutput();
    }

    function setBusy(isBusy) {
      state.isBusy = isBusy;
      runAllBtn.disabled = isBusy;
      reloadBtn.disabled = isBusy;
      rerunBtn.disabled = isBusy || !(state.run && state.run.status !== "idle");
      document.querySelectorAll(".run-item-btn").forEach((btn) => {
        btn.disabled = isBusy;
      });
    }

    function showError(message) {
      noticeEl.className = "notice error";
      noticeEl.textContent = message;
    }

    async function runTests(itemIds = []) {
      const labels = itemIds.map((itemId) => {
        const item = getItemById(itemId);
        return item ? item.label : itemId;
      });
      setBusy(true);
      runBadgeEl.className = "run-badge idle";
      runBadgeEl.textContent = "Running";
      metaEl.textContent = labels.length ? `running ${labels.join(" + ")}` : "running full suite";
      noticeEl.className = "notice";
      noticeEl.textContent = labels.length
        ? "正在執行局部檢查。完成後會清楚標示這次結果只覆蓋哪些卡片。"
        : "正在執行完整 suite。完成後所有卡片都會更新狀態。";
      try {
        const response = await fetch("/api/admin/tests/run?token=" + encodeURIComponent(token), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ itemIds }),
        });
        if (!response.ok) {
          showError(`Run failed with HTTP ${response.status}`);
          return;
        }
        state.run = await response.json();
        renderAll();
      } catch (error) {
        showError(`Run failed: ${error}`);
      } finally {
        setBusy(false);
      }
    }

    async function loadCatalog() {
      try {
        const response = await fetch("/api/admin/tests/catalog?token=" + encodeURIComponent(token));
        if (!response.ok) {
          showError(`Catalog error ${response.status}`);
          return;
        }
        state.catalog = await response.json();
        renderCatalog();
      } catch (error) {
        showError(`Catalog error: ${error}`);
      }
    }

    async function loadLast() {
      try {
        const response = await fetch("/api/admin/tests/last?token=" + encodeURIComponent(token));
        if (!response.ok) {
          showError(`Load last result failed with HTTP ${response.status}`);
          return;
        }
        state.run = await response.json();
        renderAll();
      } catch (error) {
        showError(`Load last result failed: ${error}`);
      }
    }

    runAllBtn.addEventListener("click", () => runTests([]));
    rerunBtn.addEventListener("click", () => {
      const selected = (state.run && state.run.selectedItems) || [];
      runTests(selected);
    });
    reloadBtn.addEventListener("click", loadLast);
    caseSearchEl.addEventListener("input", renderCases);
    document.querySelectorAll("#case-filters .filter-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#case-filters .filter-btn").forEach((node) => node.classList.remove("active"));
        btn.classList.add("active");
        state.caseFilter = btn.dataset.filter;
        renderCases();
      });
    });

    (async () => {
      await loadCatalog();
      await loadLast();
      renderAll();
    })();
  </script>
</body>
</html>"""


@app.get("/admin/tests", response_class=HTMLResponse, include_in_schema=False)
def admin_tests_ui(token: str | None = None):
    """Minimal grayscale test matrix dashboard."""
    _check_admin(token)
    return HTMLResponse(_ADMIN_TESTS_HTML)
