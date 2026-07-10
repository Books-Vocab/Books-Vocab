"""SQLite-backed :class:`SharedDeckStore` — the global shared-decks catalog.

Unlike the per-user stores (cards/notebook/library), this store is a **single
global** SQLite file at ``data_dir/shared_decks.db``. A shared deck's owner is
the ``owner_id`` *column* (``NULL`` for official decks), never encoded in the
path — the same cross-user shape as ``translate_log``. It is therefore OUTSIDE
the per-user backup/erasure scope and needs its own hooks (Phase 1b / §3.5).

Six tables (all six ``table=True`` class names are **globally unique** so
SQLModel's shared metadata registry never trips ``InvalidRequestError``, the
failure ``library/store.py`` documents):

* ``shared_deck``        — metadata / index / moderation plane
* ``shared_deck_version``— immutable versioned payload pointer
* ``shared_deck_card``   — **content plane ONLY** (structurally zero SRS columns)
* ``shared_deck_rating`` — one-vote-per-user authority (Phase 3 write path)
* ``shared_deck_report`` — reactive moderation (Phase 3 write path)
* ``shared_deck_copy_log``— copy idempotency + rating-eligibility gate

The rating/report/copy_log tables carry their forward-compat columns from
day one so opening the community-UGC write path later needs no migration.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from ..sqlite_utils import make_sqlite_engine


def _mint_deck_id() -> str:
    """Server-minted deck id matching ``^[A-Za-z0-9_-]{1,64}$`` (= deep-link
    identifier). ``token_urlsafe`` yields exactly that alphabet."""
    return secrets.token_urlsafe(12)


class SharedDeck(SQLModel, table=True):
    """Metadata / index / moderation plane for a shared deck.

    Three orthogonal deletion axes (never overwrite each other):
    ``visibility`` (exposure) × ``status`` (moderation) × ``is_deleted``
    (existence). Browse discovery hard-filters ``is_deleted=0 AND
    status='active' AND visibility='public'``.
    """

    __tablename__ = "shared_deck"
    __table_args__ = (
        # Republish idempotency: an (owner, source notebook) pair upserts in
        # place. NULLs are distinct in SQLite UNIQUE, so official decks
        # (owner_id=NULL) are intentionally unconstrained here.
        UniqueConstraint("owner_id", "source_notebook_id", name="uq_shared_deck_owner_source"),
    )

    id: str = SQLField(default_factory=_mint_deck_id, primary_key=True)
    owner_id: str | None = SQLField(default=None, index=True)  # NULL = official
    source_notebook_id: str | None = SQLField(default=None)  # author-side republish key
    title: str = SQLField(default="")
    description: str | None = SQLField(default=None)
    # Coarse filter enum: 'language'|'exam'|'phrase'|'custom'
    category: str | None = SQLField(default=None)
    tags: list[str] = SQLField(default_factory=list, sa_column=Column(JSON))
    language_pair: str | None = SQLField(default=None)  # e.g. 'en-zh'
    # server-authoritative: 'official'|'community' — NEVER read from request body
    source: str = SQLField(default="community")
    publisher_display_name: str | None = SQLField(default=None)  # snapshot at publish
    # exposure axis: 'private'|'unlisted'|'public'|'official'
    visibility: str = SQLField(default="private")
    share_token: str | None = SQLField(default=None, unique=True)  # unlisted access
    # moderation axis: 'active'|'under_review'|'removed'
    status: str = SQLField(default="active")
    is_deleted: bool = SQLField(default=False)  # existence axis (owner soft-unpublish)
    current_version: int = SQLField(default=0)  # atomically flipped pointer
    card_count: int = SQLField(default=0)
    color: str | None = SQLField(default=None)
    cover_pattern: str | None = SQLField(default=None)  # procedural cover; no image v1
    title_nfc_lower: str = SQLField(default="", index=True)  # search key
    download_count: int = SQLField(default=0)
    rating_sum: int = SQLField(default=0)  # denormalized cache (authority=rating table)
    rating_count: int = SQLField(default=0)
    report_count: int = SQLField(default=0)
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


class SharedDeckVersion(SQLModel, table=True):
    """Immutable payload pointer. Republish mints a new (deck, version) row;
    ``SharedDeck.current_version`` flips to it atomically. The composite PK is
    what catches concurrent-republish races via ``IntegrityError`` — not a
    ``threading.Lock``.
    """

    __tablename__ = "shared_deck_version"

    shared_deck_id: str = SQLField(primary_key=True)
    version: int = SQLField(primary_key=True)
    content_hash: str = SQLField(default="")  # over content plane, excl. timestamps
    payload_schema_version: int = SQLField(default=1)  # tolerate replaying old payloads
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


class SharedDeckCard(SQLModel, table=True):
    """Content plane ONLY — structurally zero SRS columns.

    A publish path cannot leak the 7 review columns because they do not exist
    here. ``content_guid`` covers (content, pos, mode, meaning) so homographs
    (``lead`` metal vs verb) do not collide into one guid.
    """

    __tablename__ = "shared_deck_card"
    __table_args__ = (
        UniqueConstraint(
            "shared_deck_id", "version", "content_guid", name="uq_shared_deck_card_guid"
        ),
    )

    id: str = SQLField(default_factory=lambda: secrets.token_urlsafe(9), primary_key=True)
    shared_deck_id: str = SQLField(index=True)
    version: int = SQLField(default=0)
    content_guid: str = SQLField(default="")
    content: str = SQLField(default="")
    pos: str | None = SQLField(default=None)
    meaning: str = SQLField(default="")
    examples: list[str] = SQLField(default_factory=list, sa_column=Column(JSON))
    collocations: list[str] = SQLField(default_factory=list, sa_column=Column(JSON))
    note: str | None = SQLField(default=None)
    difficulty: float | None = SQLField(default=None)
    mode: str = SQLField(default="recognition")
    root_form: str | None = SQLField(default=None)
    inflections: list[str] = SQLField(default_factory=list, sa_column=Column(JSON))


class SharedDeckRating(SQLModel, table=True):
    """One-vote-per-user authority (Phase 3 write path). ``rating_sum`` /
    ``rating_count`` on ``shared_deck`` are a denormalized cache of this table."""

    __tablename__ = "shared_deck_rating"

    shared_deck_id: str = SQLField(primary_key=True)
    user_id: str = SQLField(primary_key=True)
    stars: int = SQLField(default=0)  # 1-5
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


class SharedDeckReport(SQLModel, table=True):
    """Reactive moderation (Phase 3 write path). One report per reporter
    (composite PK) blocks Sybil report-stuffing."""

    __tablename__ = "shared_deck_report"

    shared_deck_id: str = SQLField(primary_key=True)
    reporter_id: str = SQLField(primary_key=True)
    # reason ∈ {'spam','offensive','copyright','pii','other'}
    reason: str = SQLField(default="other")
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


class SharedDeckCopyLog(SQLModel, table=True):
    """Copy idempotency store + rating-eligibility gate. A transport retry
    replays to the same ``result_notebook_id`` via the composite PK."""

    __tablename__ = "shared_deck_copy_log"

    copier_id: str = SQLField(primary_key=True)
    idempotency_key: str = SQLField(primary_key=True)
    source_shared_deck_id: str = SQLField(default="")
    source_version: int = SQLField(default=0)
    result_notebook_id: str = SQLField(default="")
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


_SHARED_DECK_TABLES = [
    SharedDeck.__table__,
    SharedDeckVersion.__table__,
    SharedDeckCard.__table__,
    SharedDeckRating.__table__,
    SharedDeckReport.__table__,
    SharedDeckCopyLog.__table__,
]


class SharedDeckStore:
    """SQLite-based global shared-decks catalog. One engine per process (cached
    under a user-independent key by ``deps``), not per request."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.engine = make_sqlite_engine(self.path)
        # Explicit table list (not a bare ``metadata.create_all``): the shared
        # SQLModel registry also holds Card/Notebook/... — only ours here.
        SQLModel.metadata.create_all(
            self.engine, tables=_SHARED_DECK_TABLES, checkfirst=True
        )

    def close(self) -> None:
        """Dispose the engine (required for LRU eviction — see LibraryStore)."""
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None


__all__ = [
    "SharedDeck",
    "SharedDeckVersion",
    "SharedDeckCard",
    "SharedDeckRating",
    "SharedDeckReport",
    "SharedDeckCopyLog",
    "SharedDeckStore",
]
