"""Readonly observability for the pure dictionary lookup integration."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from ops_helpers import run_ops_cli as _run_cli


def _iso(**delta) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).isoformat()


def _seed_lexical_cache(data_dir: Path) -> None:
    from kg.lexical import LexicalCache

    path = data_dir / "lexical_cache.db"
    LexicalCache(path)
    with closing(sqlite3.connect(path)) as conn, conn:
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
                ("free_dictionary", "search", "miss", 7, _iso(days=3)),
            ],
        )


def test_dictionary_health_reports_lookup_plane_only(tmp_path):
    _seed_lexical_cache(tmp_path)
    result = _run_cli(str(tmp_path), "dictionary-health", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["cache"]["entries"] == 3
    assert payload["cache"]["positive"] == 2
    assert payload["cache"]["negative"] == 1
    assert payload["provider_budget"]["requests_last_hour"]["free_dictionary"] == 4
    assert payload["lookups"]["total"] == 7
    assert payload["lookups"]["admitted"] == 6
    assert payload["lookups"]["cache_hit_rate"] == round(2 / 6, 4)
    assert payload["lookups"]["failure_rate"] == round(3 / 6, 4)
    assert payload["lookups"]["latency_ms"]["max"] == 900


def test_dictionary_health_handles_missing_cache_and_removed_card_command(tmp_path):
    missing = _run_cli(str(tmp_path), "dictionary-health", "--json")
    assert missing.returncode == 0, missing.stderr
    assert json.loads(missing.stdout)["exists"] is False

    removed = _run_cli(str(tmp_path), "dictionary-cards", "--json")
    assert removed.returncode != 0
    assert "invalid choice" in removed.stderr


def test_dictionary_health_filters_lookup_events_by_utc_instant(tmp_path):
    from kg.lexical import LexicalCache

    path = tmp_path / "lexical_cache.db"
    LexicalCache(path)
    now = datetime.now(UTC).replace(microsecond=0)
    cutoff = now - timedelta(hours=24)
    before_cutoff = (cutoff - timedelta(minutes=30)).astimezone(
        timezone(timedelta(hours=1))
    )
    after_cutoff = cutoff + timedelta(minutes=30)

    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executemany(
            "INSERT INTO lexical_lookup_event("
            "provider, operation, outcome, duration_ms, created_at"
            ") VALUES (?, ?, ?, ?, ?)",
            [
                ("free_dictionary", "search", "fresh", 5, before_cutoff.isoformat()),
                ("free_dictionary", "search", "miss", 7, after_cutoff.isoformat()),
            ],
        )

    result = _run_cli(str(tmp_path), "dictionary-health", "--window", "24", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["lookups"]["total"] == 1
    assert payload["lookups"]["by_outcome"] == {"miss": 1}
