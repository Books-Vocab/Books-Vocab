from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from pathlib import Path
from typing import Any

from ..api_models import VocabAddResponse, VocabEntry
from ..vocab_intake import add_vocab_entries
from ._shared import _resolve_stores


def add_vocab_response(
    entries: list[VocabEntry],
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Path], Any],
    embedding_store_factory: Callable[..., Any],
    graph_store_factory: Callable[..., Any],
    gemini_client_factory: Callable[[], Any],
    logger: Logger,
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> VocabAddResponse:
    from ..tracked_llm import TrackedLLM
    cards, _ = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    llm = TrackedLLM(gemini_client_factory(), user["id"])
    return add_vocab_entries(
        entries,
        user=user,
        cards=cards,
        embeddings=embedding_store_factory(user["dir"], llm=llm, notebook_id=notebook_id),
        graph=graph_store_factory(user["dir"], notebook_id=notebook_id),
        logger=logger,
        notebook_id=notebook_id,
    )
