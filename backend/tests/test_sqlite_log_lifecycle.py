"""Contract tests for the shared SQLite log connection lifecycle."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS marker (value TEXT NOT NULL)")


def test_lifecycle_reuses_switches_resets_and_reopens(tmp_path: Path):
    from kg.sqlite_lifecycle import SQLiteLifecycle

    lifecycle = SQLiteLifecycle()
    first_path = tmp_path / "first.db"
    second_path = tmp_path / "second.db"

    first = lifecycle.get_connection(first_path, _init_schema)
    assert lifecycle.get_connection(first_path, _init_schema) is first

    second = lifecycle.get_connection(second_path, _init_schema)
    assert second is not first
    with pytest.raises(sqlite3.ProgrammingError):
        first.execute("SELECT 1")

    lifecycle.reset()
    with pytest.raises(sqlite3.ProgrammingError):
        second.execute("SELECT 1")
    reopened = lifecycle.get_connection(second_path, _init_schema)
    assert reopened is not second
    assert reopened.execute("SELECT 1").fetchone() == (1,)


def test_lifecycle_serializes_concurrent_first_open(tmp_path: Path):
    from kg.sqlite_lifecycle import SQLiteLifecycle

    lifecycle = SQLiteLifecycle()
    db_path = tmp_path / "concurrent.db"

    def open_connection() -> int:
        return id(lifecycle.get_connection(db_path, _init_schema))

    with ThreadPoolExecutor(max_workers=8) as pool:
        connection_ids = list(pool.map(lambda _: open_connection(), range(32)))

    assert len(set(connection_ids)) == 1


def _write_log_entry(module_name: str, suffix: str) -> None:
    if module_name == "kg.judge_log":
        from kg import judge_log

        judge_log.record(
            user_id="u1", notebook_id="nb", from_id=f"from-{suffix}",
            to_id="to", similarity=0.5, verdict="accept", confidence=0.9,
            accepted=True,
        )
    elif module_name == "kg.translate_log":
        from kg import translate_log

        translate_log.record(
            user_id="u1", operation="translate", word=f"word-{suffix}",
            context="", context_hash=suffix, source_lang="en",
            target_lang="zh-Hant", response_raw="{}", latency_ms=1,
        )
    elif module_name == "kg.pipeline_log":
        from kg import pipeline_log

        pipeline_log.start_run(f"run-{suffix}", "u1", "nb", "test")
    elif module_name == "kg.token_tracker":
        from kg import token_tracker

        token_tracker.record("u1", "translate", 1, 1)
    elif module_name == "kg.podcast_progress":
        from kg import podcast_progress

        podcast_progress.upsert(
            user_id="u1", series_id=f"series-{suffix}", ep_num=1,
            position_sec=1, duration_sec=2, updated_at="2026-01-01T00:00:00Z",
        )
    elif module_name == "kg.llm_error_log":
        from kg import llm_error_log

        llm_error_log.record(user_id="u1", call_type="translate", error_class="Error")
    elif module_name == "kg.admin_audit":
        from kg import admin_audit

        admin_audit.record_audit(admin_uid="admin", action=f"test-{suffix}")
    else:
        raise AssertionError(module_name)


@pytest.mark.parametrize(
    "module_name,db_name",
    [
        ("kg.judge_log", "judge_log.db"),
        ("kg.translate_log", "translate_log.db"),
        ("kg.pipeline_log", "pipeline_runs.db"),
        ("kg.token_tracker", "token_usage.db"),
        ("kg.podcast_progress", "podcast_progress.db"),
        ("kg.llm_error_log", "llm_errors.db"),
        ("kg.admin_audit", "admin_audit.db"),
    ],
)
def test_log_modules_switch_data_dir_without_private_conn_access(
    module_name: str, db_name: str, tmp_path: Path, monkeypatch
):
    module = __import__(module_name, fromlist=["reset"])
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    monkeypatch.setenv("KG_DATA_DIR", str(first_dir))
    module.reset()
    if module_name == "kg.podcast_progress":
        module.set_data_dir(first_dir)

    _write_log_entry(module_name, uuid4().hex)
    assert (first_dir / db_name).exists()

    monkeypatch.setenv("KG_DATA_DIR", str(second_dir))
    if module_name == "kg.podcast_progress":
        module.set_data_dir(second_dir)
    _write_log_entry(module_name, uuid4().hex)
    assert (second_dir / db_name).exists()


@pytest.mark.parametrize(
    "module_name",
    [
        "kg.judge_log",
        "kg.translate_log",
        "kg.pipeline_log",
        "kg.token_tracker",
        "kg.podcast_progress",
        "kg.llm_error_log",
        "kg.admin_audit",
    ],
)
def test_log_modules_expose_public_reset(module_name: str):
    module = __import__(module_name, fromlist=["reset"])

    assert callable(module.reset)
    module.reset()
