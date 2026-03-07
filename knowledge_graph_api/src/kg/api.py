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
from pydantic import BaseModel, Field
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
from .apple_auth import verify_apple_token
from .google_auth import verify_google_token

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

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = 60 * 24 * 365 # 1 year
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
APPLE_BUNDLE_ID = os.getenv("APPLE_BUNDLE_ID", "com.Max0228.BooksBrowser")

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


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class VocabEntry(BaseModel):
    """A vocabulary entry from BooksBrowser."""
    word: str
    translation: str
    context: str = ""
    root_form: str | None = None  # AI-determined lemma from translate/quick


class VocabAddResponse(BaseModel):
    created: int
    skipped: int
    duplicates: list[str]
    cardIds: dict[str, str]  # word -> card_id


class HealthResponse(BaseModel):
    status: str
    cards: int
    links: int
    pendingCandidates: int
    lastModified: str | None


class CardResponse(BaseModel):
    id: str
    content: str
    meaning: str
    pos: str | None
    difficulty: float | None
    difficultyTier: str | None
    note: str | None
    examples: list[str]
    mode: str
    isDeleted: bool
    inflections: list[str] = []
    linksByKind: dict[str, list["CardLinkSummaryResponse"]] = Field(default_factory=dict)


class CardLinkSummaryResponse(BaseModel):
    id: str
    cardId: str
    word: str
    kind: str
    label: str
    confidence: float
    reason: str


class TranslateRequest(BaseModel):
    word: str
    context: str

class GraphLinkResponse(BaseModel):
    id: str
    fromId: str
    toId: str
    kind: str
    confidence: float
    reason: str

class QuickTranslateResponse(BaseModel):
    t: str
    p: str | None = None
    r: str | None = None  # root form (lemma)

class ExplainResponse(BaseModel):
    e: str


# ---------------------------------------------------------------------------
# Auth models
# ---------------------------------------------------------------------------
class AuthVerifyRequest(BaseModel):
    provider: str  # "apple" or "google"
    token: str
    email: str | None = None  # Optional: email from provider


class AuthVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    expires_in: int  # seconds


class UserConfigRequest(BaseModel):
    mochi_api_key: str | None = None
    # Add other config fields here in the future if needed


class UserConfigResponse(BaseModel):
    mochi_api_key: str | None = None


class DeleteAccountResponse(BaseModel):
    deleted_user_id: str
    linked_ids: list[str]
    deleted_dirs: list[str]


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
    from .difficulty import get_tier

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
    background_tasks.add_task(_run_pipeline_background, user)
    return {"status": "queued", "message": "Pipeline started in the background"}

# ---------------------------------------------------------------------------
# POST /api/translate/quick & /api/translate/explain
# ---------------------------------------------------------------------------
@app.post("/api/translate/quick", response_model=QuickTranslateResponse)
def translate_quick(req: TranslateRequest, user: dict = Depends(get_current_user)):
    """Perform a quick UI translation via Gemini API (proxy)."""
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
        "nodeids": ["tests/test_renderer_truncation.py"],
    },
    {
        "id": "vocab_graph",
        "domain": "Vocab/Graph",
        "column": "Integration",
        "label": "Vocab + Graph API",
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
        "nodeids": ["tests/test_api_surface.py::test_translate_endpoints_success_and_error"],
    },
    {
        "id": "auth_linking",
        "domain": "User/Auth",
        "column": "Integration",
        "label": "Auth Linking",
        "nodeids": ["tests/test_api_surface.py::test_auth_verify_links_google_and_apple_by_email"],
    },
    {
        "id": "account_robustness",
        "domain": "User/Auth",
        "column": "Robustness",
        "label": "Config + Account Robustness",
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
        "nodeids": ["tests/test_robustness.py::TestBatchC_EmbeddingBackfill"],
    },
    {
        "id": "storage_atomicity",
        "domain": "Storage",
        "column": "Robustness",
        "label": "Mochi + CardStore Atomicity",
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
        "nodeids": ["tests/test_robustness.py::TestBatchD_UserLockAtomic"],
    },
    {
        "id": "admin_contract",
        "domain": "Admin",
        "column": "Contract",
        "label": "Admin Endpoints",
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
        "nodeids": ["tests/test_robustness.py::TestBatchE_VocabConcurrentWrite"],
    },
    {
        "id": "pipeline_integration",
        "domain": "Pipeline",
        "column": "Integration",
        "label": "Pipeline Integration",
        "nodeids": ["tests/test_pipeline_integration.py::TestPipelineIntegration"],
    },
]
_TEST_MATRIX_ITEM_MAP = {item["id"]: item for item in _TEST_MATRIX_ITEMS}


