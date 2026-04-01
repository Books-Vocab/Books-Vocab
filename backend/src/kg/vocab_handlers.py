from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from pathlib import Path
from typing import Any

from .api_models import (
    ArchiveWordRequest,
    BatchArchiveRequest,
    BatchDeleteRequest,
    CardResponse,
    DailyReviewStatsPushRequest,
    DailyReviewStatsPushResponse,
    DailyReviewStatsResponse,
    GraphLinkResponse,
    ManualLinkRequest,
    MoveWordsRequest,
    ReviewStatePushRequest,
    ReviewStatePushResponse,
    VocabAddResponse,
    VocabEntry,
)
from .notebook import validate_notebook_access
from .vocab_crud import (
    archive_vocab_word,
    batch_archive_vocab_words,
    batch_delete_vocab_words,
    delete_vocab_word,
    list_vocab_cards,
    lookup_vocab_word,
    move_vocab_words,
)
from .vocab_graph import graph_links_payload
from .vocab_graph_ops import (
    create_manual_link,
    delete_graph_link,
    hide_graph_link,
    unhide_graph_link,
)
from .vocab_intake import add_vocab_entries
from .vocab_review import (
    pull_daily_review_stats,
    push_daily_review_stats,
    push_review_states,
)


def _resolve_stores(
    user: dict[str, Any],
    notebook_id: str | None,
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
) -> tuple[Any, Any]:
    """Validate notebook access and construct card + graph stores."""
    if notebook_id is not None and notebook_store_factory is not None:
        validate_notebook_access(notebook_store_factory(user["dir"]), notebook_id)
    cards = card_store_factory(user["dir"])
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id or "default") if graph_store_factory is not None else None
    return cards, graph


def list_vocab_response(
    since: str | None,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any],
    card_response_builder: Callable[[Any, Any, dict[str, Any]], Any],
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str | None = None,
) -> list[Any]:
    cards_store, graph = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return list_vocab_cards(
        since=since,
        cards_store=cards_store,
        graph=graph,
        card_response_builder=card_response_builder,
        notebook_id=notebook_id,
    )


def lookup_word_response(
    word: str,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any],
    card_response_builder: Callable[[Any, Any, dict[str, Any]], Any],
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> CardResponse:
    cards, graph = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return lookup_vocab_word(
        word,
        cards_store=cards,
        graph=graph,
        card_response_builder=card_response_builder,
        notebook_id=notebook_id,
    )


def archive_word_response(
    word: str,
    req: ArchiveWordRequest,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str | None = None,
) -> dict[str, str]:
    cards, graph = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return archive_vocab_word(word, archived=req.archived, cards_store=cards, graph=graph, notebook_id=notebook_id)


def move_words_response(
    req: MoveWordsRequest,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> dict[str, int]:
    if notebook_store_factory is not None:
        validate_notebook_access(notebook_store_factory(user["dir"]), notebook_id)
        validate_notebook_access(notebook_store_factory(user["dir"]), req.to_notebook_id)
    cards = card_store_factory(user["dir"])
    source_graph = graph_store_factory(user["dir"], notebook_id=notebook_id) if graph_store_factory else None
    target_graph = graph_store_factory(user["dir"], notebook_id=req.to_notebook_id) if graph_store_factory else None
    return move_vocab_words(
        words=req.words,
        from_notebook_id=notebook_id,
        to_notebook_id=req.to_notebook_id,
        cards_store=cards,
        source_graph=source_graph,
        target_graph=target_graph,
    )


def delete_word_response(
    word: str,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> dict[str, str]:
    cards, graph = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return delete_vocab_word(word, cards_store=cards, graph=graph, notebook_id=notebook_id)


def batch_delete_response(
    req: BatchDeleteRequest,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> dict[str, Any]:
    cards, graph = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return batch_delete_vocab_words(req.words, cards_store=cards, graph=graph, notebook_id=notebook_id)


def batch_archive_response(
    req: BatchArchiveRequest,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> dict[str, Any]:
    cards, graph = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return batch_archive_vocab_words(req.words, archived=req.archived, cards_store=cards, graph=graph, notebook_id=notebook_id)


def get_graph_links_response(
    user: dict[str, Any],
    *,
    graph_store_factory: Callable[..., Any],
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> list[GraphLinkResponse]:
    if notebook_id is not None and notebook_store_factory is not None:
        validate_notebook_access(notebook_store_factory(user["dir"]), notebook_id)
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id)
    return graph_links_payload(graph=graph)


def add_vocab_response(
    entries: list[VocabEntry],
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    embedding_store_factory: Callable[..., Any],
    graph_store_factory: Callable[..., Any],
    logger: Logger,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> VocabAddResponse:
    cards, _ = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return add_vocab_entries(
        entries,
        user=user,
        cards=cards,
        embeddings=embedding_store_factory(user["dir"], user_id=user["id"], notebook_id=notebook_id),
        graph=graph_store_factory(user["dir"], notebook_id=notebook_id),
        logger=logger,
        notebook_id=notebook_id,
    )


def push_review_response(
    req: ReviewStatePushRequest,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    logger: Logger,
    notebook_id: str | None = None,
) -> ReviewStatePushResponse:
    cards = card_store_factory(user["dir"])
    result = push_review_states(req.entries, cards_store=cards, logger=logger, notebook_id=notebook_id)
    return ReviewStatePushResponse(**result)


def push_daily_stats_response(
    req: DailyReviewStatsPushRequest,
    user: dict[str, Any],
    *,
    daily_stats_store_factory: Callable[[Path], Any],
    logger: Logger,
) -> DailyReviewStatsPushResponse:
    store = daily_stats_store_factory(user["dir"])
    result = push_daily_review_stats(req.entries, stats_store=store, logger=logger)
    return DailyReviewStatsPushResponse(**result)


def pull_daily_stats_response(
    since: str | None,
    user: dict[str, Any],
    *,
    daily_stats_store_factory: Callable[[Path], Any],
) -> DailyReviewStatsResponse:
    store = daily_stats_store_factory(user["dir"])
    entries = pull_daily_review_stats(since=since, stats_store=store)
    return DailyReviewStatsResponse(entries=entries)


def create_manual_link_response(
    req: ManualLinkRequest,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any],
    gemini_client_factory: Callable[[], Any],
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> GraphLinkResponse:
    cards, graph = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )

    from .judge import ManualLinkJudge
    judge = ManualLinkJudge(gemini_client_factory())

    link = create_manual_link(
        from_id=req.from_id, to_id=req.to_id,
        cards_store=cards, graph=graph, judge=judge,
    )
    return GraphLinkResponse(
        id=link.id,
        fromId=link.from_id,
        toId=link.to_id,
        kind=link.kind.value if hasattr(link.kind, 'value') else link.kind,
        confidence=link.confidence,
        reason=link.reason,
    )


def delete_graph_link_response(
    link_id: str,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any],
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> None:
    cards, graph = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    delete_graph_link(link_id=link_id, graph=graph, cards_store=cards)


def hide_graph_link_response(
    link_id: str,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any],
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> None:
    cards, graph = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    hide_graph_link(link_id=link_id, graph=graph, cards_store=cards)


def unhide_graph_link_response(
    link_id: str,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any],
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> None:
    cards, graph = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    unhide_graph_link(link_id=link_id, graph=graph, cards_store=cards)
