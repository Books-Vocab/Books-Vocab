"""投影面對損毀資料 fail-loud、對真空資料維持空的契約測試。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from kg.ops_world_projection import WorldProjectionError, project_user_world


_CARD_COLUMNS = ("id", "content", "meaning", "notebook_id", "is_deleted")
_CARD_ROW = ("c1", "meticulous", "careful", "nb1", 0)
_LINK = {
    "id": "l1",
    "from_id": "c1",
    "to_id": "c1",
    "kind": "shares_usage",
    "confidence": 0.7,
    "reason": "test",
    "status": "active",
}


def _world(
    tmp_path: Path,
    *,
    columns: tuple[str, ...] = _CARD_COLUMNS,
    rows: tuple[tuple[object, ...], ...] = (_CARD_ROW,),
    graph: str | None = None,
) -> Path:
    user_dir = tmp_path / "users" / "u1"
    user_dir.mkdir(parents=True)
    (tmp_path / "users.json").write_text(
        json.dumps({"u1": {"id": "u1", "config": {}}}),
        encoding="utf-8",
    )
    conn = sqlite3.connect(str(user_dir / "cards.db"))
    definitions = ", ".join(
        f"{column} {'INTEGER' if column == 'is_deleted' else 'TEXT'}"
        for column in columns
    )
    conn.execute(f"CREATE TABLE card ({definitions})")
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(f"INSERT INTO card VALUES ({placeholders})", rows)
    conn.commit()
    conn.close()
    if graph is not None:
        (user_dir / "graph_nb1.json").write_text(graph, encoding="utf-8")
    return tmp_path


def _project(tmp_path: Path, **kwargs):
    return project_user_world("u1", data_root=_world(tmp_path, **kwargs))


class TestWorldProjectionErrorSemantics:
    def test_card_schema_drift_raises_named_projection_error(self, tmp_path):
        with pytest.raises(WorldProjectionError) as exc_info:
            _project(
                tmp_path,
                columns=("zid", "zcontent"),
                rows=(("c1", "meticulous"),),
            )
        assert "cards.db" in str(exc_info.value)

    def test_corrupt_graph_json_raises_named_projection_error(self, tmp_path):
        with pytest.raises(WorldProjectionError) as exc_info:
            _project(tmp_path, graph="{ this is not json")
        assert "graph_nb1.json" in str(exc_info.value)

    def test_graph_json_wrong_shape_raises_named_projection_error(self, tmp_path):
        with pytest.raises(WorldProjectionError) as exc_info:
            _project(tmp_path, graph="42")
        assert "graph_nb1.json" in str(exc_info.value)

    def test_healthy_list_graph_stays_projectable(self, tmp_path):
        world = _project(tmp_path, graph=json.dumps([_LINK]))
        assert [card["content"] for card in world["cards"]] == ["meticulous"]
        assert world["graphs"][0]["links"] == [
            {**_LINK, "from_content": "meticulous", "to_content": "meticulous"}
        ]

    def test_healthy_dict_graph_stays_projectable(self, tmp_path):
        world = _project(tmp_path, graph=json.dumps({"l1": _LINK}))
        assert world["graphs"][0]["links"][0]["kind"] == "shares_usage"
        assert world["graphs"][0]["links"][0]["from_content"] == "meticulous"

    def test_empty_graph_file_stays_empty(self, tmp_path):
        world = _project(tmp_path, graph="[]")
        assert world["cards"]
        assert world["graphs"][0]["links"] == []

    def test_empty_cards_and_graph_stay_empty(self, tmp_path):
        world = _project(tmp_path, rows=(), graph="[]")
        assert world["cards"] == []
        assert world["graphs"][0]["links"] == []
