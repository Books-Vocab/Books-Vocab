"""Transactional persistence primitives for dictionary-card sidecars and sagas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..exceptions import ConflictError, NotFoundError
from ..lexical import LexicalEntry
from ..text_utils import normalize_nfc, normalize_nfc_lower
from .dictionary_models import (
    DictionaryArchiveLinkCause,
    DictionaryEntry,
    DictionaryLifecycleState,
    DictionaryPromotionJob,
    LexicalOperation,
)
from .model import Card


def _monotonic_now(previous: datetime, now: datetime) -> datetime:
    """Keep incremental-sync timestamps strictly increasing within a row."""
    if previous.tzinfo is None:
        now = now.replace(tzinfo=None)
    return max(now, previous + timedelta(microseconds=1))


@dataclass(frozen=True)
class PromotionEnqueueResult:
    card: Card
    already_promoted: bool


@dataclass(frozen=True)
class PromotionClaim:
    card: Card
    dictionary: DictionaryEntry
    job: DictionaryPromotionJob


@dataclass(frozen=True)
class DictionaryLifecyclePlan:
    card: Card
    action: str
    graph_snapshot_json: str
    link_ids: frozenset[str]
    needs_graph: bool


class PromotionLeaseLost(RuntimeError):
    """A recovered/retried job no longer belongs to this worker attempt."""


def _selected(entry: LexicalEntry, sense_key: str, example_key: str):
    sense = next((item for item in entry.senses if item.key == sense_key), None)
    if sense is None:
        raise NotFoundError("Dictionary sense", sense_key)
    example = next((item for item in sense.examples if item.key == example_key), None)
    if example is None:
        raise NotFoundError("Dictionary example", example_key)
    return sense, example


def _owns_promotion_claim(
    card: Card,
    job: DictionaryPromotionJob,
    *,
    worker_id: str | None,
    attempt_count: int,
) -> bool:
    return (
        card.card_role == "dictionary"
        and card.promotion_state == "running"
        and job.status == "running"
        and job.worker_id == worker_id
        and job.attempt_count == attempt_count
    )


class DictionaryCardStoreMixin:
    """Dictionary-only read/write methods. Requires ``self.engine``."""

    @staticmethod
    def _require_dictionary_lifecycle_card(
        session: Session,
        card_id: str,
        *,
        notebook_id: str,
    ) -> Card:
        """Resolve a notebook-owned, durable dictionary card for mutation.

        The retained sidecar is part of the resource identity even after a soft
        delete.  Role and promotion checks live in the same SQLite transaction
        as the state change so a promotion worker cannot race a lifecycle write.
        """
        card = session.get(Card, card_id)
        sidecar = session.get(DictionaryEntry, card_id)
        if (
            card is None
            or card.notebook_id != notebook_id
            or sidecar is None
            or sidecar.materialization_status != "active"
        ):
            raise NotFoundError("Dictionary card", card_id)
        if card.card_role != "dictionary":
            raise ConflictError(
                "A promoted learning card cannot use dictionary lifecycle actions"
            )
        if card.promotion_state in {"queued", "running"}:
            raise ConflictError(
                "Dictionary promotion must finish before a lifecycle action"
            )
        return card

    def begin_dictionary_lifecycle(
        self,
        card_id: str,
        *,
        notebook_id: str,
        action: str,
        graph_snapshot_json: str,
        graph_link_ids: set[str],
        cause_link_ids: set[str],
    ) -> DictionaryLifecyclePlan:
        """Atomically claim a card mutation and persist its graph reconciliation plan."""
        if action not in {"archive", "unarchive", "delete"}:
            raise ValueError(f"Unsupported dictionary lifecycle action: {action}")
        with Session(self.engine) as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            card = self._require_dictionary_lifecycle_card(
                session, card_id, notebook_id=notebook_id
            )
            state = session.get(DictionaryLifecycleState, card_id)
            if state is not None and state.pending_action is not None:
                if state.pending_action != action:
                    raise ConflictError(
                        "A dictionary lifecycle reconciliation is already pending"
                    )
                saved_links = frozenset(json.loads(state.pending_link_ids_json))
                saved_snapshot = state.graph_snapshot_json
                if saved_snapshot is None:
                    raise ConflictError("Pending dictionary lifecycle plan is incomplete")
                session.commit()
                session.refresh(card)
                return DictionaryLifecyclePlan(
                    card=card,
                    action=action,
                    graph_snapshot_json=saved_snapshot,
                    link_ids=saved_links,
                    needs_graph=True,
                )

            if action != "delete" and card.is_deleted:
                raise NotFoundError("Dictionary card", card_id)
            desired_already_applied = (
                (action == "archive" and card.is_archived)
                or (action == "unarchive" and not card.is_archived)
                or (action == "delete" and card.is_deleted)
            )
            if desired_already_applied:
                session.commit()
                session.refresh(card)
                return DictionaryLifecyclePlan(
                    card=card,
                    action=action,
                    graph_snapshot_json=graph_snapshot_json,
                    link_ids=frozenset(),
                    needs_graph=False,
                )

            now = datetime.now(UTC)
            if state is None:
                state = DictionaryLifecycleState(
                    card_id=card_id,
                    notebook_id=notebook_id,
                )
            state.pending_action = action
            state.graph_snapshot_json = graph_snapshot_json
            pending_causes: set[str] = set()
            if action == "archive":
                for link_id in cause_link_ids:
                    key = (card_id, link_id)
                    if session.get(DictionaryArchiveLinkCause, key) is None:
                        session.add(
                            DictionaryArchiveLinkCause(
                                card_id=card_id,
                                link_id=link_id,
                                notebook_id=notebook_id,
                            )
                        )
                        pending_causes.add(link_id)
            elif action == "unarchive":
                causes = list(
                    session.exec(
                        select(DictionaryArchiveLinkCause).where(
                            DictionaryArchiveLinkCause.card_id == card_id,
                            DictionaryArchiveLinkCause.notebook_id == notebook_id,
                        )
                    ).all()
                )
                for cause in causes:
                    session.delete(cause)
                    pending_causes.add(cause.link_id)
                session.flush()
                graph_link_ids = {
                    link_id
                    for link_id in pending_causes
                    if session.exec(
                        select(DictionaryArchiveLinkCause).where(
                            DictionaryArchiveLinkCause.link_id == link_id,
                            DictionaryArchiveLinkCause.notebook_id == notebook_id,
                        )
                    ).first()
                    is None
                }
            state.pending_link_ids_json = json.dumps(sorted(graph_link_ids))
            state.pending_cause_link_ids_json = json.dumps(sorted(pending_causes))
            state.card_before_archived = card.is_archived
            state.card_before_deleted = card.is_deleted
            state.updated_at = now

            if action == "archive":
                card.is_archived = True
            elif action == "unarchive":
                card.is_archived = False
            else:
                card.is_deleted = True
            card.updated_at = _monotonic_now(card.updated_at, now)
            session.add(card)
            session.add(state)
            session.commit()
            session.refresh(card)
            return DictionaryLifecyclePlan(
                card=card,
                action=action,
                graph_snapshot_json=graph_snapshot_json,
                link_ids=frozenset(graph_link_ids),
                needs_graph=True,
            )

    def complete_dictionary_lifecycle(
        self,
        card_id: str,
        *,
        action: str,
    ) -> Card:
        """Mark a pending graph plan complete and retain archive link lineage."""
        with Session(self.engine) as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            card = session.get(Card, card_id)
            state = session.get(DictionaryLifecycleState, card_id)
            if card is None or state is None or state.pending_action != action:
                raise ConflictError("Dictionary lifecycle plan is no longer pending")
            state.pending_action = None
            state.graph_snapshot_json = None
            state.pending_link_ids_json = "[]"
            state.pending_cause_link_ids_json = "[]"
            state.updated_at = datetime.now(UTC)
            session.add(state)
            session.commit()
            session.refresh(card)
            return card

    def rollback_dictionary_lifecycle(self, card_id: str, *, action: str) -> Card:
        """Restore the card half after graph snapshot rollback succeeded."""
        with Session(self.engine) as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            card = session.get(Card, card_id)
            state = session.get(DictionaryLifecycleState, card_id)
            if card is None or state is None or state.pending_action != action:
                raise ConflictError("Dictionary lifecycle plan is no longer pending")
            card.is_archived = state.card_before_archived
            card.is_deleted = state.card_before_deleted
            card.updated_at = _monotonic_now(card.updated_at, datetime.now(UTC))
            pending_causes = set(json.loads(state.pending_cause_link_ids_json))
            if action == "archive":
                for link_id in pending_causes:
                    cause = session.get(DictionaryArchiveLinkCause, (card_id, link_id))
                    if cause is not None:
                        session.delete(cause)
            elif action == "unarchive":
                for link_id in pending_causes:
                    if session.get(DictionaryArchiveLinkCause, (card_id, link_id)) is None:
                        session.add(
                            DictionaryArchiveLinkCause(
                                card_id=card_id,
                                link_id=link_id,
                                notebook_id=state.notebook_id,
                            )
                        )
            state.pending_action = None
            state.graph_snapshot_json = None
            state.pending_link_ids_json = "[]"
            state.pending_cause_link_ids_json = "[]"
            state.updated_at = datetime.now(UTC)
            session.add(card)
            session.add(state)
            session.commit()
            session.refresh(card)
            return card

    def dictionary_archive_link_ids(self, card_id: str) -> set[str]:
        with Session(self.engine) as session:
            return {
                cause.link_id
                for cause in session.exec(
                    select(DictionaryArchiveLinkCause).where(
                        DictionaryArchiveLinkCause.card_id == card_id
                    )
                ).all()
            }

    def dictionary_managed_archive_link_ids(self, *, notebook_id: str) -> set[str]:
        with Session(self.engine) as session:
            return {
                cause.link_id
                for cause in session.exec(
                    select(DictionaryArchiveLinkCause).where(
                        DictionaryArchiveLinkCause.notebook_id == notebook_id
                    )
                ).all()
            }

    def get_dictionary_entry(self, card_id: str) -> DictionaryEntry | None:
        with Session(self.engine) as session:
            return session.get(DictionaryEntry, card_id)

    def get_dictionary_promotion_job(self, card_id: str) -> DictionaryPromotionJob | None:
        with Session(self.engine) as session:
            return session.get(DictionaryPromotionJob, card_id)

    def get_dictionary_promotion_jobs(
        self, card_ids: set[str]
    ) -> dict[str, DictionaryPromotionJob]:
        if not card_ids:
            return {}
        with Session(self.engine) as session:
            return {
                job.card_id: job
                for job in session.exec(
                    select(DictionaryPromotionJob).where(
                        DictionaryPromotionJob.card_id.in_(card_ids)
                    )
                ).all()
            }

    def enqueue_dictionary_promotion(self, card_id: str) -> PromotionEnqueueResult:
        """Durably queue an idle/failed dictionary card.

        Repeated requests while queued/running are no-ops. A promoted learning
        card is recognized by its retained dictionary sidecar and reports
        ``already_promoted`` without creating a second job/card.
        """
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            card = session.get(Card, card_id)
            sidecar = session.get(DictionaryEntry, card_id)
            if (
                card is None
                or sidecar is None
                or sidecar.materialization_status != "active"
            ):
                raise NotFoundError("Dictionary card", card_id)
            if card.is_deleted:
                raise ConflictError("Deleted dictionary cards cannot be promoted")
            if card.card_role == "learning":
                return PromotionEnqueueResult(card=card, already_promoted=True)
            if card.card_role != "dictionary":
                raise ConflictError("Unsupported card role for promotion")
            if card.is_archived:
                raise ConflictError(
                    "Archived dictionary cards must be restored before promotion"
                )

            job = session.get(DictionaryPromotionJob, card_id)
            if card.promotion_state in {"queued", "running"}:
                if job is None:
                    raise ConflictError("Promotion state is missing its durable job")
                return PromotionEnqueueResult(card=card, already_promoted=False)

            if card.promotion_state not in {"idle", "failed"}:
                raise ConflictError("Invalid dictionary promotion state")
            card.promotion_state = "queued"
            card.updated_at = _monotonic_now(card.updated_at, now)
            if job is None:
                job = DictionaryPromotionJob(
                    card_id=card_id,
                    status="queued",
                    queued_at=now,
                    updated_at=now,
                )
            else:
                job.status = "queued"
                job.error_code = None
                job.retryable = None
                job.queued_at = now
                job.started_at = None
                job.finished_at = None
                job.updated_at = now
            session.add(card)
            session.add(job)
            session.commit()
            session.refresh(card)
            return PromotionEnqueueResult(card=card, already_promoted=False)

    def recover_orphaned_dictionary_promotion(
        self, card_id: str, *, current_worker_id: str
    ) -> bool:
        """Requeue a running job owned by a previous server generation."""
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            card = session.get(Card, card_id)
            job = session.get(DictionaryPromotionJob, card_id)
            if card is None or job is None:
                return False
            if (
                card.card_role != "dictionary"
                or card.promotion_state != "running"
                or job.status != "running"
                or job.worker_id == current_worker_id
            ):
                return False
            card.promotion_state = "queued"
            card.updated_at = _monotonic_now(card.updated_at, now)
            job.status = "queued"
            job.worker_id = None
            job.started_at = None
            job.updated_at = now
            session.add(card)
            session.add(job)
            session.commit()
            return True

    def claim_dictionary_promotion(
        self, card_id: str, *, worker_id: str | None = None
    ) -> PromotionClaim | None:
        """Atomically claim a queued promotion; return ``None`` if not queued."""
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            card = session.get(Card, card_id)
            sidecar = session.get(DictionaryEntry, card_id)
            job = session.get(DictionaryPromotionJob, card_id)
            if card is None or sidecar is None or job is None:
                raise NotFoundError("Dictionary promotion", card_id)
            if card.promotion_state != "queued" or job.status != "queued":
                return None
            if card.card_role != "dictionary" or card.review_eligible is not False:
                raise ConflictError("Only review-ineligible dictionary cards can be claimed")
            card.promotion_state = "running"
            card.updated_at = _monotonic_now(card.updated_at, now)
            job.status = "running"
            job.attempt_count += 1
            job.worker_id = worker_id
            job.started_at = now
            job.finished_at = None
            job.updated_at = now
            session.add(card)
            session.add(job)
            session.commit()
            session.refresh(card)
            session.refresh(sidecar)
            session.refresh(job)
            return PromotionClaim(card=card, dictionary=sidecar, job=job)

    def complete_dictionary_promotion(
        self,
        card_id: str,
        *,
        worker_id: str | None,
        attempt_count: int,
        meaning: str,
        pos: str | None,
        note: str | None,
        collocations: list[str],
        difficulty: float,
    ) -> Card:
        """Commit Stage A content, role transfer, and fresh SRS in one tx."""
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            card = session.get(Card, card_id)
            sidecar = session.get(DictionaryEntry, card_id)
            job = session.get(DictionaryPromotionJob, card_id)
            if card is None or sidecar is None or job is None:
                raise NotFoundError("Dictionary promotion", card_id)
            if not _owns_promotion_claim(
                card,
                job,
                worker_id=worker_id,
                attempt_count=attempt_count,
            ):
                raise PromotionLeaseLost(card_id)

            card.meaning = meaning
            card.pos = pos
            card.note = note
            card.collocations = list(collocations)
            card.difficulty = difficulty
            card.card_role = "learning"
            card.review_eligible = True
            card.promotion_state = "idle"
            card.promoted_at = now
            card.review_interval_hours = 12.0
            card.next_review_at = None
            card.last_reviewed_at = None
            card.review_count = 0
            card.lapse_count = 0
            card.review_streak = 0
            card.last_review_feedback = -1
            card.updated_at = _monotonic_now(card.updated_at, now)
            job.status = "completed"
            job.error_code = None
            job.retryable = None
            job.worker_id = None
            job.finished_at = now
            job.updated_at = now
            session.add(card)
            session.add(job)
            session.commit()
            session.refresh(card)
            return card

    def fail_dictionary_promotion(
        self,
        card_id: str,
        *,
        worker_id: str | None,
        attempt_count: int,
        error_code: str,
        retryable: bool,
    ) -> Card:
        """Record a classified Stage A failure without altering card content."""
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            card = session.get(Card, card_id)
            job = session.get(DictionaryPromotionJob, card_id)
            if card is None or job is None:
                raise NotFoundError("Dictionary promotion", card_id)
            if not _owns_promotion_claim(
                card,
                job,
                worker_id=worker_id,
                attempt_count=attempt_count,
            ):
                raise PromotionLeaseLost(card_id)
            card.review_eligible = False
            card.promotion_state = "failed"
            card.updated_at = _monotonic_now(card.updated_at, now)
            job.status = "failed"
            job.error_code = error_code
            job.retryable = retryable
            job.worker_id = None
            job.finished_at = now
            job.updated_at = now
            session.add(card)
            session.add(job)
            session.commit()
            session.refresh(card)
            return card
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
                    ) from None
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
