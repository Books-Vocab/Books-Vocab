import json
import os

import kg.graph.persistence as persistence
from kg.graph import GraphStore


def test_atomic_json_write_fsyncs_before_rename(tmp_path, monkeypatch):
    """Durability contract: the tmp file's data must be fsynced BEFORE the
    rename, otherwise an OS/power crash can persist the rename ahead of the
    bytes → a zero-length or torn primary file. We spy on os.fsync to prove it
    runs during the write (and still fsync for real so the file is intact)."""
    fsynced_fds: list[int] = []
    real_fsync = os.fsync

    def spy(fd):
        fsynced_fds.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(persistence.os, "fsync", spy)

    path = tmp_path / "durable.json"
    GraphStore._atomic_json_write(path, [{"a": 1}])

    assert json.loads(path.read_text()) == [{"a": 1}]
    assert fsynced_fds, "expected os.fsync to be called (file data not durable before rename)"


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
