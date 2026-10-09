from __future__ import annotations

from logging import Logger
from pathlib import Path
from typing import Any, Protocol

from ..api_models import (
    ReviewEventsPushRequest,
    ReviewEventsPushResponse,
    ReviewEventsResponse,
    ReviewStatePushRequest,
    ReviewStatePushResponse,
)
from ..review_events import pull_review_events, push_review_events
from ..vocab_review import push_review_states


class CardStore(Protocol): ...


class ReviewEventStore(Protocol): ...


class CardStoreFactory(Protocol):
    def __call__(self, user_dir: Path) -> CardStore: ...


class NotebookStoreFactory(Protocol):
    def __call__(self, user_dir: Path) -> Any: ...


class ReviewEventStoreFactory(Protocol):
    def __call__(self, user_dir: Path) -> ReviewEventStore: ...


def push_review_response(
    req: ReviewStatePushRequest,
    user: dict[str, Any],
    *,
    card_store_factory: CardStoreFactory,
    logger: Logger,
    notebook_id: str | None = None,
    notebook_store_factory: NotebookStoreFactory | None = None,
) -> ReviewStatePushResponse:
    cards = card_store_factory(user["dir"])
    # Staged (copy-in-progress) notebooks are hidden from the pull path; the
    # global push must not write review state into their cards either.
    staged_ids: list[str] = []
    if notebook_id is None and notebook_store_factory is not None:
        staged_ids = notebook_store_factory(user["dir"]).staged_ids()
    result = push_review_states(
        req.entries, cards_store=cards, logger=logger, notebook_id=notebook_id, exclude_notebook_ids=staged_ids
    )
    return ReviewStatePushResponse(**result)


def push_review_events_response(
    req: ReviewEventsPushRequest,
    user: dict[str, Any],
    *,
    review_event_store_factory: ReviewEventStoreFactory,
) -> ReviewEventsPushResponse:
    store = review_event_store_factory(user["dir"])
    result = push_review_events(req.entries, event_store=store)
    return ReviewEventsPushResponse(**result)


def pull_review_events_response(
    since: str | None,
    user: dict[str, Any],
    *,
    review_event_store_factory: ReviewEventStoreFactory,
) -> ReviewEventsResponse:
    store = review_event_store_factory(user["dir"])
    entries, cursor = pull_review_events(since=since, event_store=store)
    return ReviewEventsResponse(entries=entries, cursor=cursor)
