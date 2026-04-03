"""Tests for admin graph-density endpoint."""
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
    """Write a graph_{notebook_id}.json with given link dicts."""
    data = {}
    for link in links:
        data[link["id"]] = link
    (user_dir / f"graph_{notebook_id}.json").write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# compute_graph_density unit tests
# ---------------------------------------------------------------------------

class TestComputeGraphDensity:
    def test_empty_user_dir(self, tmp_path: Path):
        """No cards.db, no graph JSON → empty points."""
        from kg.admin_graph_density import compute_graph_density

        result = compute_graph_density(tmp_path, "default")
        assert result["user_id"] == ""
        assert result["notebook_id"] == "default"
        assert result["points"] == []

    def test_cards_only(self, tmp_path: Path):
        """Cards but no links → density stays 0."""
        from kg.admin_graph_density import compute_graph_density

        _make_cards_db(tmp_path, [
            {"id": "c1", "content": "hello", "meaning": "你好",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 1, tzinfo=UTC)},
            {"id": "c2", "content": "world", "meaning": "世界",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 2, tzinfo=UTC)},
        ])

        result = compute_graph_density(tmp_path, "default")
        assert len(result["points"]) == 2
        assert all(p["event"] == "card" for p in result["points"])
        assert result["points"][0]["cum_cards"] == 1
        assert result["points"][0]["density"] == 0.0
        assert result["points"][1]["cum_cards"] == 2
        assert result["points"][1]["density"] == 0.0

    def test_cards_and_links(self, tmp_path: Path):
        """Mixed cards and links produce correct cumulative density."""
        from kg.admin_graph_density import compute_graph_density

        _make_cards_db(tmp_path, [
            {"id": "c1", "content": "hello", "meaning": "你好",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 1, tzinfo=UTC)},
            {"id": "c2", "content": "world", "meaning": "世界",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 2, tzinfo=UTC)},
        ])
        _make_graph_json(tmp_path, "default", [
            {"id": "l1", "from_id": "c1", "to_id": "c2",
             "kind": "contrasts_with", "confidence": 0.9, "reason": "test",
             "created_at": "2025-01-03T00:00:00+00:00", "status": "active"},
        ])

        result = compute_graph_density(tmp_path, "default")
        assert len(result["points"]) == 3
        # After 2 cards and 1 link: density = 1/2 = 0.5
        last = result["points"][-1]
        assert last["event"] == "link"
        assert last["cum_cards"] == 2
        assert last["cum_links"] == 1
        assert last["density"] == 0.5

    def test_deleted_cards_excluded(self, tmp_path: Path):
        """Deleted cards should not appear in the timeline."""
        from kg.admin_graph_density import compute_graph_density

        _make_cards_db(tmp_path, [
            {"id": "c1", "content": "hello", "meaning": "你好",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 1, tzinfo=UTC)},
            {"id": "c2", "content": "deleted", "meaning": "已刪除",
             "notebook_id": "default", "is_deleted": True,
             "created_at": datetime(2025, 1, 2, tzinfo=UTC)},
        ])

        result = compute_graph_density(tmp_path, "default")
        assert len(result["points"]) == 1

    def test_inactive_links_excluded(self, tmp_path: Path):
        """Only active links count."""
        from kg.admin_graph_density import compute_graph_density

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

        result = compute_graph_density(tmp_path, "default")
        link_events = [p for p in result["points"] if p["event"] == "link"]
        assert len(link_events) == 1

    def test_chronological_order(self, tmp_path: Path):
        """Events must be sorted by timestamp."""
        from kg.admin_graph_density import compute_graph_density

        _make_cards_db(tmp_path, [
            {"id": "c1", "content": "hello", "meaning": "你好",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 3, tzinfo=UTC)},
        ])
        _make_graph_json(tmp_path, "default", [
            {"id": "l1", "from_id": "c1", "to_id": "c2",
             "kind": "contrasts_with", "confidence": 0.9, "reason": "test",
             "created_at": "2025-01-01T00:00:00+00:00", "status": "active"},
        ])

        result = compute_graph_density(tmp_path, "default")
        assert result["points"][0]["event"] == "link"
        assert result["points"][1]["event"] == "card"

    def test_graph_json_as_list(self, tmp_path: Path):
        """Graph JSON stored as list (production format) should work."""
        from kg.admin_graph_density import compute_graph_density

        _make_cards_db(tmp_path, [
            {"id": "c1", "content": "hello", "meaning": "你好",
             "notebook_id": "default", "is_deleted": False,
             "created_at": datetime(2025, 1, 1, tzinfo=UTC)},
        ])
        # Write as list (production format), not dict
        links = [
            {"id": "l1", "from_id": "c1", "to_id": "c2",
             "kind": "contrasts_with", "confidence": 0.9, "reason": "test",
             "created_at": "2025-01-02T00:00:00+00:00", "status": "active"},
        ]
        (tmp_path / "graph_default.json").write_text(json.dumps(links))

        result = compute_graph_density(tmp_path, "default")
        assert len(result["points"]) == 2
        assert result["points"][1]["event"] == "link"
