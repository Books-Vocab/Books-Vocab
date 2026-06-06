from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

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
    VocabEntry,
)
from ..deps import (
    _apply_quota_headers,
    _card_response,
    _card_store,
    _check_quota,
    _embedding_store,
    _graph_store,
    _notebook_store,
    _review_event_store,
    get_current_user,
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
)

NOTEBOOK_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

router = APIRouter(tags=["vocab"])


@router.get("/api/vocab", response_model=list[CardResponse])
def list_vocab(
    response: Response,
    since: str | None = None,
    notebook_id: str | None = Query(None, pattern=NOTEBOOK_ID_PATTERN),
    user: dict = Depends(get_current_user),
):
    from ..pipeline_service import is_pipeline_running

    result = list_vocab_response(
        since=since, user=user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        card_response_builder=_card_response,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )
    response.headers["X-Pipeline-Pending"] = "true" if is_pipeline_running(user["id"]) else "false"
    return result


# Static paths MUST be registered before {word} path parameter

@router.post("/api/vocab/batch-delete", response_model=BatchDeleteResponse)
def batch_delete(
    req: BatchDeleteRequest,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
    user: dict = Depends(get_current_user),
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
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
    user: dict = Depends(get_current_user),
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
    user: dict = Depends(get_current_user),
):
    # notebook_id 不做過濾：iOS client 推送全部 notebook 的複習狀態，
    # 後端需在全域卡片中查找匹配。
    return push_review_response(
        req, user,
        card_store_factory=_card_store, logger=logger,
        notebook_id=None,
    )


@router.get("/api/vocab/review-events", response_model=ReviewEventsResponse)
def pull_review_events(since: str | None = None, user: dict = Depends(get_current_user)):
    return pull_review_events_response(
        since, user,
        review_event_store_factory=_review_event_store,
    )


@router.patch("/api/vocab/review-events", response_model=ReviewEventsPushResponse)
def push_review_events(req: ReviewEventsPushRequest, user: dict = Depends(get_current_user)):
    return push_review_events_response(
        req, user,
        review_event_store_factory=_review_event_store,
    )


@router.get("/api/vocab/{word}", response_model=CardResponse)
def lookup_word(
    word: str,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
    user: dict = Depends(get_current_user),
):
    return lookup_word_response(
        word, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        card_response_builder=_card_response,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )



@router.patch("/api/vocab/{word}/archive", response_model=ArchiveWordResponse)
def archive_word(word: str, req: ArchiveWordRequest, notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN), user: dict = Depends(get_current_user)):
    return archive_word_response(word, req, user, card_store_factory=_card_store, graph_store_factory=_graph_store, notebook_store_factory=_notebook_store, notebook_id=notebook_id)


@router.delete("/api/vocab/{word}", response_model=DeleteWordResponse)
def delete_word(
    word: str,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
    user: dict = Depends(get_current_user),
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
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
    user: dict = Depends(get_current_user),
):
    return get_graph_links_response(
        user,
        graph_store_factory=_graph_store, notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )


@router.post("/api/graph/links", response_model=GraphLinkResponse)
def create_graph_link(
    req: ManualLinkRequest,
    response: Response,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
    user: dict = Depends(get_current_user),
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
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
    user: dict = Depends(get_current_user),
):
    hide_graph_link_response(
        link_id, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store, notebook_id=notebook_id,
    )


@router.patch("/api/graph/links/{link_id}/unhide", status_code=204)
def unhide_graph_link(
    link_id: str,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
    user: dict = Depends(get_current_user),
):
    unhide_graph_link_response(
        link_id, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store, notebook_id=notebook_id,
    )


@router.delete("/api/graph/links/{link_id}", status_code=204)
def delete_graph_link(
    link_id: str,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
    user: dict = Depends(get_current_user),
):
    delete_graph_link_response(
        link_id, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store, notebook_id=notebook_id,
    )


@router.post("/api/vocab", response_model=VocabAddResponse)
def add_vocab(
    entries: list[VocabEntry],
    response: Response,
    notebook_id: str = Query("default", pattern=NOTEBOOK_ID_PATTERN),
    user: dict = Depends(get_current_user),
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
