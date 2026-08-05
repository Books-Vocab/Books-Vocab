"""Transactional persistence primitives for dictionary-card sidecars and sagas."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..exceptions import ConflictError, NotFoundError
from ..lexical import LexicalEntry
from ..text_utils import normalize_nfc, normalize_nfc_lower
from .dictionary_models import DictionaryEntry, LexicalOperation
from .model import Card


def _selected(entry: LexicalEntry, sense_key: str, example_key: str):
    sense = next((item for item in entry.senses if item.key == sense_key), None)
    if sense is None:
        raise NotFoundError("Dictionary sense", sense_key)
    example = next((item for item in sense.examples if item.key == example_key), None)
    if example is None:
        raise NotFoundError("Dictionary example", example_key)
    return sense, example


class DictionaryCardStoreMixin:
    """Dictionary-only read/write methods. Requires ``self.engine``."""

    def get_dictionary_entry(self, card_id: str) -> DictionaryEntry | None:
        with Session(self.engine) as session:
            return session.get(DictionaryEntry, card_id)

    def get_active_dictionary_card_ids(self, card_ids: set[str]) -> set[str]:
        if not card_ids:
            return set()
        with Session(self.engine) as session:
            return set(
                session.exec(
                    select(DictionaryEntry.card_id).where(
                        DictionaryEntry.card_id.in_(card_ids),
                        DictionaryEntry.materialization_status == "active",
                    )
                ).all()
            )

    def get_lexical_operation(self, idempotency_key: str) -> LexicalOperation | None:
        with Session(self.engine) as session:
            return session.get(LexicalOperation, idempotency_key)

    def begin_lexical_operation(self, idempotency_key: str, request_hash: str) -> LexicalOperation:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            operation = session.get(LexicalOperation, idempotency_key)
            if operation is not None:
                if operation.request_hash != request_hash:
                    raise ConflictError("Idempotency-Key was already used with a different request")
                return operation
            operation = LexicalOperation(
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                status="started",
                created_at=now,
                updated_at=now,
            )
            session.add(operation)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                operation = session.get(LexicalOperation, idempotency_key)
                if operation is None:
                    raise
                if operation.request_hash != request_hash:
                    raise ConflictError(
                        "Idempotency-Key was already used with a different request"
                    )
                return operation
            session.refresh(operation)
            return operation

    def update_lexical_operation(self, idempotency_key: str, **values) -> LexicalOperation:
        with Session(self.engine) as session:
            operation = session.get(LexicalOperation, idempotency_key)
            if operation is None:
                raise NotFoundError("Lexical operation", idempotency_key)
            for key, value in values.items():
                if not hasattr(operation, key):
                    raise ValueError(f"Unknown lexical operation field: {key}")
                setattr(operation, key, value)
            operation.updated_at = datetime.now(UTC)
            session.add(operation)
            session.commit()
            session.refresh(operation)
            return operation

    def stage_dictionary_card(
        self,
        *,
        entry: LexicalEntry,
        notebook_id: str,
        sense_key: str,
        example_key: str,
    ) -> tuple[Card, bool]:
        """Reuse the active notebook card or atomically create card + staged sidecar."""
        normalized = normalize_nfc(entry.word)
        key = normalize_nfc_lower(normalized)
        with Session(self.engine) as session:
            existing = session.exec(
                select(Card).where(
                    Card.content_nfc_lower == key,
                    Card.notebook_id == notebook_id,
                    Card.is_deleted.is_(False),
                )
            ).first()
            if existing is not None:
                if existing.card_role == "dictionary" and session.get(DictionaryEntry, existing.id) is None:
                    raise ConflictError("Dictionary card is missing its saved dictionary entry")
                return existing, False

            sense, example = _selected(entry, sense_key, example_key)
            meaning = sense.translations[0] if sense.translations else sense.definition

            card = Card(
                content=normalized,
                content_nfc_lower=key,
                meaning=meaning,
                pos=sense.part_of_speech,
                examples=[example.text],
                root_form=entry.word,
                inflections=entry.forms,
                notebook_id=notebook_id,
                card_role="dictionary",
                review_eligible=False,
                reader_hidden=False,
            )
            sidecar = DictionaryEntry(
                card_id=card.id,
                provider=entry.provider,
                dictionary_id=entry.dictionary_id,
                provider_entry_key=entry.entry_key,
                provider_schema_version=entry.schema_version,
                selected_sense_key=sense.key,
                selected_example_key=example.key,
                payload_json=entry.model_dump_json(),
                source_url=entry.attribution.source_url,
                license_name=entry.attribution.license_name,
                license_url=entry.attribution.license_url,
                attribution_text=entry.attribution.attribution_text,
                fetched_at=entry.fetched_at,
                materialization_status="staged",
            )
            session.add(card)
            session.add(sidecar)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.exec(
                    select(Card).where(
                        Card.content_nfc_lower == key,
                        Card.notebook_id == notebook_id,
                        Card.is_deleted.is_(False),
                    )
                ).first()
                if existing is None:
                    raise
                return existing, False
            session.refresh(card)
            return card, True

    def activate_dictionary_entry_and_complete_operation(
        self,
        *,
        card_id: str,
        idempotency_key: str,
        response_json: str,
    ) -> None:
        """Cross the projection barrier and complete the ledger in one SQLite tx."""
        with Session(self.engine) as session:
            operation = session.get(LexicalOperation, idempotency_key)
            if operation is None:
                raise NotFoundError("Lexical operation", idempotency_key)
            sidecar = session.get(DictionaryEntry, card_id)
            if sidecar is not None:
                sidecar.materialization_status = "active"
                session.add(sidecar)
            operation.status = "completed"
            operation.card_id = card_id
            operation.response_json = response_json
            operation.updated_at = datetime.now(UTC)
            session.add(operation)
            session.commit()

    def update_dictionary_selection(
        self, card_id: str, *, sense_key: str, example_key: str
    ) -> DictionaryEntry:
        with Session(self.engine) as session:
            card = session.get(Card, card_id)
            sidecar = session.get(DictionaryEntry, card_id)
            if card is None or card.is_deleted or sidecar is None or sidecar.materialization_status != "active":
                raise NotFoundError("Dictionary card", card_id)
            if card.card_role != "dictionary":
                raise ConflictError("A promoted learning card cannot change dictionary selection")
            entry = LexicalEntry.model_validate_json(sidecar.payload_json)
            sense, example = _selected(entry, sense_key, example_key)
            sidecar.selected_sense_key = sense.key
            sidecar.selected_example_key = example.key
            card.meaning = sense.translations[0] if sense.translations else sense.definition
            card.pos = sense.part_of_speech
            card.examples = [example.text]
            card.updated_at = datetime.now(UTC)
            session.add(sidecar)
            session.add(card)
            session.commit()
            session.refresh(sidecar)
            return sidecar

    def set_reader_hidden(self, card_id: str, reader_hidden: bool) -> Card:
        with Session(self.engine) as session:
            card = session.get(Card, card_id)
            if card is None or card.is_deleted:
                raise NotFoundError("Card", card_id)
            if card.reader_hidden != reader_hidden:
                card.reader_hidden = reader_hidden
                card.updated_at = datetime.now(UTC)
                session.add(card)
                session.commit()
                session.refresh(card)
            return card

    def page_dictionary_cards(
        self,
        *,
        notebook_id: str | None,
        limit: int,
        after: tuple[datetime, str] | None = None,
        since: datetime | None = None,
    ) -> list[tuple[Card, DictionaryEntry]]:
        """Saved dictionary projection, including tombstones and promoted role transfers."""
        with Session(self.engine) as session:
            statement = (
                select(Card, DictionaryEntry)
                .join(DictionaryEntry, DictionaryEntry.card_id == Card.id)
                .where(DictionaryEntry.materialization_status == "active")
            )
            if notebook_id is not None:
                statement = statement.where(Card.notebook_id == notebook_id)
            if since is not None:
                statement = statement.where(Card.updated_at > since)
            if after is not None:
                statement = statement.where(
                    (Card.updated_at > after[0])
                    | ((Card.updated_at == after[0]) & (Card.id > after[1]))
                )
            statement = statement.order_by(Card.updated_at, Card.id).limit(limit)
            return list(session.exec(statement).all())