class AdminTestRunRequest(BaseModel):
    itemIds: list[str] = []


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
    domains = sorted({item["domain"] for item in _TEST_MATRIX_ITEMS})
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
  <title>Test Matrix</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Noto+Sans+TC:wght@300;400;500&display=swap" rel="stylesheet">
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
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Noto Sans TC", sans-serif;
      line-height: 1.85;
    }
    .nav {
      position: sticky;
      top: 0;
      height: 52px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 16px;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      z-index: 10;
    }
    .brand {
      font-family: "JetBrains Mono", monospace;
      font-size: 12px;
      letter-spacing: .12em;
      text-transform: uppercase;
    }
    .dev-dot {
      margin-left: 8px;
      color: var(--dev);
      border: 1px solid var(--dev);
      padding: 1px 5px;
      font-size: 10px;
      border-radius: 2px;
    }
    .nav-link {
      font-family: "JetBrains Mono", monospace;
      text-decoration: none;
      color: var(--ink-light);
      font-size: 11px;
      letter-spacing: .04em;
      text-transform: uppercase;
      border: 1px solid var(--border);
      padding: 6px 10px;
      border-radius: 2px;
      background: var(--surface);
    }
    .wrap {
      max-width: 1180px;
      margin: 20px auto 48px;
      padding: 0 16px;
    }
    .panel {
      border: 1px solid var(--border);
      background: var(--surface);
      border-radius: 3px;
      padding: 16px;
      margin-bottom: 12px;
    }
    .label {
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .14em;
      color: var(--sub);
      margin-bottom: 8px;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .cta {
      height: 48px;
      padding: 0 18px;
      border: 1px solid var(--ink);
      border-radius: 3px;
      background: var(--ink);
      color: #fff;
      font-family: "JetBrains Mono", monospace;
      font-size: 12px;
      letter-spacing: .12em;
      text-transform: uppercase;
      cursor: pointer;
      transition: transform .12s ease, box-shadow .12s ease;
    }
    .cta:hover:not(:disabled) {
      transform: translateY(-2px);
      box-shadow: 0 5px 0 rgba(42, 37, 32, .25);
    }
    .cta:disabled {
      opacity: .55;
      cursor: not-allowed;
    }
    .secondary {
      height: 38px;
      padding: 0 12px;
      border: 1px solid var(--border);
      border-radius: 3px;
      background: transparent;
      color: var(--ink-light);
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      letter-spacing: .10em;
      text-transform: uppercase;
      cursor: pointer;
    }
    .meta {
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      color: var(--sub);
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 8px;
      margin-top: 14px;
    }
    .stat {
      border: 1px solid var(--border-l);
      border-radius: 3px;
      padding: 10px 12px;
    }
    .stat-k {
      font-family: "JetBrains Mono", monospace;
      font-size: 10px;
      letter-spacing: .12em;
      text-transform: uppercase;
      color: var(--sub);
    }
    .stat-v {
      font-family: "JetBrains Mono", monospace;
      font-size: 24px;
      margin-top: 2px;
      letter-spacing: .04em;
      color: var(--ink);
    }
    .matrix-wrap {
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: 3px;
      background: var(--surface);
    }
    table {
      width: 100%;
      min-width: 760px;
      border-collapse: collapse;
      font-family: "JetBrains Mono", monospace;
      font-size: 12px;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border-l);
      border-right: 1px solid var(--border-l);
      text-align: left;
      vertical-align: top;
    }
    tr:last-child td { border-bottom: 0; }
    th:last-child, td:last-child { border-right: 0; }
    thead th {
      color: var(--sub);
      text-transform: uppercase;
      letter-spacing: .08em;
      background: #f3f0ea;
      font-size: 11px;
    }
    .cell-btn {
      width: 100%;
      border: 1px solid var(--border);
      background: transparent;
      color: var(--ink);
      border-radius: 3px;
      min-height: 44px;
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      letter-spacing: .06em;
      text-transform: uppercase;
      cursor: pointer;
      padding: 6px;
      text-align: left;
    }
    .cell-btn:hover:not(:disabled) {
      border-color: var(--ink);
      background: #f7f4ef;
    }
    .cell-btn:disabled {
      opacity: .5;
      cursor: not-allowed;
    }
    .cell-status {
      margin-top: 4px;
      font-family: "JetBrains Mono", monospace;
      font-size: 10px;
      letter-spacing: .07em;
      color: var(--sub);
      text-transform: uppercase;
    }
    .dash {
      color: var(--sub);
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      letter-spacing: .08em;
    }
    .content {
      border: 1px solid var(--border);
      border-radius: 3px;
      background: var(--surface);
      padding: 14px 16px;
      margin-top: 12px;
      max-height: 320px;
      overflow: auto;
    }
    .case-row {
      font-family: "Noto Sans TC", sans-serif;
      font-size: 14px;
      color: var(--ink-light);
      border-bottom: 1px solid var(--border-l);
      padding: 8px 0;
    }
    .case-row:last-child { border-bottom: 0; }
    .mono {
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      color: var(--sub);
      letter-spacing: .03em;
    }
    .empty {
      color: var(--sub);
      font-family: "JetBrains Mono", monospace;
      font-size: 12px;
      letter-spacing: .05em;
    }
  </style>
