from __future__ import annotations

from typing import Any

from ..api_models import GraphLinkResponse, ManualLinkRequest
from ..vocab_graph import graph_links_payload
from ..vocab_graph_ops import (
    create_manual_link,
    delete_graph_link,
    hide_graph_link,
    unhide_graph_link,
)
from ._shared import CardStoreFactory, ClientFactory, GraphStoreFactory, NotebookStoreFactory, _resolve_stores


def get_graph_links_response(
    user: dict[str, Any],
    *,
    graph_store_factory: GraphStoreFactory,
    notebook_store_factory: NotebookStoreFactory | None = None,
    notebook_id: str = "default",
) -> list[GraphLinkResponse]:
    stores = _resolve_stores(
        user,
        notebook_id,
        card_store_factory=lambda _path: None,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    return graph_links_payload(graph=stores.graph)


def create_manual_link_response(
    req: ManualLinkRequest,
    user: dict[str, Any],
    *,
    card_store_factory: CardStoreFactory,
    graph_store_factory: GraphStoreFactory,
    client_factory: ClientFactory,
    notebook_store_factory: NotebookStoreFactory | None = None,
    notebook_id: str = "default",
) -> GraphLinkResponse:
    stores = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )

    from ..deps_quota import _is_pro
    from ..judge import ManualLinkJudge
    from ..llm.providers import provider_for
    from ..tracked_llm import TrackedLLM
    provider = provider_for("judge_manual")
    judge = ManualLinkJudge(
        TrackedLLM(
            client_factory(provider),
            user["id"],
            provider=provider,
            enforce_quota=True,
            is_pro=_is_pro(user),
        ),
        model=provider.chat_model,
        user_id=user["id"], notebook_id=notebook_id,
    )

    link = create_manual_link(
        from_id=req.from_id, to_id=req.to_id,
        cards_store=stores.cards, graph=stores.graph, judge=judge,
        notebook_id=notebook_id,
    )
    return GraphLinkResponse(
        id=link.id,
        fromId=link.from_id,
        toId=link.to_id,
        kind=link.kind.value,
        confidence=link.confidence,
        reason=link.reason,
    )


def delete_graph_link_response(
    link_id: str,
    user: dict[str, Any],
    *,
    card_store_factory: CardStoreFactory,
    graph_store_factory: GraphStoreFactory,
    notebook_store_factory: NotebookStoreFactory | None = None,
    notebook_id: str = "default",
) -> None:
    stores = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    delete_graph_link(link_id=link_id, graph=stores.graph, cards_store=stores.cards)


def hide_graph_link_response(
    link_id: str,
    user: dict[str, Any],
    *,
    card_store_factory: CardStoreFactory,
    graph_store_factory: GraphStoreFactory,
    notebook_store_factory: NotebookStoreFactory | None = None,
    notebook_id: str = "default",
) -> None:
    stores = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    hide_graph_link(link_id=link_id, graph=stores.graph, cards_store=stores.cards)


def unhide_graph_link_response(
    link_id: str,
    user: dict[str, Any],
    *,
    card_store_factory: CardStoreFactory,
    graph_store_factory: GraphStoreFactory,
    notebook_store_factory: NotebookStoreFactory | None = None,
    notebook_id: str = "default",
) -> None:
    stores = _resolve_stores(
        user, notebook_id,
        card_store_factory=card_store_factory,
        graph_store_factory=graph_store_factory,
        notebook_store_factory=notebook_store_factory,
    )
    unhide_graph_link(link_id=link_id, graph=stores.graph, cards_store=stores.cards)
