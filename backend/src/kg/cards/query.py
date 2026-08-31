"""Read-only query operations for :class:`CardStore`.

Exposed as a mixin so the storage class can be split across modules
without changing the public API or method semantics.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import BigInteger, String, case, cast, func, text, tuple_
from sqlmodel import Session, select

from ..text_utils import normalize_nfc_lower
from .model import Card


def _utc_instant(value: datetime) -> datetime:
    """Interpret naive database timestamps as UTC and normalize aware ones."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_stored_timestamp(value: str) -> datetime:
    """Parse SQLite's ISO timestamp text without discarding its offset."""
    return _utc_instant(datetime.fromisoformat(value.replace(" ", "T")))


def _epoch_microseconds(value: datetime) -> int:
    """Return an exact UTC epoch key for a cursor timestamp."""
    instant = _utc_instant(value)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = instant - epoch
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _is_ascii_digit(value, position: int):
    """Build a SQLite expression that checks one timestamp character."""
    return func.substr(value, position, 1).op("GLOB")("[0-9]")


def _fractional_microseconds(value):
    """Build an exact six-digit fractional-second expression for SQLite text."""
    return case(
        (func.substr(value, 20, 1) != ".", 0),
        (~_is_ascii_digit(value, 21), 0),
        (~_is_ascii_digit(value, 22), cast(func.substr(value, 21, 1), BigInteger) * 100_000),
        (~_is_ascii_digit(value, 23), cast(func.substr(value, 21, 2), BigInteger) * 10_000),
        (~_is_ascii_digit(value, 24), cast(func.substr(value, 21, 3), BigInteger) * 1_000),
        (~_is_ascii_digit(value, 25), cast(func.substr(value, 21, 4), BigInteger) * 100),
        (~_is_ascii_digit(value, 26), cast(func.substr(value, 21, 5), BigInteger) * 10),
        else_=cast(func.substr(value, 21, 6), BigInteger),
    )


def _stored_timestamp_key(column):
    """Build a UTC-microsecond key from an ISO timestamp stored in SQLite."""
    value = cast(column, String)
    seconds = cast(func.strftime("%s", value), BigInteger)
    return seconds * 1_000_000 + _fractional_microseconds(value)


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
        ``(updated_at, id)`` using a UTC-normalized row-value comparison.

        Bounded by ``.limit`` — does NOT materialise the whole table or build a
        dict. ``after`` is the ``(updated_at, id)`` of the last card of the
        previous page; ``None`` starts from the first page. Paging is gap-free
        and duplicate-free even when many cards share an ``updated_at`` because
        ``id`` breaks ties. SQLite's text timestamps are converted to exact
        UTC-microsecond keys so legacy offset-bearing rows cannot corrupt the
        cursor boundary.

        The normalized expression preserves the existing wire cursor and handles
        both canonical UTC rows and legacy ISO timestamps with offsets.
        """
        with Session(self.engine) as session:
            statement = select(Card)
            if not include_deleted:
                statement = statement.where(Card.is_deleted.is_(False))
            if notebook_id is not None:
                statement = statement.where(Card.notebook_id == notebook_id)
            updated_at_key = _stored_timestamp_key(Card.updated_at)
            if after is not None:
                statement = statement.where(
                    tuple_(updated_at_key, Card.id) > tuple_(_epoch_microseconds(after[0]), after[1])
                )
            statement = statement.order_by(updated_at_key, Card.id).limit(limit)
            return list(session.exec(statement).all())

    def get_modified_since(
        self,
        since: datetime,
        notebook_id: str | None = None,
    ) -> list[Card]:
        """Fetch all cards modified after ``since`` as a UTC-instant comparison.

        SQLite stores these timestamps as text, so comparing the raw column to
        a datetime would order mixed-offset values lexicographically instead of
        by their actual instant. Read the raw text to preserve offsets and use
        Python's microsecond-precise datetime comparison. This retains the
        exclusive boundary and includes soft-deleted cards.
        """
        with Session(self.engine) as session:
            conditions: list[str] = []
            params: dict[str, str] = {}
            if notebook_id is not None:
                conditions.append("notebook_id = :notebook_id")
                params["notebook_id"] = notebook_id
            raw_query = "SELECT id, updated_at FROM card"
            if conditions:
                raw_query += " WHERE " + " AND ".join(conditions)
            rows = session.execute(
                text(raw_query),
                params,
            ).all()
            since_utc = _utc_instant(since)
            modified_rows = [
                (card_id, _parse_stored_timestamp(updated_at))
                for card_id, updated_at in rows
                if _parse_stored_timestamp(updated_at) > since_utc
            ]
            modified_ids = [
                card_id
                for card_id, _updated_at in sorted(
                    modified_rows,
                    key=lambda row: (row[1], row[0]),
                )
            ]
            if not modified_ids:
                return []
            cards = session.exec(select(Card).where(Card.id.in_(modified_ids))).all()
            cards_by_id = {card.id: card for card in cards}
            return [cards_by_id[card_id] for card_id in modified_ids]

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
                select(Card.notebook_id, func.count()).where(Card.is_deleted.is_(False)).group_by(Card.notebook_id)
            ).all()
            return {nb_id: cnt for nb_id, cnt in rows}
