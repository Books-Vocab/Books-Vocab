"""Card storage and CRUD operations."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import JSON, Column
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select

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
    pronunciation: str | None = None  # IPA phonetic transcription
    root_form: str | None = None  # lemma (e.g. "laid" → "lay")
    inflections: list[str] = SQLField(default_factory=list, sa_column=Column(JSON))  # all inflected forms from dictionary
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
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
        SQLModel.metadata.create_all(self.engine, checkfirst=True)
        self._migrate_review_columns()

    def _migrate_review_columns(self) -> None:
        """Add review state columns to existing card tables (SQLModel create_all won't ALTER)."""
        review_columns = {
            "pronunciation": "TEXT",
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
                    except Exception:
                        pass
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
        pronunciation: str | None = None,
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
            pronunciation=pronunciation,
        )
        with Session(self.engine) as session:
            session.add(card)
            session.commit()
            session.refresh(card)
        return card

    def get(self, card_id: str) -> Card | None:
        with Session(self.engine) as session:
            return session.get(Card, card_id)

    def all(self, include_deleted: bool = False) -> Iterator[Card]:
        with Session(self.engine) as session:
            statement = select(Card)
            if not include_deleted:
                statement = statement.where(Card.is_deleted.is_(False))
            results = session.exec(statement).all()
            yield from results

    def get_modified_since(self, since: datetime) -> list[Card]:
        """Fetch all cards (including soft-deleted) modified after the given timestamp."""
        with Session(self.engine) as session:
            statement = select(Card).where(Card.updated_at > since)
            return list(session.exec(statement).all())

    def count(self) -> int:
        from sqlalchemy import func
        with Session(self.engine) as session:
            return session.scalar(
                select(func.count()).select_from(Card).where(Card.is_deleted.is_(False))
            ) or 0

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
