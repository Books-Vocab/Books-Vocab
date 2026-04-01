"""Graph link operations: create, hide, unhide, delete."""

from __future__ import annotations

from typing import Any

from .exceptions import ConflictError, NotFoundError


def create_manual_link(
    *,
    from_id: str,
    to_id: str,
    cards_store: Any,
    graph: Any,
    judge: Any,
) -> Any:
    """Create a manual link between two cards. Calls LLM for kind + reason."""
    from .graph import LinkKind

    card_a = cards_store.get(from_id)
    card_b = cards_store.get(to_id)
    if not card_a or card_a.is_deleted or card_a.is_archived:
        raise NotFoundError("Card", from_id)
    if not card_b or card_b.is_deleted or card_b.is_archived:
        raise NotFoundError("Card", to_id)

    existing = graph.find_link_between(from_id, to_id)
    if existing and existing.status == "active":
        raise ConflictError("Link already exists between these cards")

    # Hidden → unhide directly, skip LLM
    if existing and existing.status == "hidden":
        graph.unhide_link(existing.id)
        cards_store.touch(from_id)
        cards_store.touch(to_id)
        return existing

    # Blocked pair → unblock first, then fall through to LLM evaluation
    if graph.is_blocked(from_id, to_id):
        graph.unblock_pair(from_id, to_id)

    judgement = judge.evaluate(
        card_a.content, card_a.meaning,
        card_b.content, card_b.meaning,
    )

    link = graph.add_link(
        from_id, to_id,
        LinkKind(judgement.link),
        confidence=1.0,
        reason=judgement.reason,
    )

    cards_store.touch(from_id)
    cards_store.touch(to_id)
    return link


def hide_graph_link(
    *,
    link_id: str,
    graph: Any,
    cards_store: Any,
) -> None:
    """Hide a link (user wants to stop seeing it but not permanently delete)."""
    lk = graph.get_link(link_id)
    if lk is None:
        raise NotFoundError("Link", link_id)
    try:
        graph.hide_link(link_id)
    except KeyError:
        raise NotFoundError("Link", link_id)
    cards_store.touch(lk.from_id)
    cards_store.touch(lk.to_id)


def unhide_graph_link(
    *,
    link_id: str,
    graph: Any,
    cards_store: Any,
) -> None:
    """Unhide a previously hidden link."""
    lk = graph.get_link(link_id)
    if lk is None:
        raise NotFoundError("Link", link_id)
    try:
        graph.unhide_link(link_id)
    except KeyError:
        raise NotFoundError("Link", link_id)
    cards_store.touch(lk.from_id)
    cards_store.touch(lk.to_id)


def delete_graph_link(
    *,
    link_id: str,
    graph: Any,
    cards_store: Any,
) -> None:
    """Hard-delete a link and block the pair from being re-created."""
    try:
        from_id, to_id = graph.hard_delete_link(link_id)
    except KeyError:
        raise NotFoundError("Link", link_id)
    cards_store.touch(from_id)
    cards_store.touch(to_id)
