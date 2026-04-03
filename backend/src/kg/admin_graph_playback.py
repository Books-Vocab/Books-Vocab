"""Graph playback data — full nodes + edges with timestamps for time-based visualization."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlmodel import create_engine

from .admin_graph_density import _parse_ts, _read_graph_links


def compute_graph_playback(
    user_dir: Path,
    notebook_id: str,
    *,
    user_id: str = "",
) -> dict[str, Any]:
    """Return all active nodes and edges for a user's notebook, sorted by created_at.

    Nodes = all active cards (even those without edges).
    Edges = all active graph links.
    Both lists sorted chronologically for playback animation.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # ── cards from SQLite ──────────────────────────────────────────────
    cards_db = user_dir / "cards.db"
    if cards_db.exists():
        engine = create_engine(f"sqlite:///{cards_db.absolute()}")
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT id, content, meaning, created_at FROM card "
                        "WHERE is_deleted = 0 AND notebook_id = :nb"
                    ),
                    {"nb": notebook_id},
                ).fetchall()
            for card_id, content, meaning, created_at in rows:
                ts = _parse_ts(created_at)
                nodes.append({
                    "id": card_id,
                    "label": content,
                    "meaning": meaning,
                    "created_at": ts.isoformat(),
                })
        finally:
            engine.dispose()

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
        edges.append({
            "from_id": from_id,
            "to_id": to_id,
            "kind": link.get("kind", ""),
            "confidence": link.get("confidence", 0),
            "reason": link.get("reason", ""),
            "created_at": ts.isoformat(),
        })

    # ── sort by created_at ─────────────────────────────────────────────
    nodes.sort(key=lambda n: n["created_at"])
    edges.sort(key=lambda e: e["created_at"])

    return {
        "user_id": user_id,
        "notebook_id": notebook_id,
        "nodes": nodes,
        "edges": edges,
    }
