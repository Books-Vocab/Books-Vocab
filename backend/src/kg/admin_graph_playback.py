"""Graph playback data — full nodes + edges with timestamps for time-based visualization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .admin_graph_density import _parse_ts, _read_active_cards, _read_graph_links


def compute_graph_playback(
    user_dir: Path,
    notebook_id: str,
    *,
    user_id: str = "",
) -> dict[str, Any]:
    """Return all active nodes and edges for a user's notebook, sorted for playback.

    Nodes = all active cards (even those without edges).
    Edges = all active graph links.
    Both lists are sorted chronologically with deterministic response-field
    tie-breakers for playback animation.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # ── cards from SQLite ──────────────────────────────────────────────
    cards_db = user_dir / "cards.db"
    for card_id, content, meaning, created_at in _read_active_cards(
        cards_db, notebook_id, "id, content, meaning, created_at"
    ):
        try:
            ts = _parse_ts(created_at)
        except (ValueError, TypeError):
            continue
        nodes.append(
            {
                "id": card_id,
                "label": content,
                "meaning": meaning,
                "created_at": ts.isoformat(),
            }
        )

    # ── links from graph JSON ──────────────────────────────────────────
    graph_path = user_dir / f"graph_{notebook_id}.json"
    for link in _read_graph_links(graph_path):
        if link.get("status") != "active":
            continue
        created_at = link.get("created_at")
        from_id = link.get("from_id")
        to_id = link.get("to_id")
        if not created_at or not from_id or not to_id:
            continue
        try:
            ts = _parse_ts(created_at)
        except (ValueError, TypeError):
            continue
        edges.append(
            {
                "from_id": from_id,
                "to_id": to_id,
                "kind": link.get("kind", ""),
                "confidence": link.get("confidence", 0),
                "reason": link.get("reason", ""),
                "created_at": ts.isoformat(),
            }
        )

    # ── sort chronologically with deterministic tie-breakers ───────────
    nodes.sort(key=lambda n: (n["created_at"], n["id"]))
    edges.sort(
        key=lambda e: (
            e["created_at"],
            e["from_id"],
            e["to_id"],
            e["kind"],
            e["confidence"],
            e["reason"],
        )
    )

    return {
        "user_id": user_id,
        "notebook_id": notebook_id,
        "nodes": nodes,
        "edges": edges,
    }
