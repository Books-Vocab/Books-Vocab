"""ops_cli.py 單元測試 — 用 tmp_path 建立假 DB 驗證核心函數。"""

import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from ops_helpers import (
    CLI_PATH,
    _create_judge_log_db,
    _create_token_usage_db,
    _create_translate_log_db,
    _hours_ago_iso,
    _now_iso,
)
from ops_helpers import (
    run_ops_cli as _run_cli,
)

# backend/ 不在 pytest 預設 path(conftest 只加 src/);補進來才能直接單元測試
# ops_cli 的純函數(_bucket_key)而非只能跑 subprocess。
if str(CLI_PATH.parent) not in sys.path:
    sys.path.insert(0, str(CLI_PATH.parent))

from ops_cli import _bucket_key  # noqa: E402


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


class TestCardFind:
    """card-find 子指令 — byte-exact 子字串搜尋（免寫 SQL、免處理引號）。"""

    def _setup(self, tmp_path, rows):
        uid = "user1"
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        now = _now_iso()
        _create_cards_db(user_dir / "cards.db", [
            (cid, content, "m", 0, now, now) for cid, content in rows
        ])
        return uid

    def test_finds_substring_case_insensitive(self, tmp_path):
        uid = self._setup(tmp_path, [
            ("c1", "chateau,"),          # 有 trailing comma
            ("c2", "Chateau Margaux"),   # 大寫
            ("c3", "hello"),
        ])
        result = _run_cli(str(tmp_path), "card-find", uid, "chateau")
        assert result.returncode == 0
        # 兩筆 chateau 都命中（case-insensitive），hello 不命中
        assert "c1" in result.stdout
        assert "c2" in result.stdout
        assert "hello" not in result.stdout

    def test_repr_exposes_trailing_comma(self, tmp_path):
        """關鍵：trailing comma / whitespace 在對齊表格中隱形，repr 讓其可見。"""
        uid = self._setup(tmp_path, [("c1", "chateau,")])
        result = _run_cli(str(tmp_path), "card-find", uid, "chateau")
        assert result.returncode == 0
        assert "'chateau,'" in result.stdout  # repr 暴露逗點

    def test_no_match_prints_no_data(self, tmp_path):
        uid = self._setup(tmp_path, [("c1", "hello")])
        result = _run_cli(str(tmp_path), "card-find", uid, "zzz")
        assert result.returncode == 0
        assert "no data" in result.stdout.lower()

    def test_substring_with_sql_wildcards_literal(self, tmp_path):
        """搜尋字串含 % / _ 須當字面字元，不可當 LIKE 萬用字元。"""
        uid = self._setup(tmp_path, [
            ("c1", "100%"),
            ("c2", "abc"),
        ])
        result = _run_cli(str(tmp_path), "card-find", uid, "%")
        assert result.returncode == 0
        assert "c1" in result.stdout
        assert "c2" not in result.stdout

    def test_missing_user(self, tmp_path):
        result = _run_cli(str(tmp_path), "card-find", "ghost", "x")
        assert result.returncode != 0


class TestCardGet:
    """card-get 子指令 — 單卡 byte-exact 垂直 dump（key 可為 id 或 content）。"""

    def _setup(self, tmp_path):
        uid = "user1"
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        now = _now_iso()
        _create_cards_db(user_dir / "cards.db", [
            ("7a365c", "chateau,", "莊園", 0, now, now),
            ("other1", "hello", "你好", 0, now, now),
        ])
        return uid

    def test_get_by_id(self, tmp_path):
        uid = self._setup(tmp_path)
        result = _run_cli(str(tmp_path), "card-get", uid, "7a365c")
        assert result.returncode == 0
        # 垂直 dump:每欄一行，byte-exact repr 暴露 trailing comma
        assert "'chateau,'" in result.stdout
        assert "meaning" in result.stdout
        assert "'莊園'" in result.stdout

    def test_get_by_content_ascii_case_insensitive(self, tmp_path):
        uid = self._setup(tmp_path)
        result = _run_cli(str(tmp_path), "card-get", uid, "HELLO")
        assert result.returncode == 0
        assert "'hello'" in result.stdout
        assert "other1" in result.stdout

    def test_no_match(self, tmp_path):
        uid = self._setup(tmp_path)
        result = _run_cli(str(tmp_path), "card-get", uid, "zzz")
        assert result.returncode == 0
        assert "no card" in result.stdout.lower()

    def test_missing_user(self, tmp_path):
        result = _run_cli(str(tmp_path), "card-get", "ghost", "x")
        assert result.returncode != 0


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


class TestSyncTrace:
    """sync-trace 子指令 — 合併 cards + token_usage + judge_log + translate_log 時間線。"""

    def test_combined_timeline(self, tmp_path):
        uid = "u1"
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        now = _now_iso()

        # cards.db
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        _create_cards_db(user_dir / "cards.db", [
            ("c1", "hello", "你好", 0, now, now),
            ("c2", "world", "世界", 1, now, now),
        ])

        # token_usage.db
        _create_token_usage_db(tmp_path, [
            (uid, "translate", 1000, 500, now),
        ])

        # judge_log.db
        _create_judge_log_db(tmp_path, [
            (uid, "default", "c1", "c2", "related", 0.9, 1, now, None),
        ])

        # translate_log.db
        _create_translate_log_db(tmp_path, [
            (uid, "quick", "hello", None, "h1", "en", "zh", "你好", 120, now),
        ])

        result = _run_cli(str(tmp_path), "sync-trace", uid, "--date", today)
        assert result.returncode == 0
        assert "Sync Trace" in result.stdout
        assert "hello" in result.stdout
        assert "translate" in result.stdout
        assert "judge_accept" in result.stdout or "judge" in result.stdout
        assert "translate_quick" in result.stdout or "quick" in result.stdout

    def test_json_output(self, tmp_path):
        uid = "u1"
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        now = _now_iso()

        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        _create_cards_db(user_dir / "cards.db", [
            ("c1", "hello", "你好", 0, now, now),
        ])
        _create_token_usage_db(tmp_path, [
            (uid, "translate", 1000, 500, now),
        ])

        result = _run_cli(str(tmp_path), "sync-trace", uid, "--date", today, "--json")
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert data["user_id"] == uid
        assert data["date"] == today
        assert len(data["events"]) == 2

    def test_empty_day(self, tmp_path):
        uid = "u1"
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        result = _run_cli(str(tmp_path), "sync-trace", uid, "--date", today)
        assert result.returncode == 0
        assert "Total events: 0" in result.stdout


class TestJsonContract:
    """統一輸出契約 — 每個 data-query 命令都應支援 --json 並回傳合法 JSON。"""

    def _seed(self, tmp_path):
        uid = "u1"
        now = _now_iso()
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        _create_cards_db(user_dir / "cards.db", [
            ("c1", "hello", "你好", 0, now, now),
            ("c2", "world", "世界", 1, now, now),
        ])
        _create_token_usage_db(tmp_path, [
            (uid, "translate", 1000, 500, now),
            (uid, "judge", 200, 100, now),
        ])
        return uid

    def test_user_quota_json(self, tmp_path):
        import json
        uid = self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "user-quota", uid, "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["user_id"] == uid
        assert "used_usd" in d and "hourly" in d

    def test_user_stats_json(self, tmp_path):
        import json
        uid = self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "user-stats", uid, "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["user_id"] == uid
        assert d["total"] == 2 and d["active"] == 1 and d["deleted"] == 1

    def test_quota_overview_json(self, tmp_path):
        import json
        self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "quota-overview", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert isinstance(d["users"], list) and len(d["users"]) == 1

    def test_active_users_json(self, tmp_path):
        import json
        uid = self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "active-users", "48", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["hours"] == 48
        assert d["users"][0]["user_id"] == uid and d["users"][0]["calls"] == 2

    def test_card_find_json(self, tmp_path):
        import json
        uid = self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "card-find", uid, "hello", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["matches"][0]["id"] == "c1" and d["matches"][0]["content"] == "hello"

    def test_card_get_json(self, tmp_path):
        import json
        uid = self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "card-get", uid, "c1", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert len(d["cards"]) == 1 and d["cards"][0]["id"] == "c1"

    def test_db_query_json(self, tmp_path):
        import json
        uid = self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "db-query", uid, "--json",
                     "SELECT", "id", "FROM", "card", "ORDER", "BY", "id")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["columns"] == ["id"]
        assert d["rows"] == [["c1"], ["c2"]]


