# ruff: noqa: F401, F403, F405, I001
"""test ops cli queries.py test ownership shard."""



from _ops_cli_support import *  # noqa: F403



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


class TestUserStatsOrdering:
    """user-stats recent activity ordering."""

    def test_recent_orders_mixed_offsets_by_utc_instant_with_id_tiebreaker(self, tmp_path):
        uid = "user1"
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        _create_cards_db(user_dir / "cards.db", [
            ("tie-a", "tie a", "", 0, "2026-08-27T13:00:00+01:00", "2026-08-27T13:00:00+01:00"),
            ("newest", "newest", "", 0, "2026-08-27T12:30:00+00:00", "2026-08-27T12:30:00+00:00"),
            ("tie-z", "tie z", "", 0, "2026-08-27T12:00:00+00:00", "2026-08-27T12:00:00+00:00"),
            ("oldest", "oldest", "", 0, "2026-08-27T11:30:00+00:00", "2026-08-27T11:30:00+00:00"),
        ])

        result = _run_cli(str(tmp_path), "user-stats", uid, "--json")

        assert result.returncode == 0, result.stderr
        assert [card["id"] for card in json.loads(result.stdout)["recent"]] == [
            "newest", "tie-z", "tie-a", "oldest",
        ]


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

    @pytest.fixture()
    def _seeded(self, tmp_path):
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
        return tmp_path, uid

    @pytest.mark.parametrize(
        "cmd_args,check",
        [
            (["user-quota", "u1"], lambda d: d["user_id"] == "u1" and "used_usd" in d),
            (["user-stats", "u1"], lambda d: d["user_id"] == "u1" and d["total"] == 2),
            (["quota-overview"], lambda d: isinstance(d["users"], list) and len(d["users"]) == 1),
            (["active-users", "48"], lambda d: d["hours"] == 48 and d["users"][0]["calls"] == 2),
            (["card-find", "u1", "hello"], lambda d: d["matches"][0]["id"] == "c1"),
            (["card-get", "u1", "c1"], lambda d: len(d["cards"]) == 1 and d["cards"][0]["id"] == "c1"),
            (["db-query", "u1", "--json", "SELECT", "id", "FROM", "card", "ORDER", "BY", "id"],
             lambda d: d["columns"] == ["id"] and d["rows"] == [["c1"], ["c2"]]),
        ],
    )
    def test_json_contract(self, _seeded, cmd_args, check):
        tmp_path, _ = _seeded
        r = _run_cli(str(tmp_path), *cmd_args, "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert check(d)

class TestJsonCountAndSchema:
    """list 命令的頂層 count + db-query --schema（dogfooding 缺口）。"""

    @pytest.fixture()
    def _seeded_cards(self, tmp_path):
        now = _now_iso()
        user_dir = tmp_path / "users" / "u1"
        user_dir.mkdir(parents=True)
        _create_cards_db(user_dir / "cards.db", [
            ("c1", "hello", "你好", 0, now, now),
            ("c2", "help", "幫助", 0, now, now),
        ])
        return tmp_path

    @pytest.mark.parametrize(
        "cmd_args,check",
        [
            (["card-find", "u1", "hel"], lambda d: d["count"] == len(d["matches"]) == 2),
            (["db-query", "u1", "--json", "SELECT id FROM card"],
             lambda d: d["count"] == len(d["rows"]) == 2),
        ],
    )
    def test_count(self, _seeded_cards, cmd_args, check):
        r = _run_cli(str(_seeded_cards), *cmd_args, "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert check(d)

    def test_active_users_count(self, tmp_path):
        now = _now_iso()
        _create_token_usage_db(tmp_path, [("u1", "translate", 1, 1, now)])
        r = _run_cli(str(tmp_path), "active-users", "24", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == len(d["users"]) == 1

    @pytest.mark.parametrize(
        "extra_args,check",
        [
            (["--schema"], lambda r: "CREATE TABLE" in r.stdout and "card" in r.stdout),
            (["--schema", "--json"], lambda r: "card" in [t["name"] for t in json.loads(r.stdout)["tables"]]),
        ],
    )
    def test_db_query_schema(self, _seeded_cards, extra_args, check):
        r = _run_cli(str(_seeded_cards), "db-query", "u1", *extra_args)
        assert r.returncode == 0, r.stderr
        assert check(r)

    def test_db_query_error_json(self, _seeded_cards):
        """SQL 錯誤在 --json 模式應回 error JSON + 非零 exit（驗證 sqlite3.Error 路徑）。"""
        r = _run_cli(str(_seeded_cards), "db-query", "u1", "--json", "SELECT nope FROM card")
        assert r.returncode != 0
        d = json.loads(r.stdout)
        assert "error" in d and "nope" in d["error"]
