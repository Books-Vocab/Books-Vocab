import json
from pathlib import Path

from kg.graph import GraphStore


def test_atomic_json_write_creates_backup(tmp_path):
    """Verify _atomic_json_write creates .bak file on overwrite."""
    path = tmp_path / "test.json"
    GraphStore._atomic_json_write(path, [{"a": 1}])
    assert json.loads(path.read_text()) == [{"a": 1}]
    # Second write should create .bak
    GraphStore._atomic_json_write(path, [{"a": 2}])
    assert json.loads(path.read_text()) == [{"a": 2}]
    bak = path.with_suffix(".json.bak")
    assert bak.exists()
    assert json.loads(bak.read_text()) == [{"a": 1}]


def test_atomic_json_write_no_indent(tmp_path):
    """Verify indent=None produces compact JSON."""
    path = tmp_path / "compact.json"
    GraphStore._atomic_json_write(path, [[1, 2]], indent=None)
    raw = path.read_text()
    assert "\n" not in raw


def test_atomic_json_write_creates_parent_dirs(tmp_path):
    """Verify parent directories are created if missing."""
    path = tmp_path / "sub" / "dir" / "data.json"
    GraphStore._atomic_json_write(path, {"key": "value"})
    assert json.loads(path.read_text()) == {"key": "value"}
