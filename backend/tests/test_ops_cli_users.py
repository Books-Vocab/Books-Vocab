# ruff: noqa: F401, F403, F405, I001
"""test ops cli users.py test ownership shard."""



from _ops_cli_support import *  # noqa: F403



class TestFlattenUserConfig:
    """_flatten_user_config — 攤平 users.json config blob，對齊後端 _build_user_config_response。"""

    def test_empty_config_all_defaults(self):
        flat = _flatten_user_config({})
        assert flat["translation"] == {"source_lang": "en", "target_lang": "zh-Hant"}
        assert flat["vocab_ui"] == {"active_notebook_id": "default", "updated_at": None}
        assert flat["review_mode"]["mode"] == "relaxed"
        assert flat["review_clock"]["is_paused"] is False

    def test_vocab_ui_flattened(self):
        flat = _flatten_user_config({"vocab_ui": {"active_notebook_id": "nb-7", "updated_at": 42.0}})
        assert flat["vocab_ui"] == {"active_notebook_id": "nb-7", "updated_at": 42.0}

    def test_non_dict_group_falls_back_to_default(self):
        # 髒資料（group 不是 dict）退回 default，不爆 —— 對齊 _build_user_config_response 的 isinstance guard。
        flat = _flatten_user_config({"vocab_ui": "garbage", "translation": None})
        assert flat["vocab_ui"]["active_notebook_id"] == "default"
        assert flat["translation"]["source_lang"] == "en"

class TestUserConfig:
    """user-config 子指令 — 唯讀檢視 users.json 的 per-user config（含 vocab_ui active notebook）。"""

    @staticmethod
    def _write_users(data_dir: Path, users: dict) -> None:
        (data_dir / "users.json").write_text(json.dumps(users, ensure_ascii=False))

    def test_json_output_includes_vocab_ui(self, tmp_path):
        self._write_users(tmp_path, {
            "user1": {"config": {"vocab_ui": {"active_notebook_id": "nb-9", "updated_at": 100.0}}}
        })
        result = _run_cli(str(tmp_path), "user-config", "user1", "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["user_id"] == "user1"
        assert payload["config"]["vocab_ui"]["active_notebook_id"] == "nb-9"
        assert payload["config"]["vocab_ui"]["updated_at"] == 100.0

    def test_defaults_when_config_absent(self, tmp_path):
        self._write_users(tmp_path, {"user1": {}})
        result = _run_cli(str(tmp_path), "user-config", "user1", "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["config"]["vocab_ui"]["active_notebook_id"] == "default"
        assert payload["config"]["translation"]["target_lang"] == "zh-Hant"

    def test_unknown_user_errors(self, tmp_path):
        self._write_users(tmp_path, {"user1": {}})
        result = _run_cli(str(tmp_path), "user-config", "nobody")
        assert result.returncode != 0

class TestWorldState:
    def test_json_output_uses_stable_schema_and_disk_graphs(self, tmp_path):
        uid = "user1"
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        now = _now_iso()
        self_users = {
            uid: {"config": {"vocab_ui": {"active_notebook_id": "default", "updated_at": 10.0}}},
            "_email_index": {},
        }
        (tmp_path / "users.json").write_text(json.dumps(self_users, ensure_ascii=False))

        conn = sqlite3.connect(str(user_dir / "notebooks.db"))
        conn.execute(
            "CREATE TABLE notebook (id TEXT PRIMARY KEY, name TEXT, color TEXT, sort_order INTEGER, "
            "is_default INTEGER, created_at TEXT, updated_at TEXT, is_deleted INTEGER, cover_pattern TEXT)"
        )
        conn.execute(
            "INSERT INTO notebook VALUES ('default','Default',NULL,0,1,?,?,0,NULL)",
            (now, now),
        )
        conn.commit()
        conn.close()
        _create_cards_db(user_dir / "cards.db", [("c1", "hello", "你好", 0, now, now)])
        (user_dir / "graph_default.json").write_text(
            json.dumps([{"id": "l1", "from_id": "c1", "to_id": "c2", "kind": "shares_usage", "confidence": 0.7, "reason": "r"}]),
            encoding="utf-8",
        )

        result = _run_cli(str(tmp_path), "world-state", uid, "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["schema"] == "kg.ops_world_state.v1"
        assert payload["user_id"] == uid
        assert payload["config"]["vocab_ui"]["active_notebook_id"] == "default"
        assert payload["cards"][0]["content"] == "hello"
        assert payload["graphs"][0]["links"][0]["id"] == "l1"

    def test_world_diff_matches_expected_projection(self, tmp_path):
        uid = "user1"
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        now = _now_iso()
        (tmp_path / "users.json").write_text(json.dumps({
            uid: {"config": {"review_clock": {"is_paused": True}, "vocab_ui": {"active_notebook_id": "default"}}},
            "_email_index": {},
        }, ensure_ascii=False))

        conn = sqlite3.connect(str(user_dir / "notebooks.db"))
        conn.execute(
            "CREATE TABLE notebook (id TEXT PRIMARY KEY, name TEXT, color TEXT, sort_order INTEGER, "
            "is_default INTEGER, created_at TEXT, updated_at TEXT, is_deleted INTEGER, cover_pattern TEXT)"
        )
        conn.execute(
            "INSERT INTO notebook VALUES ('default','Default','#123456',0,1,?,?,0,'waves')",
            (now, now),
        )
        conn.commit()
        conn.close()
        _create_cards_db(user_dir / "cards.db", [
            ("c1", "hello", "你好", 0, now, now),
            ("c2", "world", "世界", 0, now, now),
        ])
        (user_dir / "graph_default.json").write_text(
            json.dumps([{
                "id": "l1",
                "from_id": "c1",
                "to_id": "c2",
                "kind": "shares_usage",
                "confidence": 0.7,
                "reason": "r",
            }]),
            encoding="utf-8",
        )
        spec = tmp_path / "expect.json"
        spec.write_text(json.dumps({
            "schema": "kg.ops_world_expectation.v1",
            "config": {"review_clock": {"is_paused": True}},
            "notebooks": [{"name": "Default", "cover_pattern": "waves"}],
            "cards": [{"content": "hello", "meaning": "你好"}],
            "graphs": [{
                "notebook": "Default",
                "links": [{"from": "hello", "to": "world", "kind": "shares_usage", "confidence": 0.7}],
            }],
        }, ensure_ascii=False), encoding="utf-8")

        result = _run_cli(str(tmp_path), "world-diff", uid, str(spec), "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["schema"] == "kg.ops_world_diff.v1"
        assert payload["ok"] is True
        assert payload["mismatchCount"] == 0

    def test_world_diff_reports_stable_mismatch_paths(self, tmp_path):
        uid = "user1"
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        now = _now_iso()
        (tmp_path / "users.json").write_text(json.dumps({uid: {"config": {}}, "_email_index": {}}, ensure_ascii=False))
        conn = sqlite3.connect(str(user_dir / "notebooks.db"))
        conn.execute(
            "CREATE TABLE notebook (id TEXT PRIMARY KEY, name TEXT, color TEXT, sort_order INTEGER, "
            "is_default INTEGER, created_at TEXT, updated_at TEXT, is_deleted INTEGER, cover_pattern TEXT)"
        )
        conn.execute("INSERT INTO notebook VALUES ('default','Default',NULL,0,1,?,?,0,NULL)", (now, now))
        conn.commit()
        conn.close()
        _create_cards_db(user_dir / "cards.db", [
            ("c1", "hello", "你好", 0, now, now),
            ("c2", "world", "世界", 0, now, now),
        ])
        (user_dir / "graph_default.json").write_text(
            json.dumps([{
                "id": "l1",
                "from_id": "c1",
                "to_id": "c2",
                "kind": "shares_usage",
                "confidence": 0.2,
                "reason": "actual",
            }]),
            encoding="utf-8",
        )

        spec = tmp_path / "expect-mismatch.json"
        spec.write_text(json.dumps({
            "schema": "kg.ops_world_expectation.v1",
            "config": {"review_clock": {"is_paused": True}},
            "cards": [{"content": "hello", "meaning": "您好"}],
            "graphs": [{
                "notebook": "Default",
                "links": [{"from": "hello", "to": "world", "kind": "shares_usage", "confidence": 0.9}],
            }],
        }, ensure_ascii=False), encoding="utf-8")

        result = _run_cli(str(tmp_path), "world-diff", uid, str(spec), "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["mismatchCount"] >= 3
        paths = {item["path"] for item in payload["mismatches"]}
        assert "config.review_clock" in paths or "config.review_clock.is_paused" in paths
        assert "cards[hello].meaning" in paths
        assert "graphs[Default].links[hello->world:shares_usage].confidence" in paths

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
