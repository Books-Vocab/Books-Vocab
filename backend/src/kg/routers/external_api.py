"""Versioned Pro-only external API for card capture and enrichment."""

from __future__ import annotations

import threading
import uuid
from copy import copy
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, Response

from ..api_models.cards import CardResponse
from ..api_models.external_api import (
    ExternalApiKeyCreateRequest,
    ExternalApiKeyResponse,
    ExternalCardArchiveRequest,
    ExternalCardBatchRequest,
    ExternalCardBatchResponse,
    ExternalCardCreateRequest,
    ExternalCardDeleteResponse,
    ExternalCardIngestResponse,
    ExternalCardListResponse,
    ExternalCardReviewRequest,
    ExternalCardUpdateRequest,
    ExternalEnrichRequest,
    ExternalLinkListResponse,
    ExternalManualLinkRequest,
    ExternalOperationListResponse,
    ExternalOperationResponse,
)
from ..api_models.graph import GraphLinkResponse, ManualLinkRequest
from ..api_models.notebook import NotebookCreateRequest, NotebookResponse, NotebookUpdateRequest
from ..api_models.review import ReviewStateEntry, ReviewStatePushRequest
from ..api_models.vocab import ArchiveWordRequest
from ..deps import (
    CurrentUser,
    _apply_quota_headers,
    _card_response,
    _card_store,
    _check_quota,
    _embedding_store,
    _graph_store,
    _is_pro,
    _notebook_store,
    get_user_lock,
    logger,
)
from ..exceptions import BadRequestError, ForbiddenError, NotFoundError, ValidationError
from ..external_api_keys import (
    authenticate_api_key,
    issue_api_key,
    list_api_keys,
    revoke_api_key,
)
from ..external_api_rate_limit import enrich_limiter, read_limiter, write_limiter
from ..graph import LinkKind
from ..notebook import validate_notebook_access
from ..pipeline_service import run_pipeline_background as _run_pipeline_bg
from ..service_factories import create_client
from ..types import UserRecord
from ..vocab_handlers import (
    archive_word_response,
    create_manual_link_response,
    delete_graph_link_response,
    get_graph_links_response,
    hide_graph_link_response,
    list_vocab_response,
    push_review_response,
    unhide_graph_link_response,
)
from ..vocab_shared import _clean_content, _normalize_pos
from .notebook import (
    create_notebook as _create_notebook,
)
from .notebook import (
    delete_notebook as _delete_notebook,
)
from .notebook import (
    list_notebooks as _list_notebooks,
)
from .notebook import (
    update_notebook as _update_notebook,
)

router = APIRouter(tags=["external-v1"])


_OPERATIONS: dict[str, dict[str, str]] = {}
_OPERATIONS_LOCK = threading.Lock()
_MAX_REMEMBERED_OPERATIONS = 10_000


def _remember_operation(operation_id: str, user_id: str, notebook_id: str) -> None:
    with _OPERATIONS_LOCK:
        _OPERATIONS[operation_id] = {
            "user_id": user_id,
            "notebook_id": notebook_id,
            "status": "queued",
        }
        while len(_OPERATIONS) > _MAX_REMEMBERED_OPERATIONS:
            _OPERATIONS.pop(next(iter(_OPERATIONS)))


def _mark_operation_failed(operation_id: str) -> None:
    with _OPERATIONS_LOCK:
        record = _OPERATIONS.get(operation_id)
        if record is not None:
            record["status"] = "failed"


def _operation_owner(operation_id: str) -> dict[str, str] | None:
    with _OPERATIONS_LOCK:
        record = _OPERATIONS.get(operation_id)
        return dict(record) if record is not None else None


def _persisted_operation(operation_id: str, user_id: str) -> dict[str, Any] | None:
    """Find an operation in durable telemetry after process-local state is lost."""
    from .. import pipeline_log

    for run in pipeline_log.get_runs(user_id, limit=_MAX_REMEMBERED_OPERATIONS):
        if run.get("run_id") == operation_id:
            return run
    return None


