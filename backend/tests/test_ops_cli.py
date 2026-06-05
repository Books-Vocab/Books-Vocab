"""ops_cli.py 單元測試 — 用 tmp_path 建立假 DB 驗證核心函數。"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ops_helpers import (
    _create_judge_log_db,
    _create_token_usage_db,
    _create_translate_log_db,
    _hours_ago_iso,
    _now_iso,
)
from ops_helpers import (
    run_ops_cli as _run_cli,
)


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


class TestHelp:
    """--help 應正常輸出。"""

    def test_help(self, tmp_path):
        result = _run_cli(str(tmp_path), "--help")
        assert result.returncode == 0
        assert "user-quota" in result.stdout