</head>
<body>
  <div class="nav">
    <div class="brand">KG Test Matrix <span class="dev-dot">DEV</span></div>
    <a class="nav-link" href="/admin?token=" id="back-link">Admin</a>
  </div>

  <main class="wrap">
    <section class="panel">
      <div class="label">Run</div>
      <div class="actions">
        <button id="run-all-btn" class="cta">Run All</button>
        <button id="reload-btn" class="secondary">Reload Last</button>
        <span id="meta" class="meta">idle</span>
      </div>
      <div id="stats" class="stats"></div>
    </section>

    <section class="panel">
      <div class="label">Item Matrix (Click Cell To Run)</div>
      <div class="matrix-wrap">
        <table>
          <thead id="matrix-head"></thead>
          <tbody id="matrix-body">
            <tr><td class="empty">Loading matrix catalog...</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <div class="label">Cases</div>
      <div id="cases" class="content">
        <div class="empty">No case data.</div>
      </div>
    </section>
  </main>

  <script>
    const token = new URLSearchParams(location.search).get("token") || "";
    document.getElementById("back-link").href = "/admin?token=" + encodeURIComponent(token);

    const runAllBtn = document.getElementById("run-all-btn");
    const reloadBtn = document.getElementById("reload-btn");
    const metaEl = document.getElementById("meta");
    const matrixHead = document.getElementById("matrix-head");
    const matrixBody = document.getElementById("matrix-body");
    const casesEl = document.getElementById("cases");
    const statsEl = document.getElementById("stats");
    let matrixCatalog = null;

    function statCard(label, value) {
      return `
        <div class="stat">
          <div class="stat-k">${label}</div>
          <div class="stat-v">${value}</div>
        </div>
      `;
    }

    function renderCatalog() {
      if (!matrixCatalog) return;
      const cols = matrixCatalog.columns || [];
      matrixHead.innerHTML = `<tr><th>Domain</th>${cols.map(c => `<th>${c}</th>`).join("")}</tr>`;
      const rows = matrixCatalog.rows || [];
      if (!rows.length) {
        matrixBody.innerHTML = `<tr><td class="empty">No matrix catalog.</td></tr>`;
        return;
      }
      matrixBody.innerHTML = rows.map((row) => {
        const cells = row.cells.map((cell) => {
          if (!cell) return `<td><span class="dash">-</span></td>`;
          return `<td>
            <button class="cell-btn" data-item-id="${cell.id}">${cell.label}</button>
            <div class="cell-status" id="status-${cell.id}">NOT RUN</div>
          </td>`;
        }).join("");
        return `<tr><td>${row.domain}</td>${cells}</tr>`;
      }).join("");
    }

    function applyItemStatuses(data) {
      const itemResults = (data && data.itemResults) || [];
      const resultMap = {};
      itemResults.forEach((r) => { resultMap[r.id] = r; });
      if (!matrixCatalog || !matrixCatalog.items) return;
      matrixCatalog.items.forEach((item) => {
        const el = document.getElementById(`status-${item.id}`);
        if (!el) return;
        const r = resultMap[item.id];
        if (!r || r.status === "not_run") {
          el.textContent = "NOT RUN";
          return;
        }
        el.textContent = `${r.status.toUpperCase()} (${r.total})`;
      });
    }

    function render(data) {
      if (!data || data.status === "idle") {
        metaEl.textContent = "idle";
        statsEl.innerHTML = "";
        casesEl.innerHTML = `<div class="empty">No case data.</div>`;
        applyItemStatuses(null);
        return;
      }

      const totals = data.totals || { total: 0, passed: 0, failed: 0, errors: 0, skipped: 0 };
      metaEl.textContent = `run ${data.runId} | ${data.outcome.toUpperCase()} | ${data.durationSeconds}s`;
      statsEl.innerHTML = [
        statCard("Total", totals.total || 0),
        statCard("Passed", totals.passed || 0),
        statCard("Failed", totals.failed || 0),
        statCard("Errors", totals.errors || 0),
        statCard("Skipped", totals.skipped || 0),
      ].join("");
      applyItemStatuses(data);

      const cases = data.cases || [];
      if (!cases.length) {
        casesEl.innerHTML = `<div class="empty">No case details.</div>`;
      } else {
        casesEl.innerHTML = cases.slice(0, 400).map((c) => `
          <div class="case-row">
            <div>${c.id}</div>
            <div class="mono">${c.status} · ${c.bucket}</div>
          </div>
        `).join("");
      }
    }

    function setBusy(isBusy) {
      runAllBtn.disabled = isBusy;
      document.querySelectorAll(".cell-btn").forEach((b) => { b.disabled = isBusy; });
    }

    async function runTests(itemIds = []) {
      setBusy(true);
      metaEl.textContent = itemIds.length ? `running ${itemIds.join(",")}...` : "running all...";
      try {
        const r = await fetch("/api/admin/tests/run?token=" + encodeURIComponent(token), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ itemIds }),
        });
        if (!r.ok) {
          metaEl.textContent = `error ${r.status}`;
          return;
        }
        render(await r.json());
      } finally {
        setBusy(false);
      }
    }

    async function loadCatalog() {
      const r = await fetch("/api/admin/tests/catalog?token=" + encodeURIComponent(token));
      if (!r.ok) {
        metaEl.textContent = `catalog error ${r.status}`;
        return;
      }
      matrixCatalog = await r.json();
      renderCatalog();
      matrixBody.querySelectorAll(".cell-btn").forEach((btn) => {
        btn.addEventListener("click", () => runTests([btn.dataset.itemId]));
      });
    }

    async function loadLast() {
      const r = await fetch("/api/admin/tests/last?token=" + encodeURIComponent(token));
      if (!r.ok) {
        metaEl.textContent = `error ${r.status}`;
        return;
      }
      render(await r.json());
    }

    runAllBtn.addEventListener("click", () => runTests([]));
    reloadBtn.addEventListener("click", loadLast);
    (async () => {
      await loadCatalog();
      await loadLast();
    })();
  </script>
</body>
</html>"""


@app.get("/admin/tests", response_class=HTMLResponse, include_in_schema=False)
def admin_tests_ui(token: str | None = None):
    """Minimal grayscale test matrix dashboard."""
    _check_admin(token)
    return HTMLResponse(_ADMIN_TESTS_HTML)
