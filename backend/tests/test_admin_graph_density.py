"""Tests for admin graph-density endpoint."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from kg.cards import Card

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_cards_db(user_dir: Path, cards: list[dict]) -> None:
    """Create a cards.db with given card rows."""
    db_path = user_dir / "cards.db"
    engine = create_engine(f"sqlite:///{db_path.absolute()}")
    try:
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            for c in cards:
                session.add(Card(**c))
            session.commit()
    finally:
        engine.dispose()


def test_make_cards_db_disposes_engine(tmp_path: Path, monkeypatch) -> None:
    """The database-building helper must release its SQLAlchemy engine."""
    from sqlalchemy.engine import Engine

    disposed: list[Engine] = []
    original_dispose = Engine.dispose

    def track_dispose(engine: Engine, *args, **kwargs):
        disposed.append(engine)
        return original_dispose(engine, *args, **kwargs)

    monkeypatch.setattr(Engine, "dispose", track_dispose)
    _make_cards_db(tmp_path, [])

    assert disposed, "_make_cards_db must dispose the engine it creates"


def _make_graph_json(user_dir: Path, notebook_id: str, links: list[dict]) -> None:
    """Write a graph_{notebook_id}.json as list (production format)."""
    (user_dir / f"graph_{notebook_id}.json").write_text(json.dumps(links))


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

        _make_cards_db(
            tmp_path,
            [
                {
                    "id": "c1",
                    "content": "hello",
                    "meaning": "你好",
                    "notebook_id": "default",
                    "is_deleted": False,
                    "created_at": datetime(2025, 1, 1, tzinfo=UTC),
                },
                {
                    "id": "c2",
                    "content": "world",
                    "meaning": "世界",
                    "notebook_id": "default",
                    "is_deleted": False,
                    "created_at": datetime(2025, 1, 2, tzinfo=UTC),
                },
            ],
        )

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

        _make_cards_db(
            tmp_path,
            [
                {
                    "id": "c1",
                    "content": "hello",
                    "meaning": "你好",
                    "notebook_id": "default",
                    "is_deleted": False,
                    "created_at": datetime(2025, 1, 1, tzinfo=UTC),
                },
                {
                    "id": "c2",
                    "content": "world",
                    "meaning": "世界",
                    "notebook_id": "default",
                    "is_deleted": False,
                    "created_at": datetime(2025, 1, 2, tzinfo=UTC),
                },
            ],
        )
        _make_graph_json(
            tmp_path,
            "default",
            [
                {
                    "id": "l1",
                    "from_id": "c1",
                    "to_id": "c2",
                    "kind": "contrasts_with",
                    "confidence": 0.9,
                    "reason": "test",
                    "created_at": "2025-01-03T00:00:00+00:00",
                    "status": "active",
                },
            ],
        )

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

        _make_cards_db(
            tmp_path,
            [
                {
                    "id": "c1",
                    "content": "hello",
                    "meaning": "你好",
                    "notebook_id": "default",
                    "is_deleted": False,
                    "created_at": datetime(2025, 1, 1, tzinfo=UTC),
                },
                {
                    "id": "c2",
                    "content": "deleted",
                    "meaning": "已刪除",
                    "notebook_id": "default",
                    "is_deleted": True,
                    "created_at": datetime(2025, 1, 2, tzinfo=UTC),
                },
            ],
        )

        result = compute_graph_density(tmp_path, "default")
        assert len(result["points"]) == 1

    def test_inactive_links_excluded(self, tmp_path: Path):
        """Only active links count."""
        from kg.admin_graph_density import compute_graph_density

        _make_cards_db(
            tmp_path,
            [
                {
                    "id": "c1",
                    "content": "hello",
                    "meaning": "你好",
                    "notebook_id": "default",
                    "is_deleted": False,
                    "created_at": datetime(2025, 1, 1, tzinfo=UTC),
                },
            ],
        )
        _make_graph_json(
            tmp_path,
            "default",
            [
                {
                    "id": "l1",
                    "from_id": "c1",
                    "to_id": "c2",
                    "kind": "contrasts_with",
                    "confidence": 0.9,
                    "reason": "test",
                    "created_at": "2025-01-02T00:00:00+00:00",
                    "status": "active",
                },
                {
                    "id": "l2",
                    "from_id": "c1",
                    "to_id": "c3",
                    "kind": "contrasts_with",
                    "confidence": 0.5,
                    "reason": "test",
                    "created_at": "2025-01-03T00:00:00+00:00",
                    "status": "deprecated",
                },
                {
                    "id": "l3",
                    "from_id": "c1",
                    "to_id": "c4",
                    "kind": "contrasts_with",
                    "confidence": 0.5,
                    "reason": "test",
                    "created_at": "2025-01-04T00:00:00+00:00",
                    "status": "hidden",
                },
            ],
        )

        result = compute_graph_density(tmp_path, "default")
        link_events = [p for p in result["points"] if p["event"] == "link"]
        assert len(link_events) == 1

    def test_chronological_order(self, tmp_path: Path):
        """Events must be sorted by timestamp."""
        from kg.admin_graph_density import compute_graph_density

        _make_cards_db(
            tmp_path,
            [
                {
                    "id": "c1",
                    "content": "hello",
                    "meaning": "你好",
                    "notebook_id": "default",
                    "is_deleted": False,
                    "created_at": datetime(2025, 1, 3, tzinfo=UTC),
                },
            ],
        )
        _make_graph_json(
            tmp_path,
            "default",
            [
                {
                    "id": "l1",
                    "from_id": "c1",
                    "to_id": "c2",
                    "kind": "contrasts_with",
                    "confidence": 0.9,
                    "reason": "test",
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "status": "active",
                },
            ],
        )

        result = compute_graph_density(tmp_path, "default")
        assert result["points"][0]["event"] == "link"
        assert result["points"][1]["event"] == "card"

    def test_equal_timestamp_events_are_stable_across_source_order(self, tmp_path: Path):
        """Equal-time events use their source ids instead of storage order."""
        from kg.admin_graph_density import compute_graph_density

        links = [
            {
                "id": "l1",
                "from_id": "c1",
                "to_id": "c2",
                "kind": "contrasts_with",
                "confidence": 0.9,
                "reason": "first",
                "created_at": "2025-01-02T00:00:00+00:00",
                "status": "active",
            },
            {
                "id": "l2",
                "from_id": "c1",
                "to_id": "c3",
                "kind": "contrasts_with",
                "confidence": 0.8,
                "reason": "second",
                "created_at": "2025-01-01T19:00:00-05:00",
                "status": "active",
            },
        ]
        expected_points = [
            {"ts": "2025-01-02T00:00:00+00:00", "event": "card", "cum_cards": 1, "cum_links": 0, "density": 0.0},
            {"ts": "2025-01-02T00:00:00+00:00", "event": "link", "cum_cards": 1, "cum_links": 1, "density": 1.0},
            {"ts": "2025-01-01T19:00:00-05:00", "event": "link", "cum_cards": 1, "cum_links": 2, "density": 2.0},
        ]

        results = []
        for name, ordered_links in (("forward", links), ("reversed", list(reversed(links)))):
            fixture_dir = tmp_path / name
            fixture_dir.mkdir()
            _make_cards_db(
                fixture_dir,
                [
                    {
                        "id": "c1",
                        "content": "hello",
                        "meaning": "你好",
                        "notebook_id": "default",
                        "is_deleted": False,
                        "created_at": datetime(2025, 1, 2, tzinfo=UTC),
                    },
                ],
            )
            _make_graph_json(fixture_dir, "default", ordered_links)
            results.append(compute_graph_density(fixture_dir, "default"))

        assert results[0]["points"] == expected_points
        assert results[1]["points"] == expected_points
        assert results[0] == results[1]

    def test_graph_json_as_dict_fallback(self, tmp_path: Path):
        """Graph JSON stored as dict (legacy format) should also work."""
        from kg.admin_graph_density import compute_graph_density

        _make_cards_db(
            tmp_path,
            [
                {
                    "id": "c1",
                    "content": "hello",
                    "meaning": "你好",
                    "notebook_id": "default",
                    "is_deleted": False,
                    "created_at": datetime(2025, 1, 1, tzinfo=UTC),
                },
            ],
        )
        # Write as dict (legacy format)
        links = {
            "l1": {
                "id": "l1",
                "from_id": "c1",
                "to_id": "c2",
                "kind": "contrasts_with",
                "confidence": 0.9,
                "reason": "test",
                "created_at": "2025-01-02T00:00:00+00:00",
                "status": "active",
            }
        }
        (tmp_path / "graph_default.json").write_text(json.dumps(links))

        result = compute_graph_density(tmp_path, "default")
        assert len(result["points"]) == 2
        assert result["points"][1]["event"] == "link"

    def test_malformed_graph_json(self, tmp_path: Path):
        """Malformed or empty graph JSON should not crash."""
        from kg.admin_graph_density import compute_graph_density

        _make_cards_db(
            tmp_path,
            [
                {
                    "id": "c1",
                    "content": "hello",
                    "meaning": "你好",
                    "notebook_id": "default",
                    "is_deleted": False,
                    "created_at": datetime(2025, 1, 1, tzinfo=UTC),
                },
            ],
        )
        (tmp_path / "graph_default.json").write_text("")
        result = compute_graph_density(tmp_path, "default")
        assert len(result["points"]) == 1  # card only

    def test_link_missing_created_at(self, tmp_path: Path):
        """Links missing created_at should be skipped, not crash."""
        from kg.admin_graph_density import compute_graph_density

        _make_cards_db(
            tmp_path,
            [
                {
                    "id": "c1",
                    "content": "hello",
                    "meaning": "你好",
                    "notebook_id": "default",
                    "is_deleted": False,
                    "created_at": datetime(2025, 1, 1, tzinfo=UTC),
                },
            ],
        )
        links = [
            {
                "id": "l1",
                "from_id": "c1",
                "to_id": "c2",
                "kind": "contrasts_with",
                "confidence": 0.9,
                "reason": "ok",
                "created_at": "2025-01-02T00:00:00+00:00",
                "status": "active",
            },
            {
                "id": "l2",
                "from_id": "c1",
                "to_id": "c3",
                "kind": "contrasts_with",
                "confidence": 0.5,
                "reason": "bad",
                "status": "active",
            },  # no created_at
        ]
        (tmp_path / "graph_default.json").write_text(json.dumps(links))

        result = compute_graph_density(tmp_path, "default")
        link_events = [p for p in result["points"] if p["event"] == "link"]
        assert len(link_events) == 1
