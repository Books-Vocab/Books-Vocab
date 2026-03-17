from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ..api_models import (
    ArchiveWordRequest,
    CardResponse,
    DailyReviewStatsPushRequest,
    DailyReviewStatsPushResponse,
    DailyReviewStatsResponse,
    DeleteWordResponse,
    GraphLinkResponse,
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
    _graph_store,
    _require_pro_access,
    get_current_user,
    logger,
)
from ..vocab_handlers import (
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

router = APIRouter()


@router.get("/api/vocab", response_model=list[CardResponse])
def list_vocab(response: Response, since: str | None = None, limit: int = 5000, user: dict = Depends(get_current_user)):
    from ..pipeline_service import is_pipeline_running

    result = list_vocab_response(
        since=since, limit=limit, user=user,
        require_pro_access=_require_pro_access,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        card_response_builder=lambda card, graph_obj, cards_by_id: _card_response(card, graph_obj, cards_by_id),
    )
    response.headers["X-Pipeline-Pending"] = "true" if is_pipeline_running(user["id"]) else "false"
    return result


# Static paths MUST be registered before {word} path parameter
@router.get("/api/vocab/daily-stats", response_model=DailyReviewStatsResponse)
def pull_daily_stats(since: str | None = None, user: dict = Depends(get_current_user)):
    return pull_daily_stats_response(
        since, user, require_pro_access=_require_pro_access,
        daily_stats_store_factory=_daily_stats_store,
    )


@router.patch("/api/vocab/daily-stats", response_model=DailyReviewStatsPushResponse)
def push_daily_stats(req: DailyReviewStatsPushRequest, user: dict = Depends(get_current_user)):
    return push_daily_stats_response(
        req, user, require_pro_access=_require_pro_access,
        daily_stats_store_factory=_daily_stats_store, logger=logger,
    )


@router.patch("/api/vocab/review", response_model=ReviewStatePushResponse)
def push_review(req: ReviewStatePushRequest, user: dict = Depends(get_current_user)):
    return push_review_response(
        req, user, require_pro_access=_require_pro_access,
        card_store_factory=_card_store, logger=logger,
    )


@router.get("/api/vocab/{word}", response_model=CardResponse)
def lookup_word(word: str, user: dict = Depends(get_current_user)):
    return lookup_word_response(
        word, user, require_pro_access=_require_pro_access,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        card_response_builder=lambda card, graph_obj, cards_by_id: _card_response(card, graph_obj, cards_by_id),
    )


@router.patch("/api/vocab/{word}/archive")
def archive_word(word: str, req: ArchiveWordRequest, user: dict = Depends(get_current_user)):
    return archive_word_response(word, req, user, require_pro_access=_require_pro_access, card_store_factory=_card_store)


@router.delete("/api/vocab/{word}", response_model=DeleteWordResponse)
def delete_word(word: str, user: dict = Depends(get_current_user)):
    return delete_word_response(
        word, user, require_pro_access=_require_pro_access,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
    )


@router.get("/api/graph/links", response_model=list[GraphLinkResponse])
def get_graph_links(user: dict = Depends(get_current_user)):
    return get_graph_links_response(user, require_pro_access=_require_pro_access, graph_store_factory=_graph_store)


@router.post("/api/vocab", response_model=VocabAddResponse)
def add_vocab(entries: list[VocabEntry], user: dict = Depends(get_current_user)):
    return add_vocab_response(
        entries, user, require_pro_access=_require_pro_access,
        card_store_factory=_card_store, embedding_store_factory=_embedding_store,
        graph_store_factory=_graph_store, logger=logger,
    )
