from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from pathlib import Path
from typing import Any

from ..api_models import (
    ReviewEventsPushRequest,
    ReviewEventsPushResponse,
    ReviewEventsResponse,
    ReviewStatePushRequest,
    ReviewStatePushResponse,
)
from ..review_events import pull_review_events, push_review_events
from ..vocab_review import push_review_states


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
    entries, cursor = pull_review_events(since=since, event_store=store)
    return ReviewEventsResponse(entries=entries, cursor=cursor)
