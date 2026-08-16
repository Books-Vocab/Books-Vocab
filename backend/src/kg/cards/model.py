"""Card SQLModel definition and related type aliases."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import JSON, Column
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

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
    source: str | None = SQLField(default=None)  # JSON string
    # NFC-normalized lowercased content for fast indexed case/Unicode-insensitive lookup.
    # Populated on add/update; backfilled on schema migration.
    content_nfc_lower: str = SQLField(default="", index=True)

    # Spaced-review state (synced from client)
    review_interval_hours: float = SQLField(default=12.0)
    next_review_at: datetime | None = SQLField(default=None)
    last_reviewed_at: datetime | None = SQLField(default=None)
    review_count: int = SQLField(default=0)
    lapse_count: int = SQLField(default=0)
    review_streak: int = SQLField(default=0)
    last_review_feedback: int = SQLField(default=-1)  # -1=none, 0=forgot, 1=remembered

    # Provenance (v1 inert): content_guid of the shared_deck_card this card was
    # copied from (Phase 2 copy stamps it). NULL for organically-created cards.
    source_shared_card_guid: str | None = SQLField(default=None)

    def embed_text(self) -> str:
        """Text used for embedding."""
        return f"{self.content}: {self.meaning}"