def get_external_api_user(
    request: Request,
    api_key: str | None = Header(default=None, alias="X-KG-API-Key"),
) -> UserRecord:
    resolved = authenticate_api_key(api_key, load_users=request.app.state.load_users)
    if resolved is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid external API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    key_id, user_id, record = resolved

    settings = request.app.state.kg_settings
    user_dir = settings.data_dir / "users" / user_id
    return {
        "id": user_id,
        "dir": user_dir,
        "record": record,
        "config": record.get("config", {}) if isinstance(record.get("config"), dict) else {},
        "external_api_key_id": key_id,
    }


ExternalUser = Annotated[UserRecord, Depends(get_external_api_user)]


def _require_pro(user: UserRecord) -> None:
    if not _is_pro(user):
        raise ForbiddenError("Pro plan required for the external API")


async def _admit_external(
    response: Response,
    user: UserRecord,
    limiter: Any,
) -> None:
    key_id = user.get("external_api_key_id")
    if not isinstance(key_id, str):
        raise HTTPException(status_code=401, detail="Invalid external API key")
    decision = await limiter.admit(key_id)
    headers = decision.headers
    if not decision.allowed:
        raise HTTPException(status_code=429, detail="External API rate limit exceeded", headers=headers)
    for name, value in headers.items():
        response.headers[name] = value


def _validate_notebook(user: UserRecord, notebook_id: str) -> None:
    validate_notebook_access(_notebook_store(user["dir"]), notebook_id)


def _card_or_404(user: UserRecord, card_id: str, notebook_id: str):
    card = _card_store(user["dir"]).get(card_id)
    if not card or card.is_deleted or card.notebook_id != notebook_id:
        raise NotFoundError("Card", card_id)
    return card


def _render_card(
    user: UserRecord,
    card: Any,
    notebook_id: str,
    *,
    cards: Any | None = None,
) -> CardResponse:
    cards = cards or _card_store(user["dir"])
    graph = _graph_store(user["dir"], notebook_id=notebook_id)
    cards_by_id: dict[str, Any] = {card.id: card}
    for link in graph.get_links_for(card.id):
        other_id = link.to_id if link.from_id == card.id else link.from_id
        other = cards.get(other_id)
        if other is not None:
            cards_by_id[other.id] = other
    return _card_response(card, graph, cards_by_id)


def _ingest_card(
    user: UserRecord,
    req: ExternalCardCreateRequest,
    *,
    cards: Any | None = None,
) -> tuple[CardResponse, bool]:
    _validate_notebook(user, req.notebookId)
    content = _clean_content(req.content)
    if not content:
        raise ValidationError("content must contain a word or phrase")

    cards = cards or _card_store(user["dir"])
    existing = cards.find_by_content(content, notebook_id=req.notebookId)
    if existing is not None:
        return _render_card(user, existing, req.notebookId, cards=cards), False

    examples = list(req.examples)
    if req.context and not examples:
        examples = [req.context]
    source = req.source.model_dump_json() if req.source is not None else None
    card = cards.add(
        content=content,
        meaning=req.meaning.strip(),
        pos=_normalize_pos(req.pos),
        examples=examples,
        collocations=list(req.collocations),
        mode=req.mode,
        notebook_id=req.notebookId,
        source=source,
    )
    if req.note is not None:
        card = cards.update(card.id, note=req.note) or card
    return _render_card(user, card, req.notebookId, cards=cards), True


@router.get("/api/v1/notebooks", response_model=list[NotebookResponse])
async def list_external_notebooks(response: Response, user: ExternalUser, since: str | None = None):
    _require_pro(user)
    await _admit_external(response, user, read_limiter)
    return _list_notebooks(user, since=since)


