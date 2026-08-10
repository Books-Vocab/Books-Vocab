"""Shared lifecycle for the process-local SQLite log connections."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from threading import RLock

from .sqlite_utils import open_singleton

SchemaInitializer = Callable[[sqlite3.Connection], None]


class SQLiteLifecycle:
    """Own one lazily opened connection and its current database path."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._conn: sqlite3.Connection | None = None
        self._path: Path | None = None

    @property
    def lock(self) -> RLock:
        return self._lock

    @property
    def connection(self) -> sqlite3.Connection | None:
        return self._conn

    def get_connection(
        self, db_path: Path | str, initialize: SchemaInitializer
    ) -> sqlite3.Connection:
        path = Path(db_path).absolute()
        with self._lock:
            if self._conn is not None and self._path != path:
                self._close_unlocked()
            if self._conn is None:
                conn = open_singleton(path)
                try:
                    initialize(conn)
                    conn.commit()
                except BaseException:
                    conn.close()
                    raise
                self._conn = conn
                self._path = path
            return self._conn

    def reset(self) -> None:
        with self._lock:
            self._close_unlocked()

    close = reset

    def _close_unlocked(self) -> None:
        if self._conn is not None:
            self._conn.close()
        self._conn = None
        self._path = None
