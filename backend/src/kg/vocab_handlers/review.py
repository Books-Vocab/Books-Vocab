from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from pathlib import Path
from typing import Any

from ..api_models import (
    DailyReviewStatsPushRequest,
    DailyReviewStatsPushResponse,
    DailyReviewStatsResponse,
    ReviewEventsPushRequest,
    ReviewEventsPushResponse,
    ReviewEventsResponse,
    ReviewStatePushRequest,
    ReviewStatePushResponse,
)
from ..vocab_review import (
    pull_daily_review_stats,
    push_daily_review_stats,
    push_review_states,
)
from ..review_events import pull_review_events, push_review_events


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


def push_review_events_response(
    req: ReviewEventsPushRequest,
    user: dict[str, Any],
    *,
    review_event_store_factory: Callable[[Path], Any],
) -> ReviewEventsPushResponse:
    store = review_event_store_factory(user["dir"])
    result = push_review_events(req.entries, event_store=store)
    return ReviewEventsPushResponse(**result)


def pull_review_events_response(
    since: str | None,
    user: dict[str, Any],
    *,
    review_event_store_factory: Callable[[Path], Any],
) -> ReviewEventsResponse:
    store = review_event_store_factory(user["dir"])
    entries = pull_review_events(since=since, event_store=store)
    return ReviewEventsResponse(entries=entries)