@router.post("/api/v1/notebooks", response_model=NotebookResponse, status_code=201)
async def create_external_notebook(req: NotebookCreateRequest, response: Response, user: ExternalUser):
    _require_pro(user)
    await _admit_external(response, user, write_limiter)
    return _create_notebook(req, user)


@router.patch("/api/v1/notebooks/{notebook_id}", response_model=NotebookResponse)
async def update_external_notebook(
    notebook_id: str,
    req: NotebookUpdateRequest,
    response: Response,
    user: ExternalUser,
):
    _require_pro(user)
    await _admit_external(response, user, write_limiter)
    return _update_notebook(notebook_id, req, user)


@router.delete("/api/v1/notebooks/{notebook_id}")
async def delete_external_notebook(notebook_id: str, response: Response, user: ExternalUser):
    _require_pro(user)
    await _admit_external(response, user, write_limiter)
    return _delete_notebook(notebook_id, user)


def _operation_from_run(run: dict[str, Any]) -> ExternalOperationResponse:
    raw_status = run.get("status")
    status = {
        "completed": "succeeded",
        "running": "running",
        "quota_exhausted": "quota_exhausted",
        "failed": "failed",
        "interrupted": "interrupted",
    }.get(raw_status, "unknown")
    return ExternalOperationResponse(
        operationId=run["run_id"],
        status=status,
        notebookId=run.get("notebook_id", "default"),
        startedAt=run.get("started_at"),
        endedAt=run.get("ended_at"),
        durationSeconds=run.get("duration_s"),
        steps=run.get("steps") or [],
    )


def _queued_operation(operation_id: str, record: dict[str, str]) -> ExternalOperationResponse:
    return ExternalOperationResponse(
        operationId=operation_id,
        status=record.get("status", "queued"),
        notebookId=record["notebook_id"],
    )


async def _run_external_pipeline(
    user: UserRecord,
    operation_id: str,
    *,
    force: bool,
    notebook_id: str,
) -> None:
    try:
        await _run_pipeline_bg(
            user,
            get_user_lock_fn=get_user_lock,
            card_store_factory=_card_store,
            graph_store_factory=_graph_store,
            embedding_store_factory=_embedding_store,
            client_factory=create_client,
            logger=logger,
            link_kind_enum=LinkKind,
            force_enrich=force,
            notebook_id=notebook_id,
            run_id=operation_id,
            telemetry_started=True,
        )
    except Exception:
        logger.exception("External enrich operation failed before pipeline telemetry: %s", operation_id)
        _mark_operation_failed(operation_id)
        try:
            from .. import pipeline_log

            pipeline_log.end_run(operation_id, "failed")
        except Exception:
            logger.warning("Failed to close external operation telemetry: %s", operation_id, exc_info=True)


@router.post("/api/v1/api-keys", response_model=ExternalApiKeyResponse, status_code=201)
def create_external_api_key(req: ExternalApiKeyCreateRequest, request: Request, user: CurrentUser):
    _require_pro(user)
    settings = request.app.state.kg_settings
    try:
        return issue_api_key(
            user["id"],
            label=req.label,
            users_lock_file=settings.users_lock_file,
            load_users=request.app.state.load_users,
            save_users=request.app.state.save_users,
        )
    except ValueError as exc:
        raise ForbiddenError(str(exc)) from exc


@router.get(
    "/api/v1/api-keys",
    response_model=list[ExternalApiKeyResponse],
    response_model_exclude_none=True,
)
def get_external_api_keys(request: Request, user: CurrentUser):
    _require_pro(user)
    return list_api_keys(user["id"], load_users=request.app.state.load_users)


@router.delete(
    "/api/v1/api-keys/{key_id}",
    response_model=ExternalApiKeyResponse,
    response_model_exclude_none=True,
)
def delete_external_api_key(key_id: str, request: Request, user: CurrentUser):
    settings = request.app.state.kg_settings
    record = revoke_api_key(
        user["id"],
        key_id,
        users_lock_file=settings.users_lock_file,
        load_users=request.app.state.load_users,
        save_users=request.app.state.save_users,
    )
    if record is None:
        raise NotFoundError("API key", key_id)
    return record


