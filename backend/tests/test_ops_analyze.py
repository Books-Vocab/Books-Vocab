"""ops_analyze.py — 計價走 kg.quota_service.token_cost_usd 的 smoke 測試。"""

import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "ops_analyze.py"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _create_token_usage_db(path: Path, rows: list[tuple], *, with_provider: bool) -> None:
    """rows: (uid, call_type, in, out, created_at[, provider])。"""
    cols = "user_id, call_type, input_tokens, output_tokens, created_at"
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
    if with_provider:
        cols += ", provider"
    ph = ", ".join("?" * (6 if with_provider else 5))
    conn.executemany(f"INSERT INTO token_usage ({cols}) VALUES ({ph})", rows)
    conn.commit()
    conn.close()


def _setup_user(tmp_path: Path, uid: str) -> Path:
    udir = tmp_path / "users" / uid
    udir.mkdir(parents=True)
    conn = sqlite3.connect(str(udir / "cards.db"))
    conn.execute(
        "CREATE TABLE card (id TEXT PRIMARY KEY, content TEXT, meaning TEXT, "
        "is_deleted INTEGER DEFAULT 0)"
    )
    conn.execute("INSERT INTO card VALUES ('c1', 'hello', '你好', 0)")
    conn.commit()
    conn.close()
    (udir / "graph_default.json").write_text("[]")
    return udir


def _run(data_dir: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "KG_DATA_DIR": data_dir}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, env=env,
    )


class TestLevel1:
    def test_level_1_smoke(self, tmp_path):
        _setup_user(tmp_path, "user1")
        _create_token_usage_db(tmp_path, [
            ("user1", "translate", 1_000_000, 1_000_000, _now_iso()),
        ], with_provider=False)
        result = _run(str(tmp_path), "user1", "1")
        assert result.returncode == 0
        # gemini routed: 0.10 + 0.40 = 0.5000
        assert "0.5000" in result.stdout


class TestLevel2:
    def test_level_2_smoke(self, tmp_path):
        _setup_user(tmp_path, "user1")
        _create_token_usage_db(tmp_path, [
            ("user1", "translate", 1_000_000, 1_000_000, _now_iso()),
        ], with_provider=False)
        result = _run(str(tmp_path), "user1", "2")
        assert result.returncode == 0
        assert "0.5000" in result.stdout


class TestProviderAware:
    def test_deepseek_priced_provider_aware(self, tmp_path):
        """provider='deepseek' row → deepseek 費率 0.42,非 gemini 0.50。"""
        _setup_user(tmp_path, "user1")
        _create_token_usage_db(tmp_path, [
            ("user1", "translate", 1_000_000, 1_000_000, _now_iso(), "deepseek"),
        ], with_provider=True)
        result = _run(str(tmp_path), "user1", "2")
        assert result.returncode == 0
        assert "0.4200" in result.stdout

    def test_legacy_no_provider_column(self, tmp_path):
        """無 provider 欄 → gemini fallback,不報錯。"""
        _setup_user(tmp_path, "user1")
        _create_token_usage_db(tmp_path, [
            ("user1", "translate", 1_000_000, 1_000_000, _now_iso()),
        ], with_provider=False)
        result = _run(str(tmp_path), "user1", "1")
        assert result.returncode == 0
        assert "0.5000" in result.stdout
