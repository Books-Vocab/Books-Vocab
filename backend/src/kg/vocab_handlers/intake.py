from __future__ import annotations

from logging import Logger
from typing import Any

from ..api_models import VocabAddResponse, VocabEntry
from ..vocab_intake import add_vocab_entries
from ._shared import (
    CardStoreFactory,
    ClientFactory,
    EmbeddingStoreFactory,
    GraphStoreFactory,
    NotebookStoreFactory,
    _resolve_stores,
)


def add_vocab_response(
    entries: list[VocabEntry],
    user: dict[str, Any],
    *,
    card_store_factory: CardStoreFactory,
    embedding_store_factory: EmbeddingStoreFactory,
    graph_store_factory: GraphStoreFactory,
    client_factory: ClientFactory,
    logger: Logger,
    notebook_store_factory: NotebookStoreFactory | None = None,
    notebook_id: str = "default",
) -> VocabAddResponse:
    from ..deps_quota import _is_pro
    from ..llm.providers import provider_for
    from ..quota_service import estimate_call_cost, reserve
    from ..tracked_llm import TrackedLLM

    stores = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    provider = provider_for("embed")
    llm = TrackedLLM(client_factory(provider), user["id"], provider=provider, reserve_quota=False)
    with reserve(user["id"], estimate_call_cost("embed"), enforce=True, is_pro=_is_pro(user)):
        return add_vocab_entries(
            entries,
            user=user,
            cards=stores.cards,
            embeddings=embedding_store_factory(user["dir"], llm=llm, notebook_id=notebook_id),
            graph=graph_store_factory(user["dir"], notebook_id=notebook_id),
            logger=logger,
            notebook_id=notebook_id,
        )
