"""Graph density time-series computation for admin analytics."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlmodel import create_engine

logger = logging.getLogger(__name__)


def _read_graph_links(graph_path: Path) -> list[dict]:
    """Read graph JSON, handling both list and dict formats. Returns [] on error."""
    if not graph_path.exists():
        return []
    try:
        raw = json.loads(graph_path.read_text())
    except (json.JSONDecodeError, ValueError):
        logger.warning("Malformed graph JSON: %s", graph_path)
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return list(raw.values())
    return []


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
                try:
                    ts = _parse_ts(created_at)
                except (ValueError, TypeError):
                    continue
                events.append((ts, "card"))
        finally:
            engine.dispose()

    # ── links from graph JSON ──────────────────────────────────────────
    graph_path = user_dir / f"graph_{notebook_id}.json"
    for link in _read_graph_links(graph_path):
        if link.get("status") != "active":
            continue
        created_at = link.get("created_at")
        if not created_at:
            continue
        try:
            ts = _parse_ts(created_at)
        except (ValueError, TypeError):
            continue
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
    elif isinstance(value, (int, float)):
        ts = datetime.fromtimestamp(value, tz=UTC)
    else:
        ts = datetime.fromisoformat(str(value))
    # Normalize naive datetimes (e.g. from SQLite) to UTC
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts
