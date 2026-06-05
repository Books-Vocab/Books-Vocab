"""ops_cli.py 單元測試 — 用 tmp_path 建立假 DB 驗證核心函數。"""

import sqlite3
import subprocess
import sys
from pathlib import Path

from ops_helpers import _create_token_usage_db, _hours_ago_iso, _now_iso

# ops_cli.py 位於 backend/ 根目錄，需要直接 import
CLI_PATH = Path(__file__).resolve().parent.parent / "ops_cli.py"


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


def _run_cli(data_dir: str, *args: str) -> subprocess.CompletedProcess:
    """執行 ops_cli.py，設定 KG_DATA_DIR 環境變數。"""
    import os

    env = {**os.environ, "KG_DATA_DIR": data_dir}
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        capture_output=True,
        text=True,
        env=env,
    )


class TestUserQuota:
    """user-quota 子指令。"""

    def test_basic_output(self, tmp_path):
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("user1", "translate", 1_000_000, 500_000, now),
            ("user1", "embed", 2_000_000, 0, now),
        ])
        result = _run_cli(str(tmp_path), "user-quota", "user1")
        assert result.returncode == 0
        # translate: 0.10 + 0.20 = 0.30
        # embed: 2 * 0.00025 = 0.0005
        assert "0.3005" in result.stdout or "0.300500" in result.stdout or "$0.30" in result.stdout

    def test_unknown_user_zero(self, tmp_path):
        _create_token_usage_db(tmp_path, [])
        result = _run_cli(str(tmp_path), "user-quota", "nobody")
        assert result.returncode == 0
        assert "0.00" in result.stdout


class TestUserStats:
    """user-stats 子指令。"""

    def test_basic_stats(self, tmp_path):
        uid = "user1"
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        now = _now_iso()
        _create_cards_db(user_dir / "cards.db", [
            ("c1", "hello", "你好", 0, now, now),
            ("c2", "world", "世界", 0, now, now),
            ("c3", "deleted", "已刪", 1, now, now),
        ])
        result = _run_cli(str(tmp_path), "user-stats", uid)
        assert result.returncode == 0
        assert "3" in result.stdout  # 總數
        assert "2" in result.stdout  # 有效

    def test_missing_user(self, tmp_path):
        result = _run_cli(str(tmp_path), "user-stats", "ghost")
        assert result.returncode != 0 or "not found" in result.stdout.lower() or "not found" in result.stderr.lower()


class TestQuotaOverview:
    """quota-overview 子指令。"""

    def test_multiple_users(self, tmp_path):
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("user1", "translate", 100_000, 50_000, now),
            ("user2", "explain", 200_000, 100_000, now),
        ])
        result = _run_cli(str(tmp_path), "quota-overview")
        assert result.returncode == 0
        assert "user1" in result.stdout
        assert "user2" in result.stdout


class TestActiveUsers:
    """active-users 子指令。"""

    def test_default_24h(self, tmp_path):
        now = _now_iso()
        old = _hours_ago_iso(48)
        _create_token_usage_db(tmp_path, [
            ("active_user", "translate", 1000, 500, now),
            ("old_user", "translate", 1000, 500, old),
        ])
        result = _run_cli(str(tmp_path), "active-users")
        assert result.returncode == 0
        assert "active_user" in result.stdout
        # old_user 48 小時前，不應出現
        assert "old_user" not in result.stdout

    def test_custom_hours(self, tmp_path):
        old = _hours_ago_iso(48)
        _create_token_usage_db(tmp_path, [
            ("old_user", "translate", 1000, 500, old),
        ])
        result = _run_cli(str(tmp_path), "active-users", "72")
        assert result.returncode == 0
        assert "old_user" in result.stdout


class TestDbQuery:
    """db-query 子指令。"""

    def test_select(self, tmp_path):
        uid = "user1"
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        now = _now_iso()
        _create_cards_db(user_dir / "cards.db", [
            ("c1", "hello", "你好", 0, now, now),
        ])
        result = _run_cli(str(tmp_path), "db-query", uid, "SELECT id, content FROM card")
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_count(self, tmp_path):
        uid = "user1"
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        now = _now_iso()
        _create_cards_db(user_dir / "cards.db", [
            ("c1", "a", "x", 0, now, now),
            ("c2", "b", "y", 0, now, now),
        ])
        result = _run_cli(str(tmp_path), "db-query", uid, "SELECT count(*) FROM card")
        assert result.returncode == 0
        assert "2" in result.stdout


class TestProviderAwarePricing:
    """計價走 kg.quota_service.token_cost_usd — provider-aware。"""

    def test_deepseek_priced_provider_aware(self, tmp_path):
        """provider='deepseek' 的 row 用 deepseek 費率 (0.14/0.28),非 gemini 0.10/0.40。"""
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("user1", "translate", 1_000_000, 1_000_000, now, "deepseek"),
        ], with_provider=True)
        result = _run_cli(str(tmp_path), "user-quota", "user1")
        assert result.returncode == 0
        # deepseek: 0.14 + 0.28 = 0.42（非 gemini 的 0.50）
        assert "0.42" in result.stdout
        assert "0.500000" not in result.stdout

    def test_legacy_no_provider_column_still_works(self, tmp_path):
        """無 provider 欄的 legacy DB → 不報錯,gemini fallback (0.10/0.40)。"""
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("user1", "translate", 1_000_000, 1_000_000, now),
        ])
        result = _run_cli(str(tmp_path), "user-quota", "user1")
        assert result.returncode == 0
        # 無 provider → routed gemini: 0.10 + 0.40 = 0.50
        assert "0.50" in result.stdout

    def test_quota_overview_provider_aware(self, tmp_path):
        """quota-overview 同樣 provider-aware。"""
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("user1", "translate", 1_000_000, 1_000_000, now, "deepseek"),
        ], with_provider=True)
        result = _run_cli(str(tmp_path), "quota-overview")
        assert result.returncode == 0
        assert "0.42" in result.stdout


class TestHelp:
    """--help 應正常輸出。"""

    def test_help(self, tmp_path):
        result = _run_cli(str(tmp_path), "--help")
        assert result.returncode == 0
        assert "user-quota" in result.stdout
