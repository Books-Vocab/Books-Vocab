"""Saved dictionary cards, idempotent materialization, and sync projection."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .api_models.graph import GraphLinkResponse
from .cards.dictionary_models import (
    DictionaryEntry,
    DictionaryPromotionJob,
    LexicalOperation,
)
from .cards.model import Card
from .exceptions import ConflictError, NotFoundError
from .graph import GraphCardLifecycleSnapshot, GraphLifecycleRollbackError, LinkKind
from .judge.models import Judgement
from .keyed_lock_registry import DICTIONARY_LOCK_REGISTRY
from .lexical import LexicalEntry

logger = logging.getLogger(__name__)


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class DictionaryCardNode(_CamelModel):
    id: str
    content: str
    meaning: str
    pos: str | None = None
    examples: list[str] = Field(default_factory=list)
    inflections: list[str] = Field(default_factory=list)
    notebook_id: str
    card_role: str
    review_eligible: bool
    reader_hidden: bool
    promotion_state: str
    promoted_at: datetime | None = None
    is_deleted: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class SavedDictionaryCard(_CamelModel):
    card: DictionaryCardNode
    entry: LexicalEntry
    selected_sense_key: str
    selected_example_key: str
    materialization_status: str
    promotion_error_code: str | None = None
    promotion_retryable: bool | None = None

    @property
    def reader_hidden(self) -> bool:
        return self.card.reader_hidden


class DictionaryProjectionItem(_CamelModel):
    card: DictionaryCardNode
    dictionary: SavedDictionaryCard
    reader_hidden: bool
    links: list[GraphLinkResponse] = Field(default_factory=list)


class DictionaryProjection(_CamelModel):
    items: list[DictionaryProjectionItem] = Field(default_factory=list)
    next_cursor: str | None = None


class MaterializeLinkResult(_CamelModel):
    target_card: DictionaryCardNode
    dictionary_card: DictionaryProjectionItem | None = None
    link: GraphLinkResponse
    created_card: bool
    created_link: bool
    replayed: bool = False


def _card_node(card: Card) -> DictionaryCardNode:
    return DictionaryCardNode(
        id=card.id,
        content=card.content,
        meaning=card.meaning,
        pos=card.pos,
        examples=card.examples or [],
        inflections=card.inflections or [],
        notebook_id=card.notebook_id,
        card_role=card.card_role,
        review_eligible=card.review_eligible,
        reader_hidden=card.reader_hidden,
        promotion_state=card.promotion_state,
        promoted_at=card.promoted_at,
        is_deleted=card.is_deleted,
        is_archived=card.is_archived,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def _saved(
    card: Card,
    sidecar: DictionaryEntry,
    job: DictionaryPromotionJob | None = None,
) -> SavedDictionaryCard:
    return SavedDictionaryCard(
        card=_card_node(card),
        entry=LexicalEntry.model_validate_json(sidecar.payload_json),
        selected_sense_key=sidecar.selected_sense_key,
        selected_example_key=sidecar.selected_example_key,
        materialization_status=sidecar.materialization_status,
        promotion_error_code=job.error_code if job is not None else None,
        promotion_retryable=job.retryable if job is not None else None,
    )


def _link_response(link: Any) -> GraphLinkResponse:
    return GraphLinkResponse(
        id=link.id,
        fromId=link.from_id,
        toId=link.to_id,
        kind=link.kind.value,
        confidence=link.confidence,
        reason=link.reason,
    )


def encode_dictionary_cursor(updated_at: datetime, card_id: str) -> str:
    raw = json.dumps([updated_at.isoformat(), card_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_dictionary_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        value = cursor + "=" * (-len(cursor) % 4)
        updated_at, card_id = json.loads(base64.urlsafe_b64decode(value).decode())
        parsed = datetime.fromisoformat(updated_at)
        if not isinstance(card_id, str) or not card_id:
            raise ValueError
        return parsed, card_id
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeError) as exc:
        from .exceptions import BadRequestError

        raise BadRequestError("Malformed dictionary cursor") from exc


class DictionaryCardService:
    def __init__(
        self,
        *,
        cards: Any,
        graph: Any,
        lexical: Any,
        judge: Any,
        crash_hook: Callable[[str], None] | None = None,
        graph_resolver: Callable[[str], Any] | None = None,
    ) -> None:
        self.cards = cards
        self.graph = graph
        self.lexical = lexical
        self.judge = judge
        self.crash_hook = crash_hook or (lambda _step: None)
        self.graph_resolver = graph_resolver or (lambda _notebook_id: self.graph)
        self._lock_registry = DICTIONARY_LOCK_REGISTRY
        self._lock_key = str(cards.path.resolve())

    def get_operation(self, idempotency_key: str) -> LexicalOperation:
        operation = self.cards.get_lexical_operation(idempotency_key)
        if operation is None:
            raise NotFoundError("Lexical operation", idempotency_key)
        return operation

    def get_saved_card(self, card_id: str) -> SavedDictionaryCard:
        card = self.cards.get(card_id)
        sidecar = self.cards.get_dictionary_entry(card_id)
        if (
            card is None
            or sidecar is None
            or sidecar.materialization_status != "active"
        ):
            raise NotFoundError("Dictionary card", card_id)
        return _saved(card, sidecar, self.cards.get_dictionary_promotion_job(card_id))

    def list_projection(
        self,
        *,
        notebook_id: str | None,
        limit: int,
        since: datetime | None = None,
        cursor: str | None = None,
    ) -> DictionaryProjection:
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        after = decode_dictionary_cursor(cursor) if cursor else None
        rows = self.cards.page_dictionary_cards(
            notebook_id=notebook_id,
            limit=limit + 1,
            after=after,
            since=since,
        )
        page = rows[:limit]
        links_by_card = self._links_for_projection(page)
        jobs_by_card = self.cards.get_dictionary_promotion_jobs(
            {card.id for card, _sidecar in page}
        )
        items = [
            DictionaryProjectionItem(
                card=_card_node(card),
                dictionary=_saved(card, sidecar, jobs_by_card.get(card.id)),
                reader_hidden=card.reader_hidden,
                links=links_by_card.get(card.id, []),
            )
            for card, sidecar in page
        ]
        next_cursor = None
        if len(rows) > limit and page:
            next_cursor = encode_dictionary_cursor(page[-1][0].updated_at, page[-1][0].id)
        return DictionaryProjection(items=items, next_cursor=next_cursor)

    def _links_for_projection(
        self, rows: list[tuple[Card, DictionaryEntry]]
    ) -> dict[str, list[GraphLinkResponse]]:
        """Batch link projection once per notebook and once per SQLite lookup."""
        projected_by_notebook: dict[str, set[str]] = {}
        for card, _sidecar in rows:
            projected_by_notebook.setdefault(card.notebook_id, set()).add(card.id)
        candidates_by_notebook: dict[str, list[Any]] = {}
        endpoint_ids: set[str] = set()
        for notebook_id, projected_ids in projected_by_notebook.items():
            links = [
                link
                for link in self.graph_resolver(notebook_id).all_links()
                if link.status == "active"
                and (link.from_id in projected_ids or link.to_id in projected_ids)
            ]
            candidates_by_notebook[notebook_id] = links
            endpoint_ids.update(
                endpoint
                for link in links
                for endpoint in (link.from_id, link.to_id)
            )
        cards_by_id = self.cards.get_batch(endpoint_ids)
        dictionary_ids = {
            endpoint
            for endpoint, card in cards_by_id.items()
            if getattr(card, "card_role", "learning") == "dictionary"
        }
        active_dictionary_ids = self.cards.get_active_dictionary_card_ids(dictionary_ids)
        result: dict[str, list[GraphLinkResponse]] = {
            card_id: []
            for projected_ids in projected_by_notebook.values()
            for card_id in projected_ids
        }
        for notebook_id, links in candidates_by_notebook.items():
            projected_ids = projected_by_notebook[notebook_id]
            for link in links:
                if any(
                    endpoint in dictionary_ids and endpoint not in active_dictionary_ids
                    for endpoint in (link.from_id, link.to_id)
                ):
                    continue
                response = _link_response(link)
                for endpoint in (link.from_id, link.to_id):
                    if endpoint in projected_ids:
                        result[endpoint].append(response)
        return result

    def update_selection(
        self, card_id: str, *, sense_key: str, example_key: str
    ) -> SavedDictionaryCard:
        self.cards.update_dictionary_selection(
            card_id, sense_key=sense_key, example_key=example_key
        )
        return self.get_saved_card(card_id)

    def set_reader_visibility(self, card_id: str, *, reader_hidden: bool) -> DictionaryCardNode:
        return _card_node(self.cards.set_reader_hidden(card_id, reader_hidden))

    def set_archived(
        self,
        card_id: str,
        *,
        notebook_id: str,
        archived: bool,
    ) -> DictionaryCardNode:
        action = "archive" if archived else "unarchive"
        with self._lock_registry.lock(self._lock_key):
            graph = self.graph_resolver(notebook_id)
            snapshot = graph.capture_card_lifecycle_snapshot(card_id)
            incident_ids = {link.id for link in snapshot.links}
            active_ids = {link.id for link in snapshot.links if link.status == "active"}
            if archived:
                managed_ids = self.cards.dictionary_managed_archive_link_ids(
                    notebook_id=notebook_id
                )
                cause_link_ids = active_ids | (incident_ids & managed_ids)
                graph_link_ids = active_ids
            else:
                cause_link_ids = self.cards.dictionary_archive_link_ids(card_id)
                graph_link_ids = set()
            plan = self.cards.begin_dictionary_lifecycle(
                card_id,
                notebook_id=notebook_id,
                action=action,
                graph_snapshot_json=snapshot.model_dump_json(),
                graph_link_ids=graph_link_ids,
                cause_link_ids=cause_link_ids,
            )
            if not plan.needs_graph:
                return _card_node(plan.card)
            self.crash_hook("after_lifecycle_card_commit")
            durable_snapshot = GraphCardLifecycleSnapshot.model_validate_json(
                plan.graph_snapshot_json
            )
            try:
                graph.apply_card_lifecycle(
                    durable_snapshot,
                    action=action,
                    link_ids=set(plan.link_ids),
                    cards_store=self.cards,
                    source="manual",
                )
            except GraphLifecycleRollbackError:
                logger.exception(
                    "Graph rollback incomplete for dictionary card %s; plan retained",
                    card_id,
                )
                raise
            except Exception:
                logger.error(
                    "Graph operation failed for dictionary card %s", card_id, exc_info=True
                )
                self.cards.rollback_dictionary_lifecycle(card_id, action=action)
                raise
            return _card_node(
                self.cards.complete_dictionary_lifecycle(card_id, action=action)
            )

    def soft_delete(
        self,
        card_id: str,
        *,
        notebook_id: str,
    ) -> DictionaryCardNode:
        action = "delete"
        with self._lock_registry.lock(self._lock_key):
            graph = self.graph_resolver(notebook_id)
            snapshot = graph.capture_card_lifecycle_snapshot(card_id)
            plan = self.cards.begin_dictionary_lifecycle(
                card_id,
                notebook_id=notebook_id,
                action=action,
                graph_snapshot_json=snapshot.model_dump_json(),
                graph_link_ids={
                    link.id for link in snapshot.links if link.status == "active"
                },
                cause_link_ids=set(),
            )
            if not plan.needs_graph:
                return _card_node(plan.card)
            self.crash_hook("after_lifecycle_card_commit")
            durable_snapshot = GraphCardLifecycleSnapshot.model_validate_json(
                plan.graph_snapshot_json
            )
            try:
                graph.apply_card_lifecycle(
                    durable_snapshot,
                    action=action,
                    link_ids=set(plan.link_ids),
                    cards_store=self.cards,
                    source="manual",
                )
            except GraphLifecycleRollbackError:
                logger.exception(
                    "Graph rollback incomplete for dictionary card %s; plan retained",
                    card_id,
                )
                raise
            except Exception:
                logger.error(
                    "Graph operation failed for dictionary card %s", card_id, exc_info=True
                )
                self.cards.rollback_dictionary_lifecycle(card_id, action=action)
                raise
            return _card_node(
                self.cards.complete_dictionary_lifecycle(card_id, action=action)
            )

    def materialize_and_link(
        self,
        *,
        idempotency_key: str,
        source_card_id: str,
        notebook_id: str,
        provider: str,
        entry_key: str,
        sense_key: str,
        example_key: str,
    ) -> MaterializeLinkResult:
        if not idempotency_key.strip():
            raise ValueError("Idempotency-Key is required")
        request_values = {
            "source_card_id": source_card_id,
            "notebook_id": notebook_id,
            "provider": provider,
            "entry_key": entry_key,
            "sense_key": sense_key,
            "example_key": example_key,
        }
        request_hash = materialize_request_hash(request_values)
        with self._lock_registry.lock(self._lock_key):
            operation = self.cards.begin_lexical_operation(idempotency_key, request_hash)
            if operation.status == "completed" and operation.response_json:
                result = MaterializeLinkResult.model_validate_json(operation.response_json)
                return result.model_copy(update={"replayed": True})

            source = self.cards.get(source_card_id)
            if (
                source is None
                or source.is_deleted
                or source.is_archived
                or source.notebook_id != notebook_id
            ):
                raise NotFoundError("Card", source_card_id)

            lookup = self.lexical.get_entry(provider, entry_key, target_language="zh-Hant")
            entry = lookup.entry
            if entry is None or entry.provider != provider or entry.entry_key != entry_key:
                raise NotFoundError("Dictionary entry", entry_key)

            existing_target = self.cards.find_by_content(entry.word, notebook_id=notebook_id)
            if existing_target is not None and existing_target.id == source_card_id:
                raise ConflictError("A card cannot be linked to itself")

            if existing_target is not None:
                # Notebook uniqueness wins over the client selection. A saved
                # dictionary card keeps its pinned context; a learning card is
                # reused as-is and is never downgraded or sidecar-stamped.
                target_word = existing_target.content
                target_meaning = existing_target.meaning
                if existing_target.card_role == "dictionary":
                    pinned = self.cards.get_dictionary_entry(existing_target.id)
                    if pinned is None:
                        raise ConflictError("Dictionary card is missing its saved dictionary entry")
                    pinned_entry = LexicalEntry.model_validate_json(pinned.payload_json)
                    pinned_sense = next(
                        (sense for sense in pinned_entry.senses if sense.key == pinned.selected_sense_key),
                        None,
                    )
                    if pinned_sense is None:
                        raise ConflictError("Dictionary card has an invalid pinned selection")
                    target_word = pinned_entry.word
                    target_meaning = (
                        pinned_sense.translations[0]
                        if pinned_sense.translations
                        else pinned_sense.definition
                    )
            else:
                target_word = entry.word
                target_meaning = next(
                    (
                        (sense.translations[0] if sense.translations else sense.definition)
                        for sense in entry.senses
                        if sense.key == sense_key
                    ),
                    "",
                )
                if not target_meaning:
                    raise NotFoundError("Dictionary sense", sense_key)

            relation: Judgement
            if operation.relation_json:
                relation = Judgement.model_validate_json(operation.relation_json)
            else:
                relation = self.judge.evaluate(
                    source.content,
                    source.meaning,
                    target_word,
                    target_meaning,
                    from_id=source.id,
                    to_id=existing_target.id if existing_target else "",
                )
                operation = self.cards.update_lexical_operation(
                    idempotency_key,
                    status="judged",
                    relation_json=relation.model_dump_json(),
                )

            target, created_card = self.cards.stage_dictionary_card(
                entry=entry,
                notebook_id=notebook_id,
                sense_key=sense_key,
                example_key=example_key,
            )
            if target.id == source.id:
                raise ConflictError("A card cannot be linked to itself")
            if target.is_archived:
                raise ConflictError("Archived cards must be restored before linking")
            self.cards.update_lexical_operation(
                idempotency_key, status="card_staged", card_id=target.id
            )
            self.crash_hook("after_card_stage")

            existing_link = self.graph.find_link_between(source.id, target.id)
            created_link = existing_link is None
            if existing_link is not None and existing_link.status == "hidden":
                self.graph.unhide_link(existing_link.id, source="manual")
                link = existing_link
            elif existing_link is not None:
                link = existing_link
            else:
                if self.graph.is_blocked(source.id, target.id):
                    self.graph.unblock_pair(source.id, target.id)
                link = self.graph.add_link(
                    source.id,
                    target.id,
                    LinkKind(relation.link),
                    confidence=1.0,
                    reason=relation.reason,
                    source="manual",
                )
            self.cards.update_lexical_operation(
                idempotency_key, status="graph_written", link_id=link.id
            )
            self.crash_hook("after_graph_write")

            source_touched = self.cards.touch(source.id)
            target_touched = self.cards.touch(target.id)
            if not source_touched or not target_touched:
                raise RuntimeError("Dictionary materialization touch barrier failed")
            self.cards.update_lexical_operation(idempotency_key, status="touched")
            self.crash_hook("after_touch")

            current_target = self.cards.get(target.id)
            if current_target is None:
                raise NotFoundError("Card", target.id)
            sidecar = self.cards.get_dictionary_entry(target.id)
            dictionary_card = None
            if sidecar is not None:
                active_sidecar = sidecar.model_copy(
                    update={"materialization_status": "active"}
                )
                saved = _saved(current_target, active_sidecar)
                dictionary_card = DictionaryProjectionItem(
                    card=_card_node(current_target),
                    dictionary=saved,
                    reader_hidden=current_target.reader_hidden,
                    links=[_link_response(link)],
                )
            result = MaterializeLinkResult(
                target_card=_card_node(current_target),
                dictionary_card=dictionary_card,
                link=_link_response(link),
                created_card=created_card,
                created_link=created_link,
                replayed=False,
            )
            self.cards.activate_dictionary_entry_and_complete_operation(
                card_id=target.id,
                idempotency_key=idempotency_key,
                response_json=result.model_dump_json(),
            )
            return result


def materialize_request_hash(values: dict[str, str]) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def completed_materialize_replay(
    *, cards: Any, idempotency_key: str, request_values: dict[str, str]
) -> MaterializeLinkResult | None:
    """Return a completed ledger response without provider/quota/flag admissions."""
    operation = cards.get_lexical_operation(idempotency_key)
    if operation is None:
        return None
    if operation.request_hash != materialize_request_hash(request_values):
        raise ConflictError("Idempotency-Key was already used with a different request")
    if operation.status != "completed" or not operation.response_json:
        return None
    result = MaterializeLinkResult.model_validate_json(operation.response_json)
    return result.model_copy(update={"replayed": True})


def has_persisted_materialize_judgement(
    *, cards: Any, idempotency_key: str, request_values: dict[str, str]
) -> bool:
    """Whether same-key recovery can resume without another quota-bearing judge."""
    operation = cards.get_lexical_operation(idempotency_key)
    if operation is None:
        return False
    if operation.request_hash != materialize_request_hash(request_values):
        raise ConflictError("Idempotency-Key was already used with a different request")
    return bool(operation.relation_json)
