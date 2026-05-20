"""ops_cli.py cost / cost-overview 子命令 — 唯讀 cost-by-call_type 拆解測試。"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CLI_PATH = Path(__file__).resolve().parent.parent / "ops_cli.py"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _hours_ago_iso(hours: int) -> str:
    t = datetime.now(timezone.utc) - timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _create_token_usage_db(path: Path, rows: list[tuple], *, with_provider: bool = False) -> None:
    """rows: (uid, call_type, in, out, created_at[, provider])。"""
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


def _run_cli(data_dir: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "KG_DATA_DIR": data_dir}
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        capture_output=True, text=True, env=env,
    )


class TestCost:
    def test_cost_breakdown_by_call_type(self, tmp_path):
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("u1", "judge", 1_000_000, 100_000, now),
            ("u1", "enrich", 500_000, 200_000, now),
            ("u1", "translate_quick", 300_000, 50_000, now),
        ])
        r = _run_cli(str(tmp_path), "cost", "u1", "--range", "all")
        assert r.returncode == 0
        assert "judge" in r.stdout
        assert "enrich" in r.stdout
        assert "translate_quick" in r.stdout

    def test_cost_json_output(self, tmp_path):
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("u1", "judge", 1_000_000, 100_000, now),
            ("u1", "enrich", 500_000, 200_000, now),
        ])
        r = _run_cli(str(tmp_path), "cost", "u1", "--range", "all", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["user_id"] == "u1"
        assert "judge" in data["by_call_type"]
        assert "enrich" in data["by_call_type"]
        assert data["by_call_type"]["judge"]["calls"] == 1
        assert data["total_cost_usd"] > 0

    def test_cost_range_filter(self, tmp_path):
        """25h 前的 row 應被 --range 24h 濾掉。"""
        _create_token_usage_db(tmp_path, [
            ("u1", "translate_quick", 10_000_000, 0, _hours_ago_iso(25)),  # 舊:gemini 1.00
            ("u1", "translate_quick", 1_000_000, 0, _now_iso()),            # 新:gemini 0.10
        ])
        r = _run_cli(str(tmp_path), "cost", "u1", "--range", "24h", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        # 只算 24h 內 → 1M in * 0.10 = 0.10,不含舊的 1.00
        assert abs(data["total_cost_usd"] - 0.10) < 1e-6
        assert data["by_call_type"]["translate_quick"]["calls"] == 1

    def test_cost_provider_aware(self, tmp_path):
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("u1", "translate_quick", 1_000_000, 1_000_000, now, "deepseek"),
        ], with_provider=True)
        r = _run_cli(str(tmp_path), "cost", "u1", "--range", "all", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        # deepseek 0.14 + 0.28 = 0.42
        assert abs(data["total_cost_usd"] - 0.42) < 1e-6

    def test_cost_legacy_no_provider_column(self, tmp_path):
        """無 provider 欄的 legacy DB → gemini fallback,不報錯。"""
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("u1", "translate_quick", 1_000_000, 1_000_000, now),
        ], with_provider=False)
        r = _run_cli(str(tmp_path), "cost", "u1", "--range", "all", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        # gemini 0.10 + 0.40 = 0.50
        assert abs(data["total_cost_usd"] - 0.50) < 1e-6


class TestCostOverview:
    def test_cost_overview_ranking(self, tmp_path):
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("small_user", "translate_quick", 100_000, 0, now),
            ("big_user", "judge", 10_000_000, 0, now),
        ])
        r = _run_cli(str(tmp_path), "cost-overview", "--range", "all", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        users = data["users"]
        assert users[0]["user_id"] == "big_user"
        assert users[1]["user_id"] == "small_user"
        assert users[0]["total_cost_usd"] > users[1]["total_cost_usd"]

    def test_cost_overview_text(self, tmp_path):
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("u1", "judge", 1_000_000, 0, now),
        ])
        r = _run_cli(str(tmp_path), "cost-overview", "--range", "all")
        assert r.returncode == 0
        assert "u1" in r.stdout
