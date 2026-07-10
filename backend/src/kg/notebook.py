"""Notebook storage and CRUD operations."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, select

from .sqlite_utils import make_sqlite_engine

logger = logging.getLogger(__name__)

DEFAULT_NOTEBOOK_ID = "default"
DEFAULT_NOTEBOOK_NAME = "我的單字本"


class Notebook(SQLModel, table=True):
    """A vocabulary notebook for grouping cards."""

    id: str = SQLField(default_factory=lambda: uuid.uuid4().hex[:12], primary_key=True)
    name: str
    color: str | None = None
    cover_pattern: str | None = None
    sort_order: int = SQLField(default=0)
    is_default: bool = SQLField(default=False)
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    is_deleted: bool = SQLField(default=False)
    # Provenance (v1 inert): set when this notebook was copied from a shared
    # deck (Phase 2 copy). NULL for organically-created notebooks.
    source_shared_deck_id: str | None = None
    source_version: int | None = None


class NotebookStore:
    """SQLite-based notebook storage."""

    def __init__(self, path: Path) -> None:
        self.path = path
        # make_sqlite_engine installs a connect listener that applies
        # WAL/synchronous=NORMAL/busy_timeout to every pooled connection (and
        # creates the parent dir). create_all + column migration below run
        # after, so DDL lands on a WAL connection.
        self.engine = make_sqlite_engine(path)
        Notebook.metadata.create_all(self.engine, tables=[Notebook.__table__], checkfirst=True)
        self._migrate_columns()

    def _migrate_columns(self) -> None:
        # SQLModel create_all won't ALTER existing tables → add-if-missing.
        added_cols = {
            "cover_pattern": "TEXT",
            "source_shared_deck_id": "TEXT",
            "source_version": "INTEGER",
        }
        with self.engine.connect() as conn:
            existing = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(notebook)").fetchall()}
            changed = False
            for col, decl in added_cols.items():
                if col not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE notebook ADD COLUMN {col} {decl}")
                    logger.info("migrated notebook: added %s column", col)
                    changed = True
            if changed:
                conn.commit()

    def ensure_default(self) -> Notebook:
        """Ensure the default notebook exists. Returns it."""
        with Session(self.engine) as session:
            existing = session.exec(
                select(Notebook).where(Notebook.id == DEFAULT_NOTEBOOK_ID)
            ).first()
            if existing:
                return existing
            nb = Notebook(
                id=DEFAULT_NOTEBOOK_ID,
                name=DEFAULT_NOTEBOOK_NAME,
                is_default=True,
            )
            session.add(nb)
            session.commit()
            session.refresh(nb)
            return nb

    def create(
        self,
        name: str,
        color: str | None = None,
        cover_pattern: str | None = None,
        *,
        source_shared_deck_id: str | None = None,
        source_version: int | None = None,
        is_deleted: bool = False,
    ) -> Notebook:
        """Create a notebook. ``is_default`` is never set here (the model default
        is False), so a shared-deck copy is structurally guaranteed non-default.
        The Phase 2 copy path passes ``is_deleted=True`` to stage the notebook
        HIDDEN (the materialization barrier) plus the provenance columns, then
        reveals it via :meth:`materialize` once every card has landed."""
        nb = Notebook(
            name=name, color=color, cover_pattern=cover_pattern,
            source_shared_deck_id=source_shared_deck_id,
            source_version=source_version, is_deleted=is_deleted,
        )
        with Session(self.engine) as session:
            session.add(nb)
            session.commit()
            session.refresh(nb)
        return nb

    def materialize(self, notebook_id: str) -> bool:
        """Lift the copy barrier: flip a staged (``is_deleted=True``) copy
        notebook visible. Idempotent — a no-op (no write, no ``updated_at`` bump)
        when the notebook is already visible or absent, so a defensive
        re-materialize on an idempotent-retry replay causes no sync churn.
        Returns True only when a hidden row was actually revealed."""
        with Session(self.engine) as session:
            nb = session.get(Notebook, notebook_id)
            if nb is None or not nb.is_deleted:
                return False
            nb.is_deleted = False
            nb.updated_at = datetime.now(UTC)
            session.add(nb)
            session.commit()
            return True

    def hard_delete(self, notebook_id: str) -> bool:
        """Physically remove a notebook row. Compensation-only — ordinary
        deletes are soft (:meth:`delete`); this exists so a failed copy leaves no
        trace. Returns True if a row was deleted."""
        with Session(self.engine) as session:
            nb = session.get(Notebook, notebook_id)
            if nb is None:
                return False
            session.delete(nb)
            session.commit()
            return True

    def get(self, notebook_id: str) -> Notebook | None:
        with Session(self.engine) as session:
            return session.get(Notebook, notebook_id)

    def all(self, include_deleted: bool = False) -> list[Notebook]:
        with Session(self.engine) as session:
            statement = select(Notebook)
            if not include_deleted:
                statement = statement.where(Notebook.is_deleted.is_(False))
            statement = statement.order_by(Notebook.sort_order, Notebook.created_at)
            return list(session.exec(statement).all())

    def get_modified_since(self, since: datetime) -> list[Notebook]:
        """Fetch all notebooks (including soft-deleted) modified after the given timestamp."""
        with Session(self.engine) as session:
            statement = select(Notebook).where(Notebook.updated_at > since)
            return list(session.exec(statement).all())

    def update(self, notebook_id: str, **kwargs) -> Notebook | None:
        with Session(self.engine) as session:
            nb = session.get(Notebook, notebook_id)
            if nb is None or nb.is_deleted:
                return None
            has_changes = False
            for key, value in kwargs.items():
                if hasattr(nb, key) and getattr(nb, key) != value:
                    setattr(nb, key, value)
                    has_changes = True
            if has_changes:
                nb.updated_at = datetime.now(UTC)
                session.add(nb)
                session.commit()
                session.refresh(nb)
            return nb

    def exists(self, notebook_id: str) -> bool:
        """Check if a non-deleted notebook exists."""
        nb = self.get(notebook_id)
        return nb is not None and not nb.is_deleted

    def delete(self, notebook_id: str) -> bool | None:
        """Soft-delete a notebook. Returns True if deleted, None if already
        deleted (idempotent success), False if not found or is default."""
        with Session(self.engine) as session:
            nb = session.get(Notebook, notebook_id)
            if nb is None or nb.is_default:
                return False
            if nb.is_deleted:
                return None
            nb.is_deleted = True
            nb.updated_at = datetime.now(UTC)
            session.add(nb)
            session.commit()
            return True

    def close(self) -> None:
        """Dispose the SQLAlchemy engine and release connections."""
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None


def validate_notebook_access(notebook_store: NotebookStore, notebook_id: str) -> None:
    """Raise 403 if notebook_id does not belong to this user (not found or deleted).

    The 'default' notebook is auto-created on demand, so it always passes.
    """
    if notebook_id == DEFAULT_NOTEBOOK_ID:
        notebook_store.ensure_default()
        return
    if not notebook_store.exists(notebook_id):
        raise HTTPException(status_code=403, detail="Notebook access denied")