@router.post("/api/v1/cards/batch", response_model=ExternalCardBatchResponse, status_code=201)
async def ingest_card_batch(req: ExternalCardBatchRequest, response: Response, user: ExternalUser):
    _require_pro(user)
    await _admit_external(response, user, write_limiter)
    items: list[ExternalCardIngestResponse] = []
    created = 0
    cards = _card_store(user["dir"])
    with cards.engine.begin() as connection:
        transaction_cards = copy(cards)
        transaction_cards.engine = connection
        for entry in req.items:
            card, was_created = _ingest_card(user, entry, cards=transaction_cards)
            created += int(was_created)
            items.append(ExternalCardIngestResponse(card=card, created=was_created, clientId=entry.clientId))
    return ExternalCardBatchResponse(items=items, created=created, duplicates=len(items) - created)


@router.post("/api/v1/cards", response_model=ExternalCardIngestResponse, status_code=201)
async def ingest_card(req: ExternalCardCreateRequest, response: Response, user: ExternalUser):
    _require_pro(user)
    await _admit_external(response, user, write_limiter)
    card, created = _ingest_card(user, req)
    return ExternalCardIngestResponse(card=card, created=created, clientId=req.clientId)


@router.get("/api/v1/cards", response_model=ExternalCardListResponse)
async def list_external_cards(
    response: Response,
    user: ExternalUser,
    notebook_id: str = Query("default", alias="notebookId", pattern=r"^[A-Za-z0-9_-]{1,64}$"),
    since: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    cursor: str | None = None,
):
    _require_pro(user)
    await _admit_external(response, user, read_limiter)
    _validate_notebook(user, notebook_id)
    cards, next_cursor = list_vocab_response(
        since=since,
        user=user,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        card_response_builder=_card_response,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
        limit=limit,
        cursor=cursor,
    )
    if next_cursor is not None:
        response.headers["X-Next-Cursor"] = next_cursor
    return ExternalCardListResponse(items=cards, nextCursor=next_cursor)


