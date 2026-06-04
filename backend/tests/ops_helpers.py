"""ops 測試共用 helper — 時間字串 + token_usage.db seeder。"""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


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
