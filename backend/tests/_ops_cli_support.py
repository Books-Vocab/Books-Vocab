# ruff: noqa: F401, I001
"""Shared fixtures and helpers for the sharded backend test family."""

"""ops_cli.py 單元測試 — 用 tmp_path 建立假 DB 驗證核心函數。"""

import json

import sqlite3

import sys

from datetime import UTC, datetime

from pathlib import Path

import pytest

from ops_helpers import (
    CLI_PATH,
    _create_judge_log_db,
    _create_llm_errors_db,
    _create_pipeline_runs_db,
    _create_token_usage_db,
    _create_translate_log_db,
    _hours_ago_iso,
    _now_iso,
)

from ops_helpers import (
    run_ops_cli as _run_cli,
)

if str(CLI_PATH.parent) not in sys.path:
    sys.path.insert(0, str(CLI_PATH.parent))

from ops_cli import _bucket_key, _flatten_user_config  # noqa: E402

def _create_cards_db(path: Path, rows: list[tuple]) -> None:
    """建立 users/<uid>/cards.db 並灌入測試資料。"""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE card (
            id TEXT PRIMARY KEY,
            content TEXT,
            meaning TEXT,
            is_deleted INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO card (id, content, meaning, is_deleted, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
__all__ = (
    'CLI_PATH',
    'Path',
    'UTC',
    '_bucket_key',
    '_create_cards_db',
    '_create_judge_log_db',
    '_create_llm_errors_db',
    '_create_pipeline_runs_db',
    '_create_token_usage_db',
    '_create_translate_log_db',
    '_flatten_user_config',
    '_hours_ago_iso',
    '_now_iso',
    '_run_cli',
    'datetime',
    'json',
    'pytest',
    'sqlite3',
    'sys',
)
