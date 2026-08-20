"""Persistent cache and provider-budget/telemetry storage."""

from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from .lexical_models import LexicalEntry

logger = logging.getLogger(__name__)
LOOKUP_EVENT_RETENTION_DAYS = 14


class CachedLexicalValue(BaseModel):
    entry: LexicalEntry | None
    fresh: bool


class LexicalCache:
    def __init__(
        self,
        path: Path,
        *,
        positive_ttl: timedelta = timedelta(days=30),
        negative_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self.path = path
        self.positive_ttl = positive_ttl
        self.negative_ttl = negative_ttl
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS lexical_cache (
                    cache_key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    entry_key TEXT,
                    payload_json TEXT,
                    is_negative INTEGER NOT NULL DEFAULT 0,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_lexical_cache_entry_key "
                "ON lexical_cache(provider, entry_key)"
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS lexical_provider_request (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    requested_at REAL NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_lexical_provider_request_window "
                "ON lexical_provider_request(provider, requested_at)"
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS lexical_lookup_event (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_lexical_lookup_event_created_at "
                "ON lexical_lookup_event(created_at)"
            )

    @staticmethod
    def query_key(provider: str, query: str, source_language: str, target_language: str) -> str:
        return "|".join((provider, source_language.lower(), target_language.lower(), query.strip().casefold()))

    def get_query(
        self, provider: str, query: str, source_language: str, target_language: str
    ) -> CachedLexicalValue | None:
        return self._get(self.query_key(provider, query, source_language, target_language))

    def get_entry(self, provider: str, entry_key: str) -> CachedLexicalValue | None:
        with closing(sqlite3.connect(self.path)) as conn, conn:
            row = conn.execute(
                "SELECT payload_json, is_negative, expires_at FROM lexical_cache "
                "WHERE provider = ? AND entry_key = ? ORDER BY fetched_at DESC LIMIT 1",
                (provider, entry_key),
            ).fetchone()
        return self._row_value(row)

    def _get(self, cache_key: str) -> CachedLexicalValue | None:
        with closing(sqlite3.connect(self.path)) as conn, conn:
            row = conn.execute(
                "SELECT payload_json, is_negative, expires_at FROM lexical_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return self._row_value(row)

    @staticmethod
    def _row_value(row: tuple | None) -> CachedLexicalValue | None:
        if row is None:
            return None
        payload_json, is_negative, expires_at = row
        expires = datetime.fromisoformat(expires_at)
        now = datetime.now(UTC)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        entry = None if is_negative else LexicalEntry.model_validate_json(payload_json)
        return CachedLexicalValue(entry=entry, fresh=expires > now)

    def put(
        self,
        provider: str,
        query: str,
        source_language: str,
        target_language: str,
        entry: LexicalEntry | None,
    ) -> None:
        now = datetime.now(UTC)
        expires = now + (self.positive_ttl if entry is not None else self.negative_ttl)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                """INSERT INTO lexical_cache(
                       cache_key, provider, entry_key, payload_json, is_negative, fetched_at, expires_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(cache_key) DO UPDATE SET
                       entry_key=excluded.entry_key, payload_json=excluded.payload_json,
                       is_negative=excluded.is_negative, fetched_at=excluded.fetched_at,
                       expires_at=excluded.expires_at""",
                (
                    self.query_key(provider, query, source_language, target_language),
                    provider,
                    entry.entry_key if entry else None,
                    entry.model_dump_json() if entry else None,
                    int(entry is None),
                    now.isoformat(),
                    expires.isoformat(),
                ),
            )

    def record_lookup(
        self, provider: str, operation: str, outcome: str, duration_ms: int
    ) -> None:
        """Append one lookup outcome for ops. Best effort — never fails a lookup.

        Observability that can break the thing it observes is worse than none,
        so every SQLite failure here is swallowed after logging. Rows older than
        ``LOOKUP_EVENT_RETENTION_DAYS`` are pruned on write; the provider budget
        caps insert volume at ~1k/hour, so the indexed delete stays cheap.
        """
        now = datetime.now(UTC)
        cutoff = (now - timedelta(days=LOOKUP_EVENT_RETENTION_DAYS)).isoformat()
        try:
            with closing(sqlite3.connect(self.path, timeout=5.0)) as conn, conn:
                conn.execute(
                    "INSERT INTO lexical_lookup_event("
                    "provider, operation, outcome, duration_ms, created_at"
                    ") VALUES (?, ?, ?, ?, ?)",
                    (provider, operation, outcome, int(duration_ms), now.isoformat()),
                )
                conn.execute(
                    "DELETE FROM lexical_lookup_event "
                    "WHERE datetime(created_at) < datetime(?)",
                    (cutoff,),
                )
        except sqlite3.Error:
            logger.warning("Dictionary lookup telemetry write failed", exc_info=True)

    def reserve_provider_request(self, provider: str, *, hourly_limit: int) -> bool:
        """Atomically reserve one upstream call across workers sharing this cache."""
        now = time.time()
        window_start = now - 3600.0
        with closing(
            sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        ) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM lexical_provider_request WHERE requested_at <= ?",
                (window_start,),
            )
            request_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM lexical_provider_request "
                    "WHERE provider = ? AND requested_at > ?",
                    (provider, window_start),
                ).fetchone()[0]
            )
            if request_count >= hourly_limit:
                conn.rollback()
                return False
            conn.execute(
                "INSERT INTO lexical_provider_request(provider, requested_at) VALUES (?, ?)",
                (provider, now),
            )
            conn.commit()
        return True
