from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..api_models import GraphLinkResponse, ManualLinkRequest
from ..notebook import validate_notebook_access
from ..vocab_graph import graph_links_payload
from ..vocab_graph_ops import (
    create_manual_link,
    delete_graph_link,
    hide_graph_link,
    unhide_graph_link,
)
from ._shared import _resolve_stores


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

    from ..judge import ManualLinkJudge
    from ..tracked_llm import TrackedLLM
    judge = ManualLinkJudge(
        TrackedLLM(gemini_client_factory(), user["id"]),
        user_id=user["id"], notebook_id=notebook_id,
    )

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
