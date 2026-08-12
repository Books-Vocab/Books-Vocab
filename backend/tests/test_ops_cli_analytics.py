# ruff: noqa: F401, F403, F405, I001
"""test ops cli analytics.py test ownership shard."""



from _ops_cli_support import *  # noqa: F403



class TestCostOverview:
    """cost-overview — 全用戶 cost 排名（ops_cli_costs.py）。"""

    def test_cost_overview_json_empty_db(self, tmp_path):
        r = _run_cli(str(tmp_path), "cost-overview", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["range"] == "month"
        assert d["users"] == []
        assert d["count"] == 0

    def test_cost_overview_json_with_data(self, tmp_path):
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("u1", "translate", 1000, 500, now),
            ("u2", "judge", 200, 100, now),
        ])
        r = _run_cli(str(tmp_path), "cost-overview", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == 2
        assert {u["user_id"] for u in d["users"]} == {"u1", "u2"}
        # Descending by cost
        costs = [u["total_cost_usd"] for u in d["users"]]
        assert costs == sorted(costs, reverse=True)

class TestAnalyzeSmoke:
    """analyze — thin wrapper around ops_analyze.py subprocess."""

    def test_analyze_runs_without_crash(self, tmp_path):
        """Smoke test: analyze must not crash on empty data dir."""
        r = _run_cli(str(tmp_path), "analyze", "u1", "basic")
        # ops_analyze.py may 1 on empty data, but must not traceback
        assert "Traceback" not in r.stderr

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

    def test_scalar_graph_no_crash(self, tmp_path):
        """工程審計 HIGH:graph json 為合法 JSON scalar(非 list/dict)→ len() 此前拋
        TypeError 崩潰整個 fleet-overview。修復後視為壞形狀,不計、不爆。"""
        import json
        now = _now_iso()
        ua = tmp_path / "users" / "uA"
        ua.mkdir(parents=True)
        _create_cards_db(ua / "cards.db", [("a1", "x", "X", 0, now, now)])
        (ua / "graph_scalar.json").write_text("42")  # 合法 JSON scalar
        r = _run_cli(str(tmp_path), "fleet-overview", "--json")
        assert r.returncode == 0, r.stderr  # 此前 TypeError exit 1
        d = json.loads(r.stdout)  # stdout 仍是乾淨 JSON,非破碎
        ua_row = next(u for u in d["users"] if u["user_id"] == "uA")
        assert ua_row["links"] == 0

    def test_dict_shaped_graph_counted(self, tmp_path):
        """dict-of-links(以 id 為鍵)形狀應正確計數,語意對齊 canonical reader。"""
        import json
        now = _now_iso()
        ua = tmp_path / "users" / "uA"
        ua.mkdir(parents=True)
        _create_cards_db(ua / "cards.db", [("a1", "x", "X", 0, now, now)])
        (ua / "graph_default.json").write_text(json.dumps({
            "l1": {"from_id": "a", "to_id": "b"},
            "l2": {"from_id": "b", "to_id": "c"},
        }))
        r = _run_cli(str(tmp_path), "fleet-overview", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        ua_row = next(u for u in d["users"] if u["user_id"] == "uA")
        assert ua_row["links"] == 2

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

    def test_trend_legend_integer_metric(self, tmp_path):
        """工程審計 LOW:calls 滿格基準應印整數(2 非 2.0),與表格欄位一致。"""
        self._seed(tmp_path)  # calls 桶 max = 2
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--range", "all")
        assert r.returncode == 0, r.stderr
        assert "滿格 = 2" in r.stdout and "滿格 = 2.0" not in r.stdout

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

    def test_fill_week_bucket(self, tmp_path):
        import json
        _create_token_usage_db(tmp_path, [
            ("u1", "translate", 1, 1, "2026-06-01T10:00:00+00:00"),  # ISO W23
            ("u1", "translate", 1, 1, "2026-06-22T10:00:00+00:00"),  # ISO W26
        ])
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--bucket", "week",
                     "--range", "all", "--fill-zero", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        series = {s["bucket"]: s["value"] for s in d["series"]}
        assert series["2026-W23"] == 1 and series["2026-W26"] == 1
        assert series.get("2026-W24") == 0 and series.get("2026-W25") == 0  # 中間空週補零

    def test_fill_month_bucket(self, tmp_path):
        import json
        _create_token_usage_db(tmp_path, [
            ("u1", "translate", 1, 1, "2026-01-15T10:00:00+00:00"),
            ("u1", "translate", 1, 1, "2026-04-15T10:00:00+00:00"),
        ])
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--bucket", "month",
                     "--range", "all", "--fill-zero", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        series = {s["bucket"]: s["value"] for s in d["series"]}
        assert series["2026-01"] == 1 and series["2026-04"] == 1
        assert series.get("2026-02") == 0 and series.get("2026-03") == 0  # 中間空月補零

    def test_fill_bounded_all_filtered_zero(self, tmp_path):
        """bounded range + 資料全被 since 過濾掉 → 補出全零軸(since 起點分支,非 min_dt)。"""
        import json
        _create_token_usage_db(tmp_path, [
            ("u1", "translate", 1, 1, "2020-01-01T00:00:00+00:00"),  # 遠在 30d 外
        ])
        r = _run_cli(str(tmp_path), "timeseries", "calls", "--bucket", "day",
                     "--range", "30d", "--fill-zero", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] >= 28  # ~31 個零桶
        assert all(s["value"] == 0 for s in d["series"])

    def test_fill_zero_active_users_int_type(self, tmp_path):
        """工程審計:active_users 零桶須為 int 0(與非零桶型別一致),非 float。"""
        import json
        _create_token_usage_db(tmp_path, [
            ("u1", "translate", 1, 1, "2026-06-01T10:00:00+00:00"),
            ("u1", "translate", 1, 1, "2026-06-04T10:00:00+00:00"),
        ])
        r = _run_cli(str(tmp_path), "timeseries", "active_users", "--bucket", "day",
                     "--range", "all", "--fill-zero", "--json")
        d = json.loads(r.stdout)
        series = {s["bucket"]: s["value"] for s in d["series"]}
        assert series["2026-06-02"] == 0 and isinstance(series["2026-06-02"], int)

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

class TestTrends:
    """trends — 全域監控趨勢(errors/active/tokens 逐日,唯讀重實作對齊 admin_trends)。"""

    def test_errors_from_judge_rejects(self, tmp_path):
        import json
        now = _now_iso()
        # 2 auto-reject(accepted=0, reject_reason=None)=error;1 accept 不算;
        # 1 degree_cap reject 須排除(對齊 admin_trends DEGREE_CAP 排除)。
        _create_judge_log_db(tmp_path, [
            ("u1", "default", "a", "b", "unrelated", 0.1, 0, now, None),
            ("u1", "default", "a", "c", "unrelated", 0.1, 0, now, None),
            ("u1", "default", "a", "d", "related", 0.9, 1, now, None),
            ("u1", "default", "a", "e", "capped", 0.1, 0, now, "degree_cap"),
        ])
        r = _run_cli(str(tmp_path), "trends", "--window", "7", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["errors_per_day"][-1] == 2  # 今天 2 個真 reject(degree_cap 排除)
        assert d["total_errors"] == 2

    def test_errors_from_pipeline_failures(self, tmp_path):
        import json
        now = _now_iso()
        _create_pipeline_runs_db(tmp_path, [
            ("r1", "u1", "default", "manual", now, now, "failed", "[]"),
            ("r2", "u1", "default", "manual", now, now, "ok", "[]"),  # 不算
        ])
        r = _run_cli(str(tmp_path), "trends", "--window", "7", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["errors_per_day"][-1] == 1  # 只有 failed 計入

    def test_active_users_distinct(self, tmp_path):
        import json
        now = _now_iso()
        _create_token_usage_db(tmp_path, [
            ("u1", "translate", 1, 1, now),
            ("u2", "translate", 1, 1, now),
            ("u1", "judge", 1, 1, now),  # 同 u1 不重複計
        ])
        r = _run_cli(str(tmp_path), "trends", "--window", "7", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["active_users_per_day"][-1] == 2  # distinct u1,u2

    def test_window_and_alignment(self, tmp_path):
        import json
        r = _run_cli(str(tmp_path), "trends", "--window", "10", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["window_days"] == 10
        assert len(d["days"]) == len(d["errors_per_day"]) == \
            len(d["active_users_per_day"]) == len(d["tokens_per_day"]) == 10

    def test_text_render(self, tmp_path):
        now = _now_iso()
        _create_pipeline_runs_db(tmp_path, [
            ("r1", "u1", "default", "manual", now, now, "failed", "[]"),
        ])
        r = _run_cli(str(tmp_path), "trends", "--window", "7")
        assert r.returncode == 0, r.stderr
        assert "Errors" in r.stdout and "Total errors" in r.stdout

    def test_empty_no_crash(self, tmp_path):
        import json
        r = _run_cli(str(tmp_path), "trends", "--window", "7", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["total_errors"] == 0
        assert all(e == 0 for e in d["errors_per_day"])

    def test_readonly_does_not_mutate_pipeline(self, tmp_path):
        """關鍵:ops-cli trends 必須唯讀。此前若 import collect_trends,其 _get_conn 會把
        status='running' 的 row UPDATE 成 'interrupted'(破壞進行中 pipeline)。驗證不被竄改。"""
        import sqlite3 as _sq
        now = _now_iso()
        _create_pipeline_runs_db(tmp_path, [
            ("r_running", "u1", "default", "manual", now, None, "running", "[]"),
        ])
        r = _run_cli(str(tmp_path), "trends", "--window", "7", "--json")
        assert r.returncode == 0, r.stderr
        conn = _sq.connect(str(tmp_path / "pipeline_runs.db"))
        status = conn.execute(
            "SELECT status FROM pipeline_runs WHERE run_id = 'r_running'"
        ).fetchone()[0]
        conn.close()
        assert status == "running"  # 未被竄改 → 唯讀保證成立


    def test_llm_errors_in_trends(self, tmp_path):
        """trends 應獨立回報 llm_errors_per_day(真火),不與業務 errors 混。"""
        import json
        now = _now_iso()
        _create_llm_errors_db(tmp_path, [
            ("u1", "judge", "gemini", "m", "RateLimitError", 429, "rate limited", now),
            ("u1", "translate", "deepseek", "m", "InternalServerError", 500, "boom", now),
        ])
        r = _run_cli(str(tmp_path), "trends", "--window", "7", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["llm_errors_per_day"][-1] == 2
        assert d["total_llm_errors"] == 2
        # 業務 errors 應為 0(無 pipeline/judge 資料)
        assert d["errors_per_day"][-1] == 0
        assert d["total_errors"] == 0

class TestLlmErrors:
    """llm-errors — 真火監控(真實 LLM 失敗 429/5xx/timeout)。"""

    def test_empty_no_crash(self, tmp_path):
        import json
        r = _run_cli(str(tmp_path), "llm-errors", "--window", "7", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["total"] == 0
        assert all(v == 0 for v in d["by_day"].values())
        assert d["recent"] == []

    def test_window_filtering(self, tmp_path):
        import json
        now = _now_iso()
        yesterday = (datetime.now(UTC) - __import__("datetime").timedelta(days=1)).isoformat()
        old = "2020-01-01T00:00:00+00:00"
        _create_llm_errors_db(tmp_path, [
            ("u1", "judge", "gemini", "m", "RateLimitError", 429, "rate limited", now),
            ("u1", "judge", "gemini", "m", "RateLimitError", 429, "rate limited", yesterday),
            ("u1", "judge", "gemini", "m", "RateLimitError", 429, "rate limited", old),
        ])
        r = _run_cli(str(tmp_path), "llm-errors", "--window", "7", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["total"] == 2  # old 被 window 過濾

    def test_by_class_provider_status(self, tmp_path):
        import json
        now = _now_iso()
        _create_llm_errors_db(tmp_path, [
            ("u1", "judge", "gemini", "m", "RateLimitError", 429, "rl", now),
            ("u1", "judge", "gemini", "m", "RateLimitError", 429, "rl2", now),
            ("u1", "translate", "deepseek", "m", "InternalServerError", 500, "boom", now),
            ("u1", "embed", "gemini", "m", "APITimeoutError", None, "timeout", now),
        ])
        r = _run_cli(str(tmp_path), "llm-errors", "--window", "7", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["by_class"]["RateLimitError"] == 2
        assert d["by_class"]["InternalServerError"] == 1
        assert d["by_class"]["APITimeoutError"] == 1
        assert d["by_provider"]["gemini"] == 3
        assert d["by_provider"]["deepseek"] == 1
        assert d["by_status"]["429"] == 2
        assert d["by_status"]["500"] == 1
        assert d["by_status"]["none"] == 1  # timeout has no status_code

    def test_uid_filter(self, tmp_path):
        import json
        now = _now_iso()
        _create_llm_errors_db(tmp_path, [
            ("u1", "judge", "gemini", "m", "RateLimitError", 429, "rl", now),
            ("u2", "judge", "gemini", "m", "RateLimitError", 429, "rl", now),
        ])
        r = _run_cli(str(tmp_path), "llm-errors", "--window", "7", "--uid", "u1", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["total"] == 1

    def test_text_render(self, tmp_path):
        now = _now_iso()
        _create_llm_errors_db(tmp_path, [
            ("u1", "judge", "gemini", "m", "RateLimitError", 429, "rate limited", now),
        ])
        r = _run_cli(str(tmp_path), "llm-errors", "--window", "7")
        assert r.returncode == 0, r.stderr
        assert "LLM Errors" in r.stdout
        assert "RateLimitError" in r.stdout

    def test_readonly_does_not_write(self, tmp_path):
        """ops-cli llm-errors 必須唯讀 — 跑完後 DB 內容與 mtime 不變。"""
        import os
        now = _now_iso()
        _create_llm_errors_db(tmp_path, [
            ("u1", "judge", "gemini", "m", "RateLimitError", 429, "rl", now),
        ])
        db_path = tmp_path / "llm_errors.db"
        mtime_before = os.stat(db_path).st_mtime
        size_before = os.stat(db_path).st_size
        r = _run_cli(str(tmp_path), "llm-errors", "--window", "7", "--json")
        assert r.returncode == 0, r.stderr
        mtime_after = os.stat(db_path).st_mtime
        size_after = os.stat(db_path).st_size
        assert mtime_before == mtime_after
        assert size_before == size_after

class TestWorldStateError:
    """world-state 錯誤路徑。"""

    def test_multiple_uid_matches_errors(self, tmp_path):
        """部分 UID 匹配到多個用戶時應報錯並列出候選。"""
        users_dir = tmp_path / "users"
        users_dir.mkdir(parents=True)
        (users_dir / "userA").mkdir()
        (users_dir / "userB").mkdir()
        result = _run_cli(str(tmp_path), "world-state", "user")
        assert result.returncode != 0
        assert "userA" in result.stderr
        assert "userB" in result.stderr

class TestWorldDiffError:
    """world-diff 錯誤路徑。"""

    def test_missing_spec_file_errors(self, tmp_path):
        """spec 檔案不存在時應報錯。"""
        uid = "user1"
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        now = _now_iso()
        (tmp_path / "users.json").write_text(
            json.dumps({uid: {"config": {}}, "_email_index": {}}, ensure_ascii=False)
        )
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

        result = _run_cli(str(tmp_path), "world-diff", uid, "/nonexistent/spec.json")
        assert result.returncode != 0

class TestAnalyze:
    """analyze 子指令 — ops_cli 透過 subprocess 呼叫 ops_analyze.py。"""

    def _setup(self, tmp_path, uid="user1"):
        user_dir = tmp_path / "users" / uid
        user_dir.mkdir(parents=True)
        now = _now_iso()
        (tmp_path / "users.json").write_text(
            json.dumps({uid: {"config": {}}, "_email_index": {}}, ensure_ascii=False)
        )
        conn = sqlite3.connect(str(user_dir / "cards.db"))
        conn.execute(
            "CREATE TABLE card (id TEXT PRIMARY KEY, content TEXT, meaning TEXT, is_deleted INTEGER DEFAULT 0)"
        )
        conn.execute("INSERT INTO card VALUES ('c1', 'hello', '你好', 0)")
        conn.commit()
        conn.close()
        (user_dir / "graph_default.json").write_text("[]")
        _create_token_usage_db(tmp_path, [(uid, "translate", 1_000_000, 1_000_000, now)])
        return uid

    def test_level_1_happy_path(self, tmp_path):
        """analyze level 1 透過 ops_cli 正常輸出。"""
        uid = self._setup(tmp_path)
        result = _run_cli(str(tmp_path), "analyze", uid, "1")
        assert result.returncode == 0, result.stderr
        assert "Level 1" in result.stdout
        assert uid in result.stdout

    def test_missing_user_error(self, tmp_path):
        """用戶不存在時 ops_analyze.py 應回傳非零 exit code。"""
        result = _run_cli(str(tmp_path), "analyze", "ghost", "1")
        assert result.returncode != 0

class TestSyncTraceError:
    """sync-trace 錯誤路徑。"""

    def test_multiple_uid_matches_errors(self, tmp_path):
        """部分 UID 匹配到多個用戶時應報錯並列出候選。"""
        users_dir = tmp_path / "users"
        users_dir.mkdir(parents=True)
        (users_dir / "uAlice").mkdir()
        (users_dir / "uAlan").mkdir()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        result = _run_cli(str(tmp_path), "sync-trace", "uA", "--date", today)
        assert result.returncode != 0
        assert "uAlice" in result.stderr or "uAlan" in result.stderr

class TestHelp:
    """--help 應正常輸出。"""

    def test_help(self, tmp_path):
        result = _run_cli(str(tmp_path), "--help")
        assert result.returncode == 0
        assert "user-quota" in result.stdout
