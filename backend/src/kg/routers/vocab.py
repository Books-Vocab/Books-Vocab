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
    DailyReviewStatsPushRequest,
    DailyReviewStatsPushResponse,
    DailyReviewStatsResponse,
    DeleteWordResponse,
    GraphLinkResponse,
    ManualLinkRequest,
    ReviewStatePushRequest,
    ReviewStatePushResponse,
    VocabAddResponse,
    VocabEntry,
)
from ..deps import (
    _card_response,
    _card_store,
    _daily_stats_store,
    _embedding_store,
    _gemini_client,
    _graph_store,
    _notebook_store,
    get_current_user,
    logger,
)
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
    pull_daily_stats_response,
    push_daily_stats_response,
    push_review_response,
    unhide_graph_link_response,
)

router = APIRouter()


@router.get("/api/vocab", response_model=list[CardResponse])
def list_vocab(
    response: Response,
    since: str | None = None,
    notebook_id: str | None = Query(None),
    user: dict = Depends(get_current_user),
):
    from ..pipeline_service import is_pipeline_running

    result = list_vocab_response(
        since=since, user=user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        card_response_builder=lambda card, graph_obj, cards_by_id: _card_response(card, graph_obj, cards_by_id),
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )
    response.headers["X-Pipeline-Pending"] = "true" if is_pipeline_running(user["id"]) else "false"
    return result


# Static paths MUST be registered before {word} path parameter

@router.post("/api/vocab/batch-delete", response_model=BatchDeleteResponse)
def batch_delete(
    req: BatchDeleteRequest,
    notebook_id: str = Query("default"),
    user: dict = Depends(get_current_user),
):
    return batch_delete_response(
        req, user,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )


@router.patch("/api/vocab/batch-archive", response_model=BatchArchiveResponse)
def batch_archive(
    req: BatchArchiveRequest,
    notebook_id: str = Query("default"),
    user: dict = Depends(get_current_user),
):
    return batch_archive_response(
        req, user,
        card_store_factory=_card_store,
        graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )


@router.get("/api/vocab/daily-stats", response_model=DailyReviewStatsResponse)
def pull_daily_stats(since: str | None = None, user: dict = Depends(get_current_user)):
    return pull_daily_stats_response(
        since, user,
        daily_stats_store_factory=_daily_stats_store,
    )


@router.patch("/api/vocab/daily-stats", response_model=DailyReviewStatsPushResponse)
def push_daily_stats(req: DailyReviewStatsPushRequest, user: dict = Depends(get_current_user)):
    return push_daily_stats_response(
        req, user,
        daily_stats_store_factory=_daily_stats_store, logger=logger,
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


@router.get("/api/vocab/{word}", response_model=CardResponse)
def lookup_word(
    word: str,
    notebook_id: str = Query("default"),
    user: dict = Depends(get_current_user),
):
    return lookup_word_response(
        word, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        card_response_builder=lambda card, graph_obj, cards_by_id: _card_response(card, graph_obj, cards_by_id),
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )



@router.patch("/api/vocab/{word}/archive", response_model=ArchiveWordResponse)
def archive_word(word: str, req: ArchiveWordRequest, notebook_id: str = Query("default"), user: dict = Depends(get_current_user)):
    return archive_word_response(word, req, user, card_store_factory=_card_store, graph_store_factory=_graph_store, notebook_store_factory=_notebook_store, notebook_id=notebook_id)


@router.delete("/api/vocab/{word}", response_model=DeleteWordResponse)
def delete_word(
    word: str,
    notebook_id: str = Query("default"),
    user: dict = Depends(get_current_user),
):
    return delete_word_response(
        word, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )


@router.get("/api/graph/links", response_model=list[GraphLinkResponse])
def get_graph_links(
    notebook_id: str = Query("default"),
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
    notebook_id: str = Query("default"),
    user: dict = Depends(get_current_user),
):
    return create_manual_link_response(
        req, user,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        gemini_client_factory=_gemini_client, notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )


@router.patch("/api/graph/links/{link_id}/hide", status_code=204)
def hide_graph_link(
    link_id: str,
    notebook_id: str = Query("default"),
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
    notebook_id: str = Query("default"),
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
    notebook_id: str = Query("default"),
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
    notebook_id: str = Query("default"),
    user: dict = Depends(get_current_user),
):
    return add_vocab_response(
        entries, user,
        card_store_factory=_card_store, embedding_store_factory=_embedding_store,
        graph_store_factory=_graph_store, gemini_client_factory=_gemini_client,
        logger=logger,
        notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )
