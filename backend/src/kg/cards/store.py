"""SQLite-backed :class:`CardStore` — engine lifecycle plus read/write mixins."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import create_engine

from .model import Card
from .mutations import CardMutationMixin
from .query import CardQueryMixin
from .schema import init_schema

logger = logging.getLogger(__name__)


class CardStore(CardQueryMixin, CardMutationMixin):
    """SQLite-based card storage using SQLModel."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Use sqlite URI format
        sqlite_url = f"sqlite:///{self.path.absolute()}"
        self.engine = create_engine(sqlite_url)
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
            conn.exec_driver_sql("PRAGMA busy_timeout=30000;")
        init_schema(self.engine)

    def save(self) -> None:
        """No-op for SQLite. Changes are committed immediately or via explicit sessions."""
        pass

    def close(self) -> None:
        """Dispose the SQLAlchemy engine and release connections."""
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None


__all__ = ["Card", "CardStore"]
