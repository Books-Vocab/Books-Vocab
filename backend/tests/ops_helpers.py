"""ops 測試共用 helper — 時間字串 + DB seeder + ops_cli 子程序執行器。"""

import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

CLI_PATH = Path(__file__).resolve().parent.parent / "ops_cli.py"


def run_ops_cli(data_dir: str, *args: str) -> subprocess.CompletedProcess:
    """執行 ops_cli.py，設定 KG_DATA_DIR + PYTHONPATH。

    PYTHONPATH 指向 backend/src：子程序可能跑在裸 python（非專案 venv），
    缺它則 `import kg.*` 失敗。單一執行器集中於此，杜絕各測試檔 env 設定漂移。
    """
    env = {**os.environ, "KG_DATA_DIR": data_dir, "PYTHONPATH": str(CLI_PATH.parent / "src")}
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _hours_ago_iso(hours: int) -> str:
    t = datetime.now(UTC) - timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _create_token_usage_db(path: Path, rows: list[tuple], *, with_provider: bool = False) -> None:
    """建立 token_usage.db 並灌入測試資料。rows: (uid, call_type, in, out, created_at[, provider])。"""
    schema_extra = ", provider TEXT" if with_provider else ""
    conn = sqlite3.connect(str(path / "token_usage.db"))
    conn.execute(
        f"""
        CREATE TABLE token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            call_type TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL{schema_extra}
        )
        """
    )
    cols = "user_id, call_type, input_tokens, output_tokens, created_at"
    if with_provider:
        cols += ", provider"
    ph = ", ".join("?" * (6 if with_provider else 5))
    conn.executemany(f"INSERT INTO token_usage ({cols}) VALUES ({ph})", rows)
    conn.commit()
    conn.close()


def _create_pipeline_runs_db(path: Path, rows: list[tuple]) -> None:
    """建立 pipeline_runs.db 並灌入測試資料。
    rows: (run_id, user_id, notebook_id, trigger, started_at, ended_at, status, steps)
    """
    conn = sqlite3.connect(str(path / "pipeline_runs.db"))
    conn.execute("""
        CREATE TABLE pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE NOT NULL,
            user_id TEXT NOT NULL,
            notebook_id TEXT NOT NULL,
            trigger TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            steps TEXT NOT NULL DEFAULT '[]'
        )
    """)
    conn.executemany(
        "INSERT INTO pipeline_runs "
        "(run_id, user_id, notebook_id, trigger, started_at, ended_at, status, steps) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def _create_judge_log_db(path: Path, rows: list[tuple]) -> None:
    """建立 judge_log.db 並灌入測試資料。
    rows: (user_id, from_id, to_id, verdict, accepted, created_at[, reject_reason])
    """
    conn = sqlite3.connect(str(path / "judge_log.db"))
    conn.execute("""
        CREATE TABLE judge_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            notebook_id TEXT NOT NULL DEFAULT 'default',
            from_id TEXT NOT NULL,
            to_id TEXT NOT NULL,
            similarity REAL,
            verdict TEXT NOT NULL,
            confidence REAL NOT NULL,
            accepted INTEGER NOT NULL,
            reject_reason TEXT,
            reason TEXT,
            source TEXT NOT NULL DEFAULT 'auto',
            created_at TEXT NOT NULL
        )
    """)
    conn.executemany(
        "INSERT INTO judge_log (user_id, notebook_id, from_id, to_id, verdict, confidence, accepted, created_at, reject_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def _create_translate_log_db(path: Path, rows: list[tuple]) -> None:
    """建立 translate_log.db 並灌入測試資料。
    rows: (user_id, operation, word, context, context_hash, source_lang, target_lang, response_raw, latency_ms, created_at)
    """
    conn = sqlite3.connect(str(path / "translate_log.db"))
    conn.execute("""
        CREATE TABLE translate_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            word TEXT NOT NULL,
            context TEXT,
            context_hash TEXT NOT NULL,
            source_lang TEXT NOT NULL,
            target_lang TEXT NOT NULL,
            response_raw TEXT NOT NULL,
            latency_ms INTEGER,
            created_at TEXT NOT NULL
        )
    """)
    conn.executemany(
        "INSERT INTO translate_log (user_id, operation, word, context, context_hash, source_lang, target_lang, response_raw, latency_ms, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def _create_llm_errors_db(path: Path, rows: list[tuple]) -> None:
    """建立 llm_errors.db 並灌入測試資料。
    rows: (user_id, call_type, provider, model, error_class, status_code, message, created_at)
    """
    conn = sqlite3.connect(str(path / "llm_errors.db"))
    conn.execute("""
        CREATE TABLE llm_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            call_type TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            error_class TEXT NOT NULL,
            status_code INTEGER,
            message TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.executemany(
        "INSERT INTO llm_errors (user_id, call_type, provider, model, error_class, status_code, message, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
