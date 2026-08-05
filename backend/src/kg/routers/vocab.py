from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import Field

from ..api_models import (
    ArchiveWordRequest,
    ArchiveWordResponse,
    BatchArchiveRequest,
    BatchArchiveResponse,
    BatchDeleteRequest,
    BatchDeleteResponse,
    CardResponse,
    DeleteWordResponse,
    GraphLinkResponse,
    ManualLinkRequest,
    ReviewEventsPushRequest,
    ReviewEventsPushResponse,
    ReviewEventsResponse,
    ReviewStatePushRequest,
    ReviewStatePushResponse,
    VocabAddResponse,
    VocabContentUpdateRequest,
    VocabEntry,
)
from ..deps import (
    CurrentUser,
    _apply_quota_headers,
    _card_response,
    _card_store,
    _check_quota,
    _embedding_store,
    _graph_store,
    _notebook_store,
    _review_event_store,
    logger,
)
from ..service_factories import create_client
from ..vocab_handlers import (
    add_vocab_response,
    archive_word_response,
    batch_archive_response,
    batch_delete_response,
    create_manual_link_response,
    delete_graph_link_response,
    delete_word_response,
    get_graph_links_response,
    hide_graph_link_response,
    list_vocab_response,
    lookup_word_response,
    pull_review_events_response,
    push_review_events_response,
    push_review_response,
    unhide_graph_link_response,
    update_word_content_response,
)

NOTEBOOK_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

router = APIRouter(tags=["vocab"])


@router.get("/api/vocab", response_model=list[CardResponse])
def list_vocab(
    response: Response,
    user: CurrentUser,
    since: str | None = None,
    notebook_id: str | None = Query(None, pattern=NOTEBOOK_ID_PATTERN),
    limit: int = Query(5000, ge=1, le=10000),
    cursor: str | None = None,
):
    from ..pipeline_service import is_pipeline_running

    # Body stays response_model=list[CardResponse] (iOS parsing unchanged); the
    # opaque next-page cursor rides the X-Next-Cursor header (same out-of-band
    # pattern as X-Pipeline-Pending). A malformed cursor -> BadRequestError.
    result, next_cursor = list_vocab_response(
        since=since, user=user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        card_response_builder=_card_response,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
        limit=limit,
        cursor=cursor,
    )
    response.headers["X-Pipeline-Pending"] = "true" if is_pipeline_running(user["id"]) else "false"
    if next_cursor is not None:
        response.headers["X-Next-Cursor"] = next_cursor
    return result


# Static paths MUST be registered before {word} path parameter

@router.post("/api/vocab/batch-delete", response_model=BatchDeleteResponse)
def batch_delete(
    req: BatchDeleteRequest,
    user: CurrentUser,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
):
    return batch_delete_response(
        req, user,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store,
        embedding_store_factory=_embedding_store,
        client_factory=create_client,
        notebook_id=notebook_id,
    )


@router.patch("/api/vocab/batch-archive", response_model=BatchArchiveResponse)
def batch_archive(
    req: BatchArchiveRequest,
    user: CurrentUser,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
):
    return batch_archive_response(
        req, user,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )


@router.patch("/api/vocab/review", response_model=ReviewStatePushResponse)
def push_review(
    req: ReviewStatePushRequest,
    user: CurrentUser,
):
    # notebook_id 不做過濾：iOS client 推送全部 notebook 的複習狀態，
    # 後端需在全域卡片中查找匹配。
    return push_review_response(
        req, user,
        card_store_factory=_card_store, logger=logger,
        notebook_id=None,
    )


@router.get("/api/vocab/review-events", response_model=ReviewEventsResponse)
def pull_review_events(user: CurrentUser, since: str | None = None):
    return pull_review_events_response(
        since, user,
        review_event_store_factory=_review_event_store,
    )