@router.get("/api/v1/cards/{card_id}", response_model=CardResponse)
async def get_external_card(
    card_id: str,
    response: Response,
    user: ExternalUser,
    notebook_id: str = Query("default", alias="notebookId", pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    _require_pro(user)
    await _admit_external(response, user, read_limiter)
    _validate_notebook(user, notebook_id)
    return _render_card(user, _card_or_404(user, card_id, notebook_id), notebook_id)


@router.patch("/api/v1/cards/{card_id}", response_model=CardResponse)
async def update_external_card(
    card_id: str,
    req: ExternalCardUpdateRequest,
    response: Response,
    user: ExternalUser,
    notebook_id: str = Query("default", alias="notebookId", pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    _require_pro(user)
    await _admit_external(response, user, write_limiter)
    _validate_notebook(user, notebook_id)
    card = _card_or_404(user, card_id, notebook_id)
    updates: dict[str, Any] = {}
    for field in ("meaning", "note", "examples", "collocations", "mode"):
        value = getattr(req, field)
        if value is not None:
            updates[field] = value
    if req.pos is not None:
        updates["pos"] = _normalize_pos(req.pos)
    if not updates:
        raise BadRequestError("No card fields to update")
    updated = _card_store(user["dir"]).update(card.id, **updates)
    if updated is None:
        raise NotFoundError("Card", card_id)
    return _render_card(user, updated, notebook_id)


@router.post("/api/v1/cards/{card_id}/archive", response_model=CardResponse)
async def archive_external_card(
    card_id: str,
    req: ExternalCardArchiveRequest,
    response: Response,
    user: ExternalUser,
    notebook_id: str = Query("default", alias="notebookId", pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    _require_pro(user)
    await _admit_external(response, user, write_limiter)
    _validate_notebook(user, notebook_id)
    card = _card_or_404(user, card_id, notebook_id)
    archive_word_response(
        card.content,
        ArchiveWordRequest(archived=req.archived),
        user,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )
    updated = _card_store(user["dir"]).get(card_id)
    if updated is None:
        raise NotFoundError("Card", card_id)
    return _render_card(user, updated, notebook_id)


@router.delete("/api/v1/cards/{card_id}", response_model=ExternalCardDeleteResponse)
async def delete_external_card(
    card_id: str,
    response: Response,
    user: ExternalUser,
    notebook_id: str = Query("default", alias="notebookId", pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    _require_pro(user)
    await _admit_external(response, user, write_limiter)
    _validate_notebook(user, notebook_id)
    card = _card_or_404(user, card_id, notebook_id)
    cards = _card_store(user["dir"])
    graph = _graph_store(user["dir"], notebook_id=notebook_id)
    cards.delete(card.id)
    try:
        graph.cleanup_for_card(card.id, remove_blocked=True, source="manual")
    except Exception:
        cards.restore(card.id, notebook_id=notebook_id)
        raise
    try:
        _embedding_store(user["dir"], llm=None, notebook_id=notebook_id).remove(card.id)
    except Exception:
        # Card/graph deletion is already durable. A stale embedding is
        # recoverable on the next pipeline pass, so it must not turn a
        # successful delete into a retry-prone 5xx.
        logger.warning(
            "[%s] Failed to evict embedding for deleted card %s",
            user["id"],
            card.id,
            exc_info=True,
        )
    return ExternalCardDeleteResponse(cardId=card.id, deleted=True)


@router.post("/api/v1/cards/{card_id}/review", response_model=CardResponse)
async def review_external_card(
    card_id: str,
    req: ExternalCardReviewRequest,
    response: Response,
    user: ExternalUser,
    notebook_id: str = Query("default", alias="notebookId", pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    _require_pro(user)
    await _admit_external(response, user, write_limiter)
    _validate_notebook(user, notebook_id)
    card = _card_or_404(user, card_id, notebook_id)
    push_review_response(
        ReviewStatePushRequest(
            entries=[
                ReviewStateEntry(
                    word=card.content,
                    card_id=card.id,
                    review_interval_hours=req.reviewIntervalHours,
                    next_review_at=req.nextReviewAt,
                    last_reviewed_at=req.lastReviewedAt,
                    review_count=req.reviewCount,
                    lapse_count=req.lapseCount,
                    review_streak=req.reviewStreak,
                    last_review_feedback=req.lastReviewFeedback,
                )
            ]
        ),
        user,
        card_store_factory=_card_store,
        logger=logger,
        notebook_id=notebook_id,
    )
    updated = _card_store(user["dir"]).get(card_id)
    if updated is None:
        raise NotFoundError("Card", card_id)
    return _render_card(user, updated, notebook_id)


@router.get("/api/v1/links", response_model=ExternalLinkListResponse)
async def list_external_links(
    response: Response,
    user: ExternalUser,
    notebook_id: str = Query("default", alias="notebookId", pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    _require_pro(user)
    await _admit_external(response, user, read_limiter)
    _validate_notebook(user, notebook_id)
    return ExternalLinkListResponse(
        items=get_graph_links_response(
            user,
            graph_store_factory=_graph_store,
            card_store_factory=_card_store,
            notebook_store_factory=_notebook_store,
            notebook_id=notebook_id,
        )
    )


@router.post("/api/v1/links", response_model=GraphLinkResponse)
async def create_external_link(
    req: ExternalManualLinkRequest,
    response: Response,
    user: ExternalUser,
    notebook_id: str = Query("default", alias="notebookId", pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    _require_pro(user)
    # Manual linking invokes the LLM judge, so use the expensive-operation
    # bucket rather than the cheap card-write bucket.
    await _admit_external(response, user, enrich_limiter)
    _validate_notebook(user, notebook_id)
    quota = _check_quota(user, "manual_link", response)
    result = create_manual_link_response(
        ManualLinkRequest(from_id=req.fromId, to_id=req.toId),
        user,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        client_factory=create_client,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )
    _apply_quota_headers(response, quota)
    return result


@router.patch("/api/v1/links/{link_id}/hide", status_code=204)
async def hide_external_link(
    link_id: str,
    response: Response,
    user: ExternalUser,
    notebook_id: str = Query("default", alias="notebookId", pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    _require_pro(user)
    await _admit_external(response, user, write_limiter)
    _validate_notebook(user, notebook_id)
    hide_graph_link_response(
        link_id,
        user,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )


@router.patch("/api/v1/links/{link_id}/unhide", status_code=204)
async def unhide_external_link(
    link_id: str,
    response: Response,
    user: ExternalUser,
    notebook_id: str = Query("default", alias="notebookId", pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    _require_pro(user)
    await _admit_external(response, user, write_limiter)
    _validate_notebook(user, notebook_id)
    unhide_graph_link_response(
        link_id,
        user,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )


@router.delete("/api/v1/links/{link_id}", status_code=204)
async def delete_external_link(
    link_id: str,
    response: Response,
    user: ExternalUser,
    notebook_id: str = Query("default", alias="notebookId", pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    _require_pro(user)
    await _admit_external(response, user, write_limiter)
    _validate_notebook(user, notebook_id)
    delete_graph_link_response(
        link_id,
        user,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )


@router.post("/api/v1/enrich", response_model=ExternalOperationResponse, status_code=202)
async def enqueue_external_enrich(
    req: ExternalEnrichRequest,
    background_tasks: BackgroundTasks,
    response: Response,
    user: ExternalUser,
):
    _require_pro(user)
    await _admit_external(response, user, enrich_limiter)
    _validate_notebook(user, req.notebookId)
    quota = _check_quota(user, "pipeline", response)
    operation_id = uuid.uuid4().hex[:12]
    from .. import pipeline_log

    # Persist before scheduling the background task. If the process exits
    # between these two operations, startup recovery marks the run interrupted
    # and the operation remains queryable instead of disappearing from memory.
    pipeline_log.start_run(operation_id, user["id"], req.notebookId, "background")
    _remember_operation(operation_id, user["id"], req.notebookId)
    background_tasks.add_task(
        _run_external_pipeline,
        user,
        operation_id,
        force=req.force,
        notebook_id=req.notebookId,
    )
    _apply_quota_headers(response, quota)
    return _queued_operation(
        operation_id, _operation_owner(operation_id) or {"notebook_id": req.notebookId, "status": "queued"}
    )


@router.get("/api/v1/operations/{operation_id}", response_model=ExternalOperationResponse)
async def get_external_operation(operation_id: str, response: Response, user: ExternalUser):
    _require_pro(user)
    await _admit_external(response, user, read_limiter)
    owner = _operation_owner(operation_id)
    if owner is not None and owner.get("user_id") != user["id"]:
        raise NotFoundError("Operation", operation_id)
    persisted = _persisted_operation(operation_id, user["id"])
    if persisted is not None:
        return _operation_from_run(persisted)
    if owner is None:
        raise NotFoundError("Operation", operation_id)
    return _queued_operation(operation_id, owner)


@router.get("/api/v1/enrich/runs", response_model=ExternalOperationListResponse)
async def list_external_enrich_runs(
    response: Response,
    user: ExternalUser,
    limit: int = Query(20, ge=1, le=100),
):
    _require_pro(user)
    await _admit_external(response, user, read_limiter)
    from .. import pipeline_log

    return ExternalOperationListResponse(
        items=[_operation_from_run(run) for run in pipeline_log.get_runs(user["id"], limit=limit)]
    )
