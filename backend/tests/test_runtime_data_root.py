"""Runtime SQLite stores stay on the data root the app lifespan locked.

The lifespan takes the single-worker lock on ``settings.data_dir`` and sweeps
that directory's orphaned rows at startup.  Every later runtime read/write of
the same stores must land in that directory too: if ``KG_DATA_DIR`` points
elsewhere, rows written there are invisible to the next startup's sweep and
stay non-terminal forever (and the process touches a root it holds no lock on).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kg import pipeline_log, runtime_data_root
from kg import vocab_add_link_operation as operations
from kg.api import create_app
from kg.settings import KGSettings


@pytest.fixture()
def roots(tmp_path, monkeypatch):
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "users.json").write_text("{}")
    # A sentinel root nothing may create: any runtime access through
    # KG_DATA_DIR would mkdir it on first connection.
    sentinel = tmp_path / "kg-data-dir-sentinel"
    monkeypatch.setenv("KG_DATA_DIR", str(sentinel))
    operations.reset()
    pipeline_log.reset()
    yield locked, sentinel
    operations.reset()
    pipeline_log.reset()


def _settings(data_dir: Path) -> KGSettings:
    return KGSettings(
        data_dir=data_dir,
        jwt_secret="test-secret-key-for-ci-at-least-32-bytes",
        admin_token="adm-secret",
        app_store_allow_unsigned_sync=True,
        app_store_allow_unsigned_notifications=True,
    )


def _statuses(db: Path, table: str, key: str, value: str) -> list[str]:
    with closing(sqlite3.connect(db)) as conn:
        return [row[0] for row in conn.execute(f"SELECT status FROM {table} WHERE {key} = ?", (value,))]


def _start_add_link_operation_and_pipeline_run() -> str:
    operation, created = operations.create_operation(
        user_id="u1", notebook_id="default", idempotency_key="k1", payload={"target_word": "x"}
    )
    assert created
    operations.start_operation(operation["operation_id"])
    pipeline_log.start_run("run-1", "u1", "default", "manual")
    pipeline_log.start_step("run-1", "translate")
    return operation["operation_id"]


def test_runtime_reads_and_writes_use_the_locked_data_root(roots):
    locked, sentinel = roots

    with TestClient(create_app(_settings(locked))):
        operation_id = _start_add_link_operation_and_pipeline_run()
        assert operations.get_operation("u1", operation_id)["status"] == "running"
        assert [run["run_id"] for run in pipeline_log.get_runs("u1")] == ["run-1"]

    assert not sentinel.exists(), "runtime opened the KG_DATA_DIR root instead of the locked settings.data_dir"
    assert _statuses(locked / operations._DB_FILENAME, "vocab_add_link_operations", "operation_id", operation_id) == [
        "running"
    ]
    assert _statuses(locked / pipeline_log._DB_FILENAME, "pipeline_runs", "run_id", "run-1") == ["running"]


def test_restart_on_the_locked_root_terminalizes_what_the_previous_process_left_running(roots):
    locked, sentinel = roots

    with TestClient(create_app(_settings(locked))):
        operation_id = _start_add_link_operation_and_pipeline_run()
    operations.reset()
    pipeline_log.reset()  # the process died; only SQLite survives

    with TestClient(create_app(_settings(locked))):
        pass

    assert _statuses(locked / operations._DB_FILENAME, "vocab_add_link_operations", "operation_id", operation_id) == [
        "interrupted"
    ]
    assert _statuses(locked / pipeline_log._DB_FILENAME, "pipeline_runs", "run_id", "run-1") == ["interrupted"]
    assert not sentinel.exists()


def test_binding_lives_exactly_as_long_as_the_worker_lock(roots):
    locked, sentinel = roots
    assert runtime_data_root.bound() is None

    with TestClient(create_app(_settings(locked))):
        assert runtime_data_root.bound() == locked
        assert runtime_data_root.current() == locked

    # Lock released: the process no longer owns the root, so nothing stays bound
    # and module-level callers resolve KG_DATA_DIR again.
    assert runtime_data_root.bound() is None
    assert runtime_data_root.current() == sentinel


def test_release_only_drops_the_binding_it_was_given(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path / "env"))
    first, second = tmp_path / "first", tmp_path / "second"
    try:
        runtime_data_root.bind(first)
        runtime_data_root.bind(second)
        runtime_data_root.release(first)  # stale release from an app that was replaced
        assert runtime_data_root.current() == second

        runtime_data_root.release(second)
        assert runtime_data_root.bound() is None
        assert runtime_data_root.current() == tmp_path / "env"
    finally:
        runtime_data_root.release(first)
        runtime_data_root.release(second)
