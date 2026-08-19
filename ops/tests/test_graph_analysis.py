"""Regression tests for the graph-analysis diagnostic data layout."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "graph_analysis.py"


def _load_module(monkeypatch: pytest.MonkeyPatch, loaded_paths: list[Path]):
    """Load the script without requiring numpy in the no-project test env."""
    fake_numpy = types.ModuleType("numpy")

    def load(path: Path):
        loaded_paths.append(Path(path))
        return object()

    fake_numpy.load = load  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "numpy", fake_numpy)

    spec = importlib.util.spec_from_file_location("graph_analysis_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _user_dir(tmp_path: Path) -> Path:
    user_dir = tmp_path / "users" / "u1"
    user_dir.mkdir(parents=True)
    with sqlite3.connect(user_dir / "cards.db") as conn:
        conn.execute("CREATE TABLE card (id TEXT PRIMARY KEY, content TEXT, is_deleted INTEGER)")
    return user_dir


def _write_required_files(user_dir: Path) -> None:
    (user_dir / "embeddings_default.npy").write_bytes(b"canonical embedding fixture")
    (user_dir / "card_ids_default.json").write_text('["c1", "c2"]', encoding="utf-8")


def test_load_data_reads_only_canonical_default_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    loaded_paths: list[Path] = []
    graph_analysis = _load_module(monkeypatch, loaded_paths)
    user_dir = _user_dir(tmp_path)
    _write_required_files(user_dir)
    (user_dir / "graph_default.json").write_text(
        json.dumps({"links": [{"id": "l1", "from_id": "c1", "to_id": "c2"}]}),
        encoding="utf-8",
    )
    (user_dir / "candidates_default.json").write_text('[{"from_id": "c1", "to_id": "c2"}]', encoding="utf-8")

    # Legacy files must not be consulted when the canonical fixture exists.
    (user_dir / "embeddings.npy").write_bytes(b"legacy embedding fixture")
    (user_dir / "card_ids.json").write_text("not json", encoding="utf-8")
    (user_dir / "graph.json").write_text("not json", encoding="utf-8")
    (user_dir / "candidates.json").write_text("not json", encoding="utf-8")

    graph_analysis.DATA = tmp_path / "users"
    embeddings, card_ids, links, candidates, conn = graph_analysis.load_data("u1")
    try:
        assert embeddings is not None
        assert card_ids == ["c1", "c2"]
        assert links == [{"id": "l1", "from_id": "c1", "to_id": "c2"}]
        assert candidates == [{"from_id": "c1", "to_id": "c2"}]
        assert [path.name for path in loaded_paths] == ["embeddings_default.npy"]
    finally:
        conn.close()


@pytest.mark.parametrize("missing_name", ["embeddings_default.npy", "card_ids_default.json"])
def test_load_data_preserves_missing_required_file_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_name: str
):
    loaded_paths: list[Path] = []
    graph_analysis = _load_module(monkeypatch, loaded_paths)
    user_dir = _user_dir(tmp_path)
    _write_required_files(user_dir)
    (user_dir / missing_name).unlink()

    # A legacy counterpart must not satisfy a missing canonical file.
    (user_dir / "embeddings.npy").write_bytes(b"legacy embedding fixture")
    (user_dir / "card_ids.json").write_text('["legacy"]', encoding="utf-8")
    graph_analysis.DATA = tmp_path / "users"

    with pytest.raises(SystemExit, match="Embedding files not found for user 'u1'"):
        graph_analysis.load_data("u1")


@pytest.mark.parametrize(
    ("graph_content", "candidates_content"),
    [
        (None, None),
        ("[]", "[]"),
        ('{"links": []}', "[]"),
    ],
)
def test_load_data_preserves_missing_and_empty_optional_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    graph_content: str | None,
    candidates_content: str | None,
):
    loaded_paths: list[Path] = []
    graph_analysis = _load_module(monkeypatch, loaded_paths)
    user_dir = _user_dir(tmp_path)
    _write_required_files(user_dir)
    if graph_content is not None:
        (user_dir / "graph_default.json").write_text(graph_content, encoding="utf-8")
    if candidates_content is not None:
        (user_dir / "candidates_default.json").write_text(candidates_content, encoding="utf-8")
    graph_analysis.DATA = tmp_path / "users"

    _, _, links, candidates, conn = graph_analysis.load_data("u1")
    try:
        assert links == []
        assert candidates == []
    finally:
        conn.close()
