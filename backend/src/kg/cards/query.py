"""Read-only query operations for :class:`CardStore`.

Exposed as a mixin so the storage class can be split across modules
without changing the public API or method semantics.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from sqlmodel import Session, select

from ..text_utils import normalize_nfc_lower
from .model import Card


class CardQueryMixin:
    """Read-side methods of :class:`CardStore`. Requires ``self.engine``."""

    def get(self, card_id: str) -> Card | None:
        with Session(self.engine) as session:
            return session.get(Card, card_id)

    def find_by_content(self, content: str, notebook_id: str | None = None) -> Card | None:
        """Indexed case- and Unicode-insensitive lookup via `content_nfc_lower`.

        A single query against `ix_card_content_nfc_lower`; subsumes both
        case-insensitive and decomposed-Unicode (e.g. café) matching.
        """
        key = normalize_nfc_lower(content)
        with Session(self.engine) as session:
            stmt = select(Card).where(
                Card.content_nfc_lower == key,
                Card.is_deleted.is_(False),
            )
            if notebook_id is not None:
                stmt = stmt.where(Card.notebook_id == notebook_id)
            return session.exec(stmt).first()

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

    def get_batch(self, card_ids: set[str]) -> dict[str, "Card"]:
        """Fetch multiple cards by ID in a single query."""
        if not card_ids:
            return {}
        with Session(self.engine) as session:
            statement = select(Card).where(Card.id.in_(card_ids))
            return {card.id: card for card in session.exec(statement).all()}

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
