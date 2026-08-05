"""ops_cli dictionary observability — typed,唯讀，不靠手拼 SQL 當 runbook。

用真的 `CardStore` / `LexicalCache` 建 schema（杜絕 fixture 與生產 schema
漂移），再用原始 SQL 把行推到需要的狀態，最後跑 subprocess 驗 CLI 聚合。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ops_helpers import run_ops_cli as _run_cli


def _iso(**delta) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).isoformat()


def _seed_lexical_cache(data_dir: Path) -> Path:
    from kg.lexical import LexicalCache

    path = data_dir / "lexical_cache.db"
    LexicalCache(path)
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO lexical_cache("
            "cache_key, provider, entry_key, payload_json, is_negative, fetched_at, expires_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("k1", "free_dictionary", "en.aQ", "{}", 0, _iso(days=2), _iso(days=-28)),
                ("k2", "free_dictionary", "en.aR", "{}", 0, _iso(days=40), _iso(days=10)),
                ("k3", "free_dictionary", None, None, 1, _iso(hours=1), _iso(hours=-23)),
            ],
        )
        conn.executemany(
            "INSERT INTO lexical_provider_request(provider, requested_at) VALUES (?, ?)",
            [("free_dictionary", datetime.now(UTC).timestamp() - 60) for _ in range(4)],
        )
        conn.executemany(
            "INSERT INTO lexical_lookup_event("
            "provider, operation, outcome, duration_ms, created_at"
            ") VALUES (?, ?, ?, ?, ?)",
            [
                ("free_dictionary", "search", "fresh", 5, _iso(hours=1)),
                ("free_dictionary", "search", "miss", 120, _iso(hours=2)),
                ("free_dictionary", "search", "throttled", 0, _iso(hours=3)),
                ("free_dictionary", "entry", "stale", 900, _iso(hours=4)),
                ("free_dictionary", "entry", "rate_limited", 40, _iso(hours=5)),
                ("free_dictionary", "search", "error", 60, _iso(hours=6)),
                ("free_dictionary", "search", "negative_cached", 3, _iso(hours=7)),
                # Outside a 24h window — must not be counted.
                ("free_dictionary", "search", "miss", 7, _iso(days=3)),
            ],
        )
    return path


def _seed_user_cards(data_dir: Path, uid: str) -> Path:
    from kg.cards import CardStore

    user_dir = data_dir / "users" / uid
    user_dir.mkdir(parents=True)
    path = user_dir / "cards.db"
    store = CardStore(path)
    learning = store.add("summon", "召喚", notebook_id="default")
    active_dict = store.add("invoke", "援引", notebook_id="default")
    archived_dict = store.add("evoke", "喚起", notebook_id="default")
    staged_dict = store.add("revoke", "撤銷", notebook_id="default")
    failed_dict = store.add("provoke", "挑起", notebook_id="default")
    store.close()

    with sqlite3.connect(path) as conn:
        for card_id, archived, deleted, hidden, promotion in (
            (active_dict.id, 0, 0, 0, "idle"),
            (archived_dict.id, 1, 0, 1, "idle"),
            (staged_dict.id, 0, 0, 0, "idle"),
            (failed_dict.id, 0, 0, 0, "failed"),
        ):
            conn.execute(
                "UPDATE card SET card_role='dictionary', review_eligible=0, "
                "is_archived=?, is_deleted=?, reader_hidden=?, promotion_state=? "
                "WHERE id=?",
                (archived, deleted, hidden, promotion, card_id),
            )
        for card_id, status in (
            (active_dict.id, "active"),
            (archived_dict.id, "active"),
            (staged_dict.id, "staged"),
            (failed_dict.id, "active"),
        ):
            conn.execute(
                "INSERT INTO dictionary_entry("
                "card_id, provider, dictionary_id, provider_entry_key, "
                "provider_schema_version, selected_sense_key, selected_example_key, "
                "payload_json, source_url, license_name, license_url, "
                "attribution_text, fetched_at, materialization_status"
                ") VALUES (?, 'free_dictionary', 'wiktionary-en', 'en.aQ', 'v1', "
                "'sense_1', 'example_1', '{}', 'u', 'CC BY-SA 4.0', 'u', 'a', ?, ?)",
                (card_id, _iso(days=1), status),
            )
        conn.executemany(
            "INSERT INTO lexical_operations("
            "idempotency_key, request_hash, status, card_id, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("op-done", "h1", "completed", active_dict.id, _iso(days=1), _iso(days=1)),
                ("op-staged", "h2", "card_staged", staged_dict.id, _iso(hours=2), _iso(hours=2)),
                ("op-judged", "h3", "judged", None, _iso(hours=1), _iso(hours=1)),
            ],
        )
        conn.executemany(
            "INSERT INTO dictionary_promotion_jobs("
            "card_id, status, attempt_count, error_code, retryable, worker_id, "
            "queued_at, started_at, finished_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    failed_dict.id, "failed", 2, "enrich_failed", 1, "w1",
                    _iso(hours=3), _iso(hours=3), _iso(hours=2), _iso(hours=2),
                ),
                (
                    active_dict.id, "succeeded", 1, None, None, "w1",
                    _iso(days=1), _iso(days=1), _iso(days=1), _iso(days=1),
                ),
            ],
        )
        conn.execute(
            "INSERT INTO dictionary_lifecycle_state("
            "card_id, notebook_id, pending_action, graph_snapshot_json, "
            "pending_link_ids_json, pending_cause_link_ids_json, "
            "card_before_archived, card_before_deleted, updated_at"
            ") VALUES (?, 'default', 'delete', '{}', '[]', '[]', 0, 0, ?)",
            (archived_dict.id, _iso(hours=1)),
        )
    return learning.id and path


class TestDictionaryHealth:
    def test_reports_cache_provider_budget_and_lookup_outcomes(self, tmp_path):
        _seed_lexical_cache(tmp_path)
        result = _run_cli(str(tmp_path), "dictionary-health", "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)

        assert payload["exists"] is True
        assert payload["window_hours"] == 24
        assert payload["cache"]["entries"] == 3
        assert payload["cache"]["positive"] == 2
        assert payload["cache"]["negative"] == 1
        assert payload["cache"]["fresh"] == 2
        assert payload["cache"]["expired"] == 1

        assert payload["provider_budget"]["hourly_limit"] == 950
        assert payload["provider_budget"]["requests_last_hour"]["free_dictionary"] == 4
        assert payload["provider_budget"]["headroom"]["free_dictionary"] == 946

        lookups = payload["lookups"]
        assert lookups["total"] == 7, "the 3-day-old row is outside the window"
        assert lookups["by_outcome"] == {
            "fresh": 1,
            "miss": 1,
            "throttled": 1,
            "stale": 1,
            "rate_limited": 1,
            "error": 1,
            "negative_cached": 1,
        }
        assert lookups["by_operation"] == {"search": 5, "entry": 2}
        assert lookups["latency_ms"]["max"] == 900
        # Throttled never reached the lookup, so it is in neither rate.
        assert lookups["admitted"] == 6
        # fresh + negative_cached — both served without a provider call.
        assert lookups["cache_hit_rate"] == round(2 / 6, 4)
        # stale + rate_limited + error — stale counts because it is a provider
        # failure the user simply did not see.
        assert lookups["failure_rate"] == round(3 / 6, 4)

    def test_window_flag_narrows_the_lookup_ledger(self, tmp_path):
        _seed_lexical_cache(tmp_path)
        result = _run_cli(str(tmp_path), "dictionary-health", "--window", "3", "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["window_hours"] == 3
        assert payload["lookups"]["total"] == 2
        assert payload["lookups"]["by_outcome"] == {"fresh": 1, "miss": 1}

    def test_missing_cache_db_is_reported_not_crashed(self, tmp_path):
        result = _run_cli(str(tmp_path), "dictionary-health", "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["exists"] is False
        assert payload["lookups"]["total"] == 0

    def test_human_output_names_every_section(self, tmp_path):
        _seed_lexical_cache(tmp_path)
        result = _run_cli(str(tmp_path), "dictionary-health")
        assert result.returncode == 0, result.stderr
        for section in ("Cache", "Provider budget", "Lookups"):
            assert section in result.stdout


class TestDictionaryCards:
    def test_counts_cards_staged_operations_and_promotion_failures(self, tmp_path):
        _seed_user_cards(tmp_path, "u_alpha")
        result = _run_cli(str(tmp_path), "dictionary-cards", "u_alpha", "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)

        user = payload["users"][0]
        assert user["user_id"] == "u_alpha"
        assert user["cards"] == {
            "total": 4,
            "active": 3,
            "archived": 1,
            "deleted": 0,
            "reader_hidden": 1,
        }
        assert user["promotion_state"] == {"idle": 3, "failed": 1}
        assert user["sidecars"] == {"active": 3, "staged": 1}
        assert user["operations"] == {"completed": 1, "card_staged": 1, "judged": 1}
        assert user["operations_in_flight"] == 2
        assert user["lifecycle_pending"] == {"delete": 1}
        assert user["promotion_jobs"] == {"failed": 1, "succeeded": 1}
        assert user["promotion_failures"] == [
            {
                "card_id": user["promotion_failures"][0]["card_id"],
                "error_code": "enrich_failed",
                "retryable": True,
                "attempt_count": 2,
            }
        ]

    def test_all_users_is_the_default_and_totals_are_summed(self, tmp_path):
        _seed_user_cards(tmp_path, "u_alpha")
        _seed_user_cards(tmp_path, "u_beta")
        result = _run_cli(str(tmp_path), "dictionary-cards", "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["uid"] == "all"
        assert [u["user_id"] for u in payload["users"]] == ["u_alpha", "u_beta"]
        assert payload["totals"]["cards"] == 8
        assert payload["totals"]["operations_in_flight"] == 4
        assert payload["totals"]["promotion_failures"] == 2
        assert payload["totals"]["staged_sidecars"] == 2

    def test_user_without_cards_db_is_skipped_not_fatal(self, tmp_path):
        (tmp_path / "users" / "u_empty").mkdir(parents=True)
        _seed_user_cards(tmp_path, "u_alpha")
        result = _run_cli(str(tmp_path), "dictionary-cards", "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert [u["user_id"] for u in payload["users"]] == ["u_alpha"]

    def test_legacy_db_without_dictionary_tables_reports_zeroes(self, tmp_path):
        user_dir = tmp_path / "users" / "u_legacy"
        user_dir.mkdir(parents=True)
        with sqlite3.connect(user_dir / "cards.db") as conn:
            conn.execute(
                "CREATE TABLE card (id TEXT PRIMARY KEY, content TEXT, "
                "is_deleted INTEGER DEFAULT 0)"
            )
        result = _run_cli(str(tmp_path), "dictionary-cards", "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["users"][0]["cards"]["total"] == 0
        assert payload["users"][0]["promotion_jobs"] == {}

    def test_human_output_names_every_section(self, tmp_path):
        _seed_user_cards(tmp_path, "u_alpha")
        result = _run_cli(str(tmp_path), "dictionary-cards", "u_alpha")
        assert result.returncode == 0, result.stderr
        for section in ("Cards", "Operations", "Promotion"):
            assert section in result.stdout


def test_both_subcommands_are_documented_in_help(tmp_path):
    result = _run_cli(str(tmp_path), "--help")
    assert result.returncode == 0, result.stderr
    assert "dictionary-health" in result.stdout
    assert "dictionary-cards" in result.stdout


def test_dictionary_health_is_readonly(tmp_path):
    """唯讀契約：跑完之後 cache DB 的 mtime 與內容都不能動。"""
    path = _seed_lexical_cache(tmp_path)
    before = (path.stat().st_mtime_ns, path.read_bytes())
    assert _run_cli(str(tmp_path), "dictionary-health", "--json").returncode == 0
    assert (path.stat().st_mtime_ns, path.read_bytes()) == before
