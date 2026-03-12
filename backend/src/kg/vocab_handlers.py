from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from pathlib import Path
from typing import Any

from .api_models import (
    ArchiveWordRequest,
    CardResponse,
    DailyReviewStatsPushRequest,
    DailyReviewStatsPushResponse,
    DailyReviewStatsResponse,
    GraphLinkResponse,
    ReviewStatePushRequest,
    ReviewStatePushResponse,
    VocabAddResponse,
    VocabEntry,
)
from .vocab_service import (
    add_vocab_entries,
    archive_vocab_word,
    delete_vocab_word,
    graph_links_payload,
    list_vocab_cards,
    lookup_vocab_word,
    pull_daily_review_stats,
    push_daily_review_stats,
    push_review_states,
)


def list_vocab_response(
    since: str | None,
    limit: int,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[[Path], Any],
    card_response_builder: Callable[[Any, Any, dict[str, Any]], Any],
) -> list[Any]:
    require_pro_access(user, "knowledge_sync")
    cards_store = card_store_factory(user["dir"])
    graph = graph_store_factory(user["dir"])
    return list_vocab_cards(
        since=since,
        limit=limit,
        cards_store=cards_store,
        graph=graph,
        card_response_builder=card_response_builder,
    )


def lookup_word_response(
    word: str,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[[Path], Any],
    card_response_builder: Callable[[Any, Any, dict[str, Any]], Any],
) -> CardResponse:
    require_pro_access(user, "knowledge_sync")
    cards = card_store_factory(user["dir"])
    graph = graph_store_factory(user["dir"])
    return lookup_vocab_word(
        word,
        cards_store=cards,
        graph=graph,
        card_response_builder=card_response_builder,
    )


def archive_word_response(
    word: str,
    req: ArchiveWordRequest,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    card_store_factory: Callable[[Path], Any],
) -> dict[str, str]:
    require_pro_access(user, "knowledge_sync")
    cards = card_store_factory(user["dir"])
    return archive_vocab_word(word, archived=req.archived, cards_store=cards)


def delete_word_response(
    word: str,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    card_store_factory: Callable[[Path], Any],
) -> dict[str, str]:
    require_pro_access(user, "knowledge_sync")
    cards = card_store_factory(user["dir"])
    return delete_vocab_word(word, cards_store=cards)


def get_graph_links_response(
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    graph_store_factory: Callable[[Path], Any],
) -> list[GraphLinkResponse]:
    require_pro_access(user, "knowledge_graph")
    graph = graph_store_factory(user["dir"])
    return graph_links_payload(graph=graph)


def add_vocab_response(
    entries: list[VocabEntry],
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    card_store_factory: Callable[[Path], Any],
    embedding_store_factory: Callable[..., Any],
    graph_store_factory: Callable[[Path], Any],
    logger: Logger,
) -> VocabAddResponse:
    require_pro_access(user, "knowledge_sync")
    cards = card_store_factory(user["dir"])
    return add_vocab_entries(
        entries,
        user=user,
        cards=cards,
        embeddings=embedding_store_factory(user["dir"], user_id=user["id"]),
        graph=graph_store_factory(user["dir"]),
        logger=logger,
    )


def push_review_response(
    req: ReviewStatePushRequest,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    card_store_factory: Callable[[Path], Any],
    logger: Logger,
) -> ReviewStatePushResponse:
    require_pro_access(user, "knowledge_sync")
    cards = card_store_factory(user["dir"])
    result = push_review_states(req.entries, cards_store=cards, logger=logger)
    return ReviewStatePushResponse(**result)


def push_daily_stats_response(
    req: DailyReviewStatsPushRequest,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    daily_stats_store_factory: Callable[[Path], Any],
    logger: Logger,
) -> DailyReviewStatsPushResponse:
    require_pro_access(user, "knowledge_sync")
    store = daily_stats_store_factory(user["dir"])
    result = push_daily_review_stats(req.entries, stats_store=store, logger=logger)
    return DailyReviewStatsPushResponse(**result)


def pull_daily_stats_response(
    since: str | None,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    daily_stats_store_factory: Callable[[Path], Any],
) -> DailyReviewStatsResponse:
    require_pro_access(user, "knowledge_sync")
    store = daily_stats_store_factory(user["dir"])
    entries = pull_daily_review_stats(since=since, stats_store=store)
    return DailyReviewStatsResponse(entries=entries)
