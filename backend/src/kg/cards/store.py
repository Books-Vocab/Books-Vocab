"""SQLite-backed :class:`CardStore` — engine lifecycle plus read/write mixins."""

from __future__ import annotations

import logging
from pathlib import Path

from ..sqlite_utils import make_sqlite_engine
from .model import Card
from .dictionary_store import DictionaryCardStoreMixin
from .mutations import CardMutationMixin
from .query import CardQueryMixin
from .schema import init_schema

logger = logging.getLogger(__name__)


class CardStore(CardQueryMixin, CardMutationMixin, DictionaryCardStoreMixin):
    """SQLite-based card storage using SQLModel."""

    def __init__(self, path: Path) -> None:
        self.path = path
        # make_sqlite_engine installs a connect listener that applies
        # WAL/synchronous=NORMAL/busy_timeout to every pooled connection (and
        # creates the parent dir). DDL below runs after, so the schema is
        # created on a WAL connection.
        self.engine = make_sqlite_engine(path)
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