@router.patch("/api/vocab/review-events", response_model=ReviewEventsPushResponse)
def push_review_events(req: ReviewEventsPushRequest, user: CurrentUser):
    return push_review_events_response(
        req, user,
        review_event_store_factory=_review_event_store,
    )


@router.get("/api/vocab/{word}", response_model=CardResponse)
def lookup_word(
    word: str,
    user: CurrentUser,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
):
    return lookup_word_response(
        word, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        card_response_builder=_card_response,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )



@router.patch("/api/vocab/{word}", response_model=CardResponse)
def update_word_content(
    word: str,
    req: VocabContentUpdateRequest,
    user: CurrentUser,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
):
    # Editorial content update (meaning / note). Distinct from
    # {word}/archive (archive toggle) and DELETE {word} (soft delete).
    return update_word_content_response(
        word, req, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        card_response_builder=_card_response,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )


@router.patch("/api/vocab/{word}/archive", response_model=ArchiveWordResponse)
def archive_word(word: str, req: ArchiveWordRequest, user: CurrentUser, notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN)):
    return archive_word_response(word, req, user, card_store_factory=_card_store, graph_store_factory=_graph_store, notebook_store_factory=_notebook_store, notebook_id=notebook_id)


@router.delete("/api/vocab/{word}", response_model=DeleteWordResponse)
def delete_word(
    word: str,
    user: CurrentUser,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
):
    return delete_word_response(
        word, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store,
        embedding_store_factory=_embedding_store,
        client_factory=create_client,
        notebook_id=notebook_id,
    )


@router.get("/api/graph/links", response_model=list[GraphLinkResponse])
def get_graph_links(
    user: CurrentUser,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
    include_dictionary: bool = False,
):
    return get_graph_links_response(
        user,
        graph_store_factory=_graph_store,
        card_store_factory=_card_store,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
        include_dictionary=include_dictionary,
    )


@router.post("/api/graph/links", response_model=GraphLinkResponse)
def create_graph_link(
    req: ManualLinkRequest,
    response: Response,
    user: CurrentUser,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
):
    # Manual link creation invokes ManualLinkJudge + TrackedLLM (real LLM
    # call). Gate it with the daily quota, like add_vocab / pipeline /
    # translate, so an over-quota user cannot burn unbounded LLM cost.
    quota = _check_quota(user, "manual_link", response)
    result = create_manual_link_response(
        req, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        client_factory=create_client, notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )
    _apply_quota_headers(response, quota)
    return result


@router.patch("/api/graph/links/{link_id}/hide", status_code=204)
def hide_graph_link(
    link_id: str,
    user: CurrentUser,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
):
    hide_graph_link_response(
        link_id, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store, notebook_id=notebook_id,
    )


@router.patch("/api/graph/links/{link_id}/unhide", status_code=204)
def unhide_graph_link(
    link_id: str,
    user: CurrentUser,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
):
    unhide_graph_link_response(
        link_id, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store, notebook_id=notebook_id,
    )


@router.delete("/api/graph/links/{link_id}", status_code=204)
def delete_graph_link(
    link_id: str,
    user: CurrentUser,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
):
    delete_graph_link_response(
        link_id, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store, notebook_id=notebook_id,
    )


@router.post("/api/vocab", response_model=VocabAddResponse)
def add_vocab(
    # Cap intake batch at the schema layer (matches batch-delete/archive's
    # max_length=500) so an oversized list is rejected at request validation
    # before being deserialized — bounds LLM/DB amplification. The handler keeps
    # its own MAX_BATCH_SIZE guard as defense-in-depth.
    entries: Annotated[list[VocabEntry], Field(max_length=500)],
    response: Response,
    user: CurrentUser,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
):
    quota = _check_quota(user, "vocab_add", response)
    result = add_vocab_response(
        entries, user,
        card_store_factory=_card_store, embedding_store_factory=_embedding_store,
        graph_store_factory=_graph_store, client_factory=create_client,
        logger=logger,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )
    _apply_quota_headers(response, quota)
    return result
