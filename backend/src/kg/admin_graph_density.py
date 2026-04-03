"""Graph density time-series computation for admin analytics."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlmodel import create_engine


def compute_graph_density(
    user_dir: Path,
    notebook_id: str,
    *,
    user_id: str = "",
) -> dict[str, Any]:
    """Compute cumulative graph density time-series for a user's notebook.

    Returns a dict with ``user_id``, ``notebook_id``, and ``points`` — a
    chronologically-sorted list of events, each carrying cumulative card/link
    counts and the resulting density ratio.
    """
    events: list[tuple[datetime, str]] = []  # (ts, event_type)

    # ── cards from SQLite ──────────────────────────────────────────────
    cards_db = user_dir / "cards.db"
    if cards_db.exists():
        engine = create_engine(f"sqlite:///{cards_db.absolute()}")
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT id, created_at FROM card "
                        "WHERE is_deleted = 0 AND notebook_id = :nb"
                    ),
                    {"nb": notebook_id},
                ).fetchall()
            for _id, created_at in rows:
                ts = _parse_ts(created_at)
                events.append((ts, "card"))
        finally:
            engine.dispose()

    # ── links from graph JSON ──────────────────────────────────────────
    graph_path = user_dir / f"graph_{notebook_id}.json"
    if graph_path.exists():
        raw = json.loads(graph_path.read_text())
        links = raw if isinstance(raw, list) else raw.values()
        for link in links:
            if link.get("status") != "active":
                continue
            ts = _parse_ts(link["created_at"])
            events.append((ts, "link"))

    # ── sort & cumulative scan ─────────────────────────────────────────
    events.sort(key=lambda e: e[0])

    cum_cards = 0
    cum_links = 0
    points: list[dict[str, Any]] = []
    for ts, event_type in events:
        if event_type == "card":
            cum_cards += 1
        else:
            cum_links += 1
        density = cum_links / cum_cards if cum_cards > 0 else 0.0
        points.append({
            "ts": ts.isoformat(),
            "event": event_type,
            "cum_cards": cum_cards,
            "cum_links": cum_links,
            "density": round(density, 6),
        })

    return {
        "user_id": user_id,
        "notebook_id": notebook_id,
        "points": points,
    }


def _parse_ts(value: Any) -> datetime:
    """Parse a timestamp and ensure it is offset-aware (UTC)."""
    from datetime import UTC

    if isinstance(value, datetime):
        ts = value
    else:
        ts = datetime.fromisoformat(str(value))
    # Normalize naive datetimes (e.g. from SQLite) to UTC
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts
