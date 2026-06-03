"""Graph link operations: create, hide, unhide, delete.

Touch barrier (#720 Q2)
-----------------------
Each op mutates the graph, then bumps both endpoint cards' ``updated_at`` via
``cards_store.touch()``. That bump is what makes the change visible to iOS: the
client pulls deltas through ``get_modified_since(updated_at)`` and, on seeing a
card change, re-fetches that card's links. If ``touch`` were to fail *after* a
successful graph mutation with no guard, the graph would have changed but no
card's ``updated_at`` moved -> the client would *permanently* miss the change
and graph/card state would silently diverge.

``_touch_both`` closes that silent window:

* It always attempts *both* endpoints (a failure on the first must not skip the
  second -- if at least one card's ``updated_at`` advances, the client still
  re-fetches that card's links and converges).
* Any failure is logged at ERROR (observable, not swallowed) and re-raised so
  the caller / HTTP layer surfaces an error instead of a fake success.

Reversible callers (hide / unhide, and create_manual_link's unhide branch) wrap
the barrier and roll the graph mutation back on failure, keeping graph and card
state consistent. ``delete`` and the create-new-link path are not cleanly
reversible (hard_delete is destructive; add_link's inverse adds a blocked pair),
so they rely on the barrier's observability + re-raise contract alone.
"""

from __future__ import annotations

import logging
from typing import Any

from .exceptions import ConflictError, NotFoundError

logger = logging.getLogger(__name__)


def _touch_both(cards_store: Any, from_id: str, to_id: str) -> None:
    """Bump updated_at on both endpoints; never silently swallow a failure.

    Both endpoints are always attempted, even if the first raises, so the
    client can still converge from whichever side succeeded. The first
    exception encountered is logged at ERROR and re-raised after both attempts.
    """
    first_error: BaseException | None = None
    for card_id in (from_id, to_id):
        try:
            cards_store.touch(card_id)
        except Exception as exc:  # noqa: BLE001 - re-raised below after logging
            if first_error is None:
                first_error = exc
            logger.error(
                "cards_store.touch failed for card %s after graph mutation; "
                "updated_at not bumped, client may miss this change",
                card_id,
                exc_info=True,
            )
    if first_error is not None:
        raise first_error


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

    # Hidden → unhide directly, skip LLM. Reversible: roll back to hidden if the
    # touch barrier fails so graph and card state stay consistent.
    if existing and existing.status == "hidden":
        graph.unhide_link(existing.id)
        try:
            _touch_both(cards_store, from_id, to_id)
        except Exception:
            graph.hide_link(existing.id)
            raise
        return existing

    # Blocked pair → unblock first, then fall through to LLM evaluation
    if graph.is_blocked(from_id, to_id):
        graph.unblock_pair(from_id, to_id)

    judgement = judge.evaluate(
        card_a.content, card_a.meaning,
        card_b.content, card_b.meaning,
        from_id=from_id, to_id=to_id,
    )

    link = graph.add_link(
        from_id, to_id,
        LinkKind(judgement.link),
        confidence=1.0,
        reason=judgement.reason,
    )

    # New link is not cleanly reversible (add_link's inverse, hard_delete, would
    # introduce a blocked pair). Rely on the barrier: observable + re-raise.
    _touch_both(cards_store, from_id, to_id)
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
    except KeyError as exc:
        raise NotFoundError("Link", link_id) from exc
    # Reversible: unhide on touch failure to keep graph/card state consistent.
    try:
        _touch_both(cards_store, lk.from_id, lk.to_id)
    except Exception:
        graph.unhide_link(link_id)
        raise


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
    # Reversible: re-hide on touch failure to keep graph/card state consistent.
    try:
        _touch_both(cards_store, lk.from_id, lk.to_id)
    except Exception:
        graph.hide_link(link_id)
        raise


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
    # hard_delete is destructive and not cleanly reversible. Rely on the
    # barrier: observable (logged) + re-raise instead of a silent divergence.
    _touch_both(cards_store, from_id, to_id)
