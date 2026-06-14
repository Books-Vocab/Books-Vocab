"""Read-only query operations for :class:`CardStore`.

Exposed as a mixin so the storage class can be split across modules
without changing the public API or method semantics.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import func, tuple_
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
        if not content:
            return None
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

    def all_as_dict(self, include_deleted: bool = False, notebook_id: str | None = None) -> dict[str, Card]:
        with Session(self.engine) as session:
            statement = select(Card)
            if not include_deleted:
                statement = statement.where(Card.is_deleted.is_(False))
            if notebook_id is not None:
                statement = statement.where(Card.notebook_id == notebook_id)
            return {card.id: card for card in session.exec(statement).all()}

    def get_batch(self, card_ids: set[str]) -> dict[str, Card]:
        """Fetch multiple cards by ID in a single query.

        Intentionally notebook-agnostic — unlike the content/word-based query
        methods (find_by_content / all / count …), this is a low-level id→Card
        primitive. Card ids are already unique within a user's store, and id is
        the caller's chosen scope. Two deliberate callers rely on this: graph
        neighbour expansion (vocab_crud), whose ids come from the per-notebook
        graph and are thus already same-notebook; and cross-notebook review-state
        sync (vocab_review, notebook_id=None by design), which must reach the
        user's cards across all notebooks. Adding a notebook filter here would
        break the latter — callers needing a scoped fetch must filter the result.
        """
        if not card_ids:
            return {}
        with Session(self.engine) as session:
            statement = select(Card).where(Card.id.in_(card_ids))
            return {card.id: card for card in session.exec(statement).all()}

    def page_cards(
        self,
        *,
        limit: int,
        after: tuple[datetime, str] | None,
        include_deleted: bool,
        notebook_id: str | None,
    ) -> list[Card]:
        """Return at most ``limit`` cards ordered by the composite cursor
        ``(updated_at, id)`` using a row-value comparison.

        Bounded by ``.limit`` — does NOT materialise the whole table or build a
        dict. ``after`` is the ``(updated_at, id)`` of the last card of the
        previous page; ``None`` starts from the first page. Paging is gap-free
        and duplicate-free even when many cards share an ``updated_at`` because
        ``id`` breaks ties. Backed by ``ix_card_updated_at_id``.

        Correctness relies on ``updated_at`` being stored as fixed-width UTC
        text (SQLite drops tz offsets): all card writes stamp
        ``datetime.now(UTC)`` server-side, so lexicographic text order equals
        chronological order. A non-UTC / variable-width write would corrupt the
        cursor ordering.
        """
        with Session(self.engine) as session:
            statement = select(Card)
            if not include_deleted:
                statement = statement.where(Card.is_deleted.is_(False))
            if notebook_id is not None:
                statement = statement.where(Card.notebook_id == notebook_id)
            if after is not None:
                statement = statement.where(
                    tuple_(Card.updated_at, Card.id) > tuple_(after[0], after[1])
                )
            statement = statement.order_by(Card.updated_at, Card.id).limit(limit)
            return list(session.exec(statement).all())

    def get_modified_since(self, since: datetime, notebook_id: str | None = None) -> list[Card]:
        """Fetch all cards (including soft-deleted) modified after the given timestamp."""
        with Session(self.engine) as session:
            statement = select(Card).where(Card.updated_at > since)
            if notebook_id is not None:
                statement = statement.where(Card.notebook_id == notebook_id)
            return list(session.exec(statement).all())

    def count(self, notebook_id: str | None = None) -> int:
        with Session(self.engine) as session:
            statement = select(func.count()).select_from(Card).where(Card.is_deleted.is_(False))
            if notebook_id is not None:
                statement = statement.where(Card.notebook_id == notebook_id)
            return session.scalar(statement) or 0

    def count_by_notebook(self) -> dict[str, int]:
        """Single GROUP BY query returning {notebook_id: count}."""
        with Session(self.engine) as session:
            rows = session.exec(
                select(Card.notebook_id, func.count())
                .where(Card.is_deleted.is_(False))
                .group_by(Card.notebook_id)
            ).all()
            return {nb_id: cnt for nb_id, cnt in rows}
