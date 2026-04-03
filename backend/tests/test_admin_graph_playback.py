"""Tests for admin graph-playback endpoint."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from kg.cards import Card


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_cards_db(user_dir: Path, cards: list[dict]) -> None:
    """Create a cards.db with given card rows."""
    db_path = user_dir / "cards.db"
    engine = create_engine(f"sqlite:///{db_path.absolute()}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        for c in cards:
            session.add(Card(**c))
        session.commit()


def _make_graph_json(user_dir: Path, notebook_id: str, links: list[dict]) -> None:
    """Write a graph_{notebook_id}.json as list (production format)."""
    (user_dir / f"graph_{notebook_id}.json").write_text(json.dumps(links))


# ---------------------------------------------------------------------------
# compute_graph_playback unit tests
# ---------------------------------------------------------------------------

class TestComputeGraphPlayback:
    def test_empty_user_dir(self, tmp_path: Path):
        """No cards.db, no graph JSON -> empty nodes/edges."""
        from kg.admin_graph_playback import compute_graph_playback

        result = compute_graph_playback(tmp_path, "default")
        assert result["user_id"] == ""
        assert result["notebook_id"] == "default"
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_cards_only_no_graph(self, tmp_path: Path):
        """Cards but no graph file -> nodes with no edges."""
        from kg.admin_graph_playback import compute_graph_playback

        _make_cards_db(tmp_path, [
            {"id": "c1", "content": "hello", "meaning": "你好",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 1, tzinfo=UTC)},
            {"id": "c2", "content": "world", "meaning": "世界",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 2, tzinfo=UTC)},
        ])

        result = compute_graph_playback(tmp_path, "default")
        assert len(result["nodes"]) == 2
        assert result["edges"] == []
        assert result["nodes"][0]["id"] == "c1"
        assert result["nodes"][0]["label"] == "hello"
        assert result["nodes"][0]["meaning"] == "你好"
        assert result["nodes"][1]["id"] == "c2"

    def test_cards_and_links(self, tmp_path: Path):
        """Cards + active links -> correct nodes and edges, sorted by created_at."""
        from kg.admin_graph_playback import compute_graph_playback

        _make_cards_db(tmp_path, [
            {"id": "c1", "content": "hello", "meaning": "你好",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 2, tzinfo=UTC)},
            {"id": "c2", "content": "world", "meaning": "世界",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 1, tzinfo=UTC)},
        ])
        _make_graph_json(tmp_path, "default", [
            {"id": "l1", "from_id": "c1", "to_id": "c2",
             "kind": "contrasts_with", "confidence": 0.85, "reason": "opposites",
             "created_at": "2025-01-03T00:00:00+00:00", "status": "active"},
        ])

        result = compute_graph_playback(tmp_path, "default")
        # nodes sorted by created_at: c2 (Jan 1) before c1 (Jan 2)
        assert result["nodes"][0]["id"] == "c2"
        assert result["nodes"][1]["id"] == "c1"
        # edges
        assert len(result["edges"]) == 1
        edge = result["edges"][0]
        assert edge["from_id"] == "c1"
        assert edge["to_id"] == "c2"
        assert edge["kind"] == "contrasts_with"
        assert edge["confidence"] == 0.85
        assert edge["reason"] == "opposites"

    def test_deleted_cards_excluded(self, tmp_path: Path):
        """Deleted cards should not appear in nodes."""
        from kg.admin_graph_playback import compute_graph_playback

        _make_cards_db(tmp_path, [
            {"id": "c1", "content": "hello", "meaning": "你好",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 1, tzinfo=UTC)},
            {"id": "c2", "content": "deleted", "meaning": "已刪除",
             "notebook_id": "default", "is_deleted": True,
             "created_at": datetime(2025, 1, 2, tzinfo=UTC)},
        ])

        result = compute_graph_playback(tmp_path, "default")
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["id"] == "c1"

    def test_inactive_links_excluded(self, tmp_path: Path):
        """Only active links appear in edges."""
        from kg.admin_graph_playback import compute_graph_playback

        _make_cards_db(tmp_path, [
            {"id": "c1", "content": "hello", "meaning": "你好",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 1, tzinfo=UTC)},
        ])
        _make_graph_json(tmp_path, "default", [
            {"id": "l1", "from_id": "c1", "to_id": "c2",
             "kind": "contrasts_with", "confidence": 0.9, "reason": "test",
             "created_at": "2025-01-02T00:00:00+00:00", "status": "active"},
            {"id": "l2", "from_id": "c1", "to_id": "c3",
             "kind": "contrasts_with", "confidence": 0.5, "reason": "test",
             "created_at": "2025-01-03T00:00:00+00:00", "status": "deprecated"},
            {"id": "l3", "from_id": "c1", "to_id": "c4",
             "kind": "contrasts_with", "confidence": 0.5, "reason": "test",
             "created_at": "2025-01-04T00:00:00+00:00", "status": "hidden"},
        ])

        result = compute_graph_playback(tmp_path, "default")
        assert len(result["edges"]) == 1
        assert result["edges"][0]["from_id"] == "c1"

    def test_all_active_cards_returned(self, tmp_path: Path):
        """All active cards are returned as nodes, even those without edges."""
        from kg.admin_graph_playback import compute_graph_playback

        _make_cards_db(tmp_path, [
            {"id": "c1", "content": "hello", "meaning": "你好",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 1, tzinfo=UTC)},
            {"id": "c2", "content": "world", "meaning": "世界",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 2, tzinfo=UTC)},
            {"id": "c3", "content": "orphan", "meaning": "孤兒",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 3, tzinfo=UTC)},
        ])
        _make_graph_json(tmp_path, "default", [
            {"id": "l1", "from_id": "c1", "to_id": "c2",
             "kind": "contrasts_with", "confidence": 0.9, "reason": "test",
             "created_at": "2025-01-04T00:00:00+00:00", "status": "active"},
        ])

        result = compute_graph_playback(tmp_path, "default")
        # All 3 active cards returned, even c3 which has no edges
        assert len(result["nodes"]) == 3
        node_ids = [n["id"] for n in result["nodes"]]
        assert "c3" in node_ids
