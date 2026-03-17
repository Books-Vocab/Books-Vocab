"""Card storage and CRUD operations."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import JSON, Column
from sqlalchemy.exc import OperationalError
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select

logger = logging.getLogger(__name__)

CardMode = Literal["recognition", "production"]


class Card(SQLModel, table=True):
    """A vocabulary card."""

    id: str = SQLField(default_factory=lambda: uuid.uuid4().hex[:12], primary_key=True)
    content: str  # word or phrase
    pos: str | None = None  # part of speech [v.] [n.] [adj.]
    meaning: str  # canonical definition
    examples: list[str] = SQLField(default_factory=list, sa_column=Column(JSON))
    collocations: list[str] = SQLField(default_factory=list, sa_column=Column(JSON))  # common collocations
    note: str | None = None  # LLM-generated teacher note (markdown)
    difficulty: float | None = None  # Zipf frequency score (higher = more common)
    mode: str = "recognition"  # recognition: 英→中, production: 中→英
    root_form: str | None = None  # lemma (e.g. "laid" → "lay")
    inflections: list[str] = SQLField(default_factory=list, sa_column=Column(JSON))  # all inflected forms from dictionary
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    notebook_id: str = SQLField(default="default")
    is_deleted: bool = SQLField(default=False)
    is_archived: bool = SQLField(default=False)

    # Spaced-review state (synced from client)
    review_interval_hours: float = SQLField(default=12.0)
    next_review_at: datetime | None = SQLField(default=None)
    last_reviewed_at: datetime | None = SQLField(default=None)
    review_count: int = SQLField(default=0)
    lapse_count: int = SQLField(default=0)
    review_streak: int = SQLField(default=0)
    last_review_feedback: int = SQLField(default=-1)  # -1=none, 0=forgot, 1=remembered

    def embed_text(self) -> str:
        """Text used for embedding."""
        return f"{self.content}: {self.meaning}"


class CardStore:
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
        Card.metadata.create_all(self.engine, tables=[Card.__table__], checkfirst=True)
        self._migrate_review_columns()
        with self.engine.connect() as conn:
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_card_updated_at ON card (updated_at)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_card_content ON card (content)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_card_content_nocase ON card (content COLLATE NOCASE)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_card_notebook_id ON card (notebook_id)"
            )
            conn.commit()

    def _migrate_review_columns(self) -> None:
        """Add review state columns to existing card tables (SQLModel create_all won't ALTER)."""
        review_columns = {
            "notebook_id": "TEXT DEFAULT 'default'",
            "is_archived": "INTEGER DEFAULT 0",
            "review_interval_hours": "REAL DEFAULT 12.0",
            "next_review_at": "TIMESTAMP",
            "last_reviewed_at": "TIMESTAMP",
            "review_count": "INTEGER DEFAULT 0",
            "lapse_count": "INTEGER DEFAULT 0",
            "review_streak": "INTEGER DEFAULT 0",
            "last_review_feedback": "INTEGER DEFAULT -1",
        }
        with self.engine.connect() as conn:
            result = conn.exec_driver_sql("PRAGMA table_info(card)")
            existing = {row[1] for row in result}
            for col_name, col_type in review_columns.items():
                if col_name not in existing:
                    try:
                        conn.exec_driver_sql(f"ALTER TABLE card ADD COLUMN {col_name} {col_type}")
                    except OperationalError as exc:
                        if "duplicate column" in str(exc).lower():
                            pass  # column already added by concurrent process
                        else:
                            logger.error("Migration failed for column %s: %s", col_name, exc)
                            raise
            conn.commit()

    def add(
        self,
        content: str,
        meaning: str,
        pos: str | None = None,
        examples: list[str] | None = None,
        collocations: list[str] | None = None,
        mode: str = "recognition",
        root_form: str | None = None,
        inflections: list[str] | None = None,
        notebook_id: str = "default",
    ) -> Card:
        """Create and store a new card."""
        card = Card(
            content=content,
            meaning=meaning,
            pos=pos,
            examples=examples or [],
            collocations=collocations or [],
            mode=mode,
            root_form=root_form,
            inflections=inflections or [],
            notebook_id=notebook_id,
        )
        with Session(self.engine) as session:
            session.add(card)
            session.commit()
            session.refresh(card)
        return card

    def get(self, card_id: str) -> Card | None:
        with Session(self.engine) as session:
            return session.get(Card, card_id)

    def find_by_content(self, content: str, notebook_id: str | None = None) -> Card | None:
        """Case-insensitive lookup with Unicode NFC normalization.

        1. Exact match (uses ix_card_content index)
        2. Case-insensitive via raw SQL COLLATE NOCASE
        3. Fallback: Python-side NFC normalization for decomposed Unicode

        When notebook_id is given, results are scoped to that notebook.
        """
        import unicodedata
        norm = unicodedata.normalize("NFC", content).strip()
        with Session(self.engine) as session:
            # 1. Exact match — uses index
            stmt = select(Card).where(Card.content == norm, Card.is_deleted.is_(False))
            if notebook_id is not None:
                stmt = stmt.where(Card.notebook_id == notebook_id)
            result = session.exec(stmt).first()
            if result:
                return result
            # 2. Case-insensitive via raw SQL
            conn = session.connection()
            nb_clause = " AND notebook_id = ?" if notebook_id is not None else ""
            params = (norm, notebook_id) if notebook_id is not None else (norm,)
            row = conn.exec_driver_sql(
                f"SELECT id FROM card WHERE content = ? COLLATE NOCASE AND is_deleted = 0{nb_clause} LIMIT 1",
                params,
            ).first()
            if row:
                return session.get(Card, row[0])
            # 3. NFC normalization fallback (handles decomposed Unicode like café)
            fallback_stmt = select(Card).where(Card.is_deleted.is_(False))
            if notebook_id is not None:
                fallback_stmt = fallback_stmt.where(Card.notebook_id == notebook_id)
            norm_lower = norm.lower()
            for card in session.exec(fallback_stmt).all():
                if unicodedata.normalize("NFC", card.content).strip().lower() == norm_lower:
                    return card
            return None

    def all(self, include_deleted: bool = False, notebook_id: str | None = None) -> Iterator[Card]:
        with Session(self.engine) as session:
            statement = select(Card)
            if not include_deleted:
                statement = statement.where(Card.is_deleted.is_(False))
            if notebook_id is not None:
                statement = statement.where(Card.notebook_id == notebook_id)
            results = session.exec(statement).all()
            yield from results

    def all_as_dict(self, include_deleted: bool = False, notebook_id: str | None = None) -> dict[str, "Card"]:
        with Session(self.engine) as session:
            statement = select(Card)
            if not include_deleted:
                statement = statement.where(Card.is_deleted.is_(False))
            if notebook_id is not None:
                statement = statement.where(Card.notebook_id == notebook_id)
            return {card.id: card for card in session.exec(statement).all()}

    def all_limited(self, limit: int = 5000, include_deleted: bool = False, notebook_id: str | None = None) -> list[Card]:
        with Session(self.engine) as session:
            statement = select(Card)
            if not include_deleted:
                statement = statement.where(Card.is_deleted.is_(False))
            if notebook_id is not None:
                statement = statement.where(Card.notebook_id == notebook_id)
            statement = statement.order_by(Card.updated_at.desc()).limit(limit)
            return list(session.exec(statement).all())

    def get_modified_since(self, since: datetime, notebook_id: str | None = None) -> list[Card]:
        """Fetch all cards (including soft-deleted) modified after the given timestamp."""
        with Session(self.engine) as session:
            statement = select(Card).where(Card.updated_at > since)
            if notebook_id is not None:
                statement = statement.where(Card.notebook_id == notebook_id)
            return list(session.exec(statement).all())

    def count(self, notebook_id: str | None = None) -> int:
        from sqlalchemy import func
        with Session(self.engine) as session:
            statement = select(func.count()).select_from(Card).where(Card.is_deleted.is_(False))
            if notebook_id is not None:
                statement = statement.where(Card.notebook_id == notebook_id)
            return session.scalar(statement) or 0

    def count_by_notebook(self) -> dict[str, int]:
        """Single GROUP BY query returning {notebook_id: count}."""
        from sqlalchemy import func
        with Session(self.engine) as session:
            rows = session.exec(
                select(Card.notebook_id, func.count())
                .where(Card.is_deleted.is_(False))
                .group_by(Card.notebook_id)
            ).all()
            return {nb_id: cnt for nb_id, cnt in rows}

    def reassign_notebook(self, from_notebook_id: str, to_notebook_id: str) -> int:
        """Move all non-deleted cards from one notebook to another. Returns count."""
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            cards = session.exec(
                select(Card).where(
                    Card.notebook_id == from_notebook_id,
                    Card.is_deleted.is_(False),
                )
            ).all()
            for card in cards:
                card.notebook_id = to_notebook_id
                card.updated_at = now
                session.add(card)
            session.commit()
            return len(cards)

    def delete(self, card_id: str) -> bool:
        """Soft deletes the card to support incremental sync."""
        with Session(self.engine) as session:
            card = session.get(Card, card_id)
            if card and not card.is_deleted:
                card.is_deleted = True
                card.updated_at = datetime.now(UTC)
                session.add(card)
                session.commit()
                return True
        return False

    def update(self, card_id: str, **kwargs) -> Card | None:
        """Update specific fields of a card. Automatically sets updated_at."""
        with Session(self.engine) as session:
            card = session.get(Card, card_id)
            if card and not card.is_deleted:
                has_changes = False
                for key, value in kwargs.items():
                    if hasattr(card, key) and getattr(card, key) != value:
                        setattr(card, key, value)
                        has_changes = True

                if has_changes:
                    card.updated_at = datetime.now(UTC)
                    session.add(card)
                    session.commit()
                    session.refresh(card)
                return card
        return None

    def save(self) -> None:
        """No-op for SQLite. Changes are committed immediately or via explicit sessions."""
        pass
