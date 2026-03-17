"""Notebook storage and CRUD operations."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import OperationalError
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select

logger = logging.getLogger(__name__)

DEFAULT_NOTEBOOK_ID = "default"
DEFAULT_NOTEBOOK_NAME = "我的單字本"


class Notebook(SQLModel, table=True):
    """A vocabulary notebook for grouping cards."""

    id: str = SQLField(default_factory=lambda: uuid.uuid4().hex[:12], primary_key=True)
    name: str
    color: str | None = None
    sort_order: int = SQLField(default=0)
    is_default: bool = SQLField(default=False)
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    is_deleted: bool = SQLField(default=False)


class NotebookStore:
    """SQLite-based notebook storage."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_url = f"sqlite:///{self.path.absolute()}"
        self.engine = create_engine(sqlite_url)
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
            conn.exec_driver_sql("PRAGMA busy_timeout=30000;")
        SQLModel.metadata.create_all(self.engine, checkfirst=True)

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

    def create(self, name: str, color: str | None = None) -> Notebook:
        nb = Notebook(name=name, color=color)
        with Session(self.engine) as session:
            session.add(nb)
            session.commit()
            session.refresh(nb)
        return nb

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

    def delete(self, notebook_id: str) -> bool:
        """Soft-delete a notebook. Cannot delete the default notebook."""
        with Session(self.engine) as session:
            nb = session.get(Notebook, notebook_id)
            if nb is None or nb.is_deleted or nb.is_default:
                return False
            nb.is_deleted = True
            nb.updated_at = datetime.now(UTC)
            session.add(nb)
            session.commit()
            return True