class TestJsonCountAndSchema:
    """list 命令的頂層 count + db-query --schema（dogfooding 缺口）。"""

    def _seed_cards(self, tmp_path, uid="u1"):
        now = _now_iso()
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        _create_cards_db(user_dir / "cards.db", [
            ("c1", "hello", "你好", 0, now, now),
            ("c2", "help", "幫助", 0, now, now),
        ])
        return uid

    def test_card_find_count(self, tmp_path):
        import json
        uid = self._seed_cards(tmp_path)
        r = _run_cli(str(tmp_path), "card-find", uid, "hel", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == len(d["matches"]) == 2

    def test_active_users_count(self, tmp_path):
        import json
        now = _now_iso()
        _create_token_usage_db(tmp_path, [("u1", "translate", 1, 1, now)])
        r = _run_cli(str(tmp_path), "active-users", "24", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == len(d["users"]) == 1

    def test_db_query_count(self, tmp_path):
        import json
        uid = self._seed_cards(tmp_path)
        r = _run_cli(str(tmp_path), "db-query", uid, "--json", "SELECT id FROM card")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == len(d["rows"]) == 2

    def test_db_query_schema_text(self, tmp_path):
        uid = self._seed_cards(tmp_path)
        r = _run_cli(str(tmp_path), "db-query", uid, "--schema")
        assert r.returncode == 0, r.stderr
        assert "CREATE TABLE" in r.stdout and "card" in r.stdout

    def test_db_query_schema_json(self, tmp_path):
        import json
        uid = self._seed_cards(tmp_path)
        r = _run_cli(str(tmp_path), "db-query", uid, "--schema", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        names = [t["name"] for t in d["tables"]]
        assert "card" in names

    def test_db_query_error_json(self, tmp_path):
        """SQL 錯誤在 --json 模式應回 error JSON + 非零 exit（驗證 sqlite3.Error 路徑）。"""
        import json
        uid = self._seed_cards(tmp_path)
        r = _run_cli(str(tmp_path), "db-query", uid, "--json", "SELECT nope FROM card")
        assert r.returncode != 0
        d = json.loads(r.stdout)
        assert "error" in d and "nope" in d["error"]


class TestFleetOverview:
    """fleet-overview — 跨用戶 cards/links/月 cost 聚合 + FLEET TOTAL。"""

    def _seed_fleet(self, tmp_path):
        import json
        now = _now_iso()
        # user A: 2 active + 1 deleted, 1 link
        ua = tmp_path / "users" / "uA"
        ua.mkdir(parents=True)
        _create_cards_db(ua / "cards.db", [
            ("a1", "x", "X", 0, now, now),
            ("a2", "y", "Y", 0, now, now),
            ("a3", "z", "Z", 1, now, now),
        ])
        (ua / "graph_default.json").write_text(
            json.dumps([{"from_id": "a1", "to_id": "a2"}])
        )
        # user B: 1 active, no graph
        ub = tmp_path / "users" / "uB"
        ub.mkdir(parents=True)
        _create_cards_db(ub / "cards.db", [("b1", "p", "P", 0, now, now)])
        # token_usage: 只有 uA 本月有花費
        _create_token_usage_db(tmp_path, [("uA", "translate", 1000, 500, now)])

    def test_fleet_json(self, tmp_path):
        import json
        self._seed_fleet(tmp_path)
        r = _run_cli(str(tmp_path), "fleet-overview", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == 2
        ua = next(u for u in d["users"] if u["user_id"] == "uA")
        assert ua["cards_total"] == 3 and ua["cards_active"] == 2 and ua["cards_deleted"] == 1
        assert ua["links"] == 1
        assert ua["month_calls"] == 1 and ua["month_cost_usd"] > 0
        assert d["totals"]["cards_active"] == 3  # 2 + 1
        assert d["totals"]["links"] == 1
        assert d["totals"]["users"] == 2

    def test_fleet_text(self, tmp_path):
        self._seed_fleet(tmp_path)
        r = _run_cli(str(tmp_path), "fleet-overview")
        assert r.returncode == 0, r.stderr
        assert "Fleet Overview" in r.stdout
        assert "uA" in r.stdout and "uB" in r.stdout

    def test_fleet_empty(self, tmp_path):
        import json
        r = _run_cli(str(tmp_path), "fleet-overview", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == 0 and d["totals"]["users"] == 0

    def test_corrupt_graph_logged_not_silent(self, tmp_path):
        """工程審計:損壞 graph json 此前被靜默吞掉 → 應計數並 stderr 提示(stdout 仍乾淨)。"""
        import json
        now = _now_iso()
        ua = tmp_path / "users" / "uA"
        ua.mkdir(parents=True)
        _create_cards_db(ua / "cards.db", [("a1", "x", "X", 0, now, now)])
        (ua / "graph_bad.json").write_text("{not valid json")
        r = _run_cli(str(tmp_path), "fleet-overview", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)  # stdout 仍是乾淨 JSON
        ua_row = next(u for u in d["users"] if u["user_id"] == "uA")
        assert ua_row["links"] == 0  # 損壞檔不計但不爆
        assert "skip" in r.stderr.lower() or "unreadable" in r.stderr.lower()


class TestTimeseries:
    """timeseries — cost/calls/active_users 按 day/week/month 分桶趨勢。"""

    def _seed(self, tmp_path):
        # 跨兩日:06-01 有 u1+u2 各一筆,06-02 只有 u1。deepseek 計價可驗 provider-aware。
        _create_token_usage_db(tmp_path, [
            ("u1", "translate", 1_000_000, 1_000_000, "2026-06-01T10:00:00+00:00", "deepseek"),
            ("u2", "translate", 1_000_000, 1_000_000, "2026-06-01T11:00:00+00:00", "deepseek"),
            ("u1", "translate", 1_000_000, 1_000_000, "2026-06-02T10:00:00+00:00", "deepseek"),
        ], with_provider=True)

    def test_calls_by_day_json(self, tmp_path):
        import json
        self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--bucket", "day", "--range", "all", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["metric"] == "calls" and d["bucket"] == "day"
        assert d["count"] == 2
        series = {s["bucket"]: s["value"] for s in d["series"]}
        assert series["2026-06-01"] == 2 and series["2026-06-02"] == 1

    def test_active_users_distinct(self, tmp_path):
        import json
        self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "timeseries", "active_users", "--range", "all", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        series = {s["bucket"]: s["value"] for s in d["series"]}
        # 06-01 distinct = {u1,u2}=2;06-02 = {u1}=1
        assert series["2026-06-01"] == 2 and series["2026-06-02"] == 1

    def test_cost_provider_aware(self, tmp_path):
        import json
        self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "timeseries", "cost", "--range", "all", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        series = {s["bucket"]: s["value"] for s in d["series"]}
        # deepseek 1M+1M = 0.14+0.28 = 0.42/call;06-01 兩筆=0.84,06-02 一筆=0.42
        assert abs(series["2026-06-01"] - 0.84) < 1e-6
        assert abs(series["2026-06-02"] - 0.42) < 1e-6

    def test_bucket_month(self, tmp_path):
        import json
        self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--bucket", "month", "--range", "all", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == 1
        assert d["series"][0]["bucket"] == "2026-06" and d["series"][0]["value"] == 3

    def test_bucket_week(self, tmp_path):
        import json
        _create_token_usage_db(tmp_path, [
            ("u1", "translate", 1, 1, "2026-06-01T10:00:00+00:00"),
            ("u1", "translate", 1, 1, "2026-06-10T10:00:00+00:00"),  # 隔週
        ])
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--bucket", "week", "--range", "all", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == 2  # 兩個不同 ISO week
        assert all(s["bucket"].startswith("2026-W") for s in d["series"])

    def test_uid_filter(self, tmp_path):
        import json
        self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--uid", "u1", "--range", "all", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["uid"] == "u1"
        series = {s["bucket"]: s["value"] for s in d["series"]}
        assert series["2026-06-01"] == 1 and series["2026-06-02"] == 1  # u2 不算

    def test_sorted_ascending(self, tmp_path):
        import json
        self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--range", "all", "--json")
        d = json.loads(r.stdout)
        buckets = [s["bucket"] for s in d["series"]]
        assert buckets == sorted(buckets)

    def test_text_output_has_trend_bar(self, tmp_path):
        self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--range", "all")
        assert r.returncode == 0, r.stderr
        assert "2026-06-01" in r.stdout
        assert "█" in r.stdout  # 趨勢 bar

    def test_trend_legend_shows_baseline(self, tmp_path):
        """產品審計:常數序列 bar 全滿易誤判;印滿格基準值供校準。"""
        self._seed(tmp_path)
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--range", "all")
        assert r.returncode == 0, r.stderr
        assert "滿格 =" in r.stdout

    def test_empty(self, tmp_path):
        import json
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == 0 and d["series"] == []


class TestBucketKey:
    """_bucket_key 純函數單元測試 — 畸形時間戳 + 跨年 ISO 週(工程審計缺口)。"""

    def test_valid_buckets(self):
        ca = "2026-06-05T10:00:00+00:00"
        assert _bucket_key(ca, "day") == "2026-06-05"
        assert _bucket_key(ca, "month") == "2026-06"
        assert _bucket_key(ca, "week") == "2026-W23"

    def test_malformed_dropped_all_granularities(self):
        # 修復前:day/month 盲切([:10]/[:7])回垃圾桶,week 才 drop → 三粒度不一致。
        # 修復後:統一走 _parse_day,三粒度一致回 None。
        for b in ("day", "week", "month"):
            assert _bucket_key("not-a-date", b) is None
            assert _bucket_key("2026/06/05", b) is None
            assert _bucket_key("2026-13-99T00:00:00", b) is None
            assert _bucket_key("", b) is None
            assert _bucket_key(None, b) is None

    def test_cross_year_iso_week(self):
        # 2025-12-31(三)與 2026-01-01(四)同屬 ISO 2026-W01
        assert _bucket_key("2025-12-31T00:00:00", "week") == "2026-W01"
        assert _bucket_key("2026-01-01T00:00:00", "week") == "2026-W01"
        # 2021-01-01(五)屬 ISO 2020-W53
        assert _bucket_key("2021-01-01T00:00:00", "week") == "2020-W53"

    def test_week_string_sort_is_chronological(self):
        assert sorted(["2026-W01", "2020-W53", "2025-W52"]) == \
            ["2020-W53", "2025-W52", "2026-W01"]


class TestTimeseriesFillZero:
    """--fill-zero 補齊零值桶 → 顯式化斷層(dogfood + 產品審計頭號缺口)。"""

    def test_fill_gap_day(self, tmp_path):
        import json
        _create_token_usage_db(tmp_path, [
            ("u1", "translate", 1, 1, "2026-06-01T10:00:00+00:00"),
            ("u1", "translate", 1, 1, "2026-06-04T10:00:00+00:00"),  # 跳過 06-02/03
        ])
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--bucket", "day",
                     "--range", "all", "--fill-zero", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        series = {s["bucket"]: s["value"] for s in d["series"]}
        assert series["2026-06-01"] == 1
        assert series["2026-06-02"] == 0  # 補零
        assert series["2026-06-03"] == 0  # 補零
        assert series["2026-06-04"] == 1
        buckets = [s["bucket"] for s in d["series"]]
        assert buckets == sorted(buckets)  # 連續升冪

    def test_default_no_fill_is_compact(self, tmp_path):
        import json
        _create_token_usage_db(tmp_path, [
            ("u1", "translate", 1, 1, "2026-06-01T10:00:00+00:00"),
            ("u1", "translate", 1, 1, "2026-06-04T10:00:00+00:00"),
        ])
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--bucket", "day",
                     "--range", "all", "--json")  # 無 --fill-zero
        d = json.loads(r.stdout)
        assert d["count"] == 2  # 只有有資料的桶
        assert "2026-06-02" not in [s["bucket"] for s in d["series"]]

    def test_fill_all_range_no_data_empty(self, tmp_path):
        import json
        # range=all 且完全無資料 → 無起點可補 → 空 series 不報錯
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--range", "all",
                     "--fill-zero", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == 0 and d["series"] == []


class TestTimeseriesSinceFilter:
    """--range since 過濾 — 工程審計指出此前零測試覆蓋。"""

    def test_30d_excludes_old(self, tmp_path):
        import json
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("u1", "translate", 1, 1, now),
            ("u1", "translate", 1, 1, "2020-01-01T00:00:00+00:00"),  # 遠在 30d 外
        ])
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--bucket", "month",
                     "--range", "30d", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        buckets = [s["bucket"] for s in d["series"]]
        assert "2020-01" not in buckets  # 被 since cutoff 過濾
        assert d["count"] == 1


class TestHelp:
    """--help 應正常輸出。"""

    def test_help(self, tmp_path):
        result = _run_cli(str(tmp_path), "--help")
        assert result.returncode == 0
        assert "user-quota" in result.stdout
