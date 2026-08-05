"""Durable dictionary-card promotion orchestration.

Stage A is the commit boundary: only a valid single-card enrichment plus local
difficulty score may turn a dictionary card into a review-eligible learning
card. Stage B (embed + judge) is deliberately best-effort after that commit.
"""

from __future__ import annotations

import inspect
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .cards.dictionary_store import PromotionClaim, PromotionLeaseLost
from .cards.model import Card
from .exceptions import ConflictError, QuotaExceededError
from .lexical import LexicalEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromotionEnrichment:
    meaning: str
    pos: str | None
    note: str | None
    collocations: list[str]


@dataclass(frozen=True)
class PromotionRequestResult:
    card_id: str
    card_role: str
    promotion_state: str
    already_promoted: bool


@dataclass(frozen=True)
class PromotionRunResult:
    card: Card
    error_code: str | None = None
    stage_b_succeeded: bool | None = None


_LOCK_GUARD = threading.Lock()
_CLAIM_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_WORKER_ID = uuid.uuid4().hex


def _claim_lock(path: Any) -> threading.RLock:
    key = str(path.resolve())
    with _LOCK_GUARD:
        return _CLAIM_LOCKS.setdefault(key, threading.RLock())


async def _resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class DictionaryPromotionService:
    """Queue and execute one dictionary promotion against a per-user store."""

    def __init__(
        self,
        *,
        cards: Any,
        enrich: Callable[[Card], Any],
        difficulty: Callable[[str], float],
        stage_b: Callable[[Card], Any] | None,
        worker_id: str = _PROCESS_WORKER_ID,
    ) -> None:
        self.cards = cards
        self.enrich = enrich
        self.difficulty = difficulty
        self.stage_b = stage_b
        self.worker_id = worker_id
        self._lock = _claim_lock(cards.path)

    def request(self, card_id: str) -> PromotionRequestResult:
        self.cards.recover_orphaned_dictionary_promotion(
            card_id,
            current_worker_id=self.worker_id,
        )
        queued = self.cards.enqueue_dictionary_promotion(card_id)
        return PromotionRequestResult(
            card_id=queued.card.id,
            card_role=queued.card.card_role,
            promotion_state=queued.card.promotion_state,
            already_promoted=queued.already_promoted,
        )

    async def run(self, card_id: str) -> PromotionRunResult:
        # Production is single-worker, and this path also serializes same-DB
        # in-process contenders so exactly one can cross queued -> running.
        with self._lock:
            claim = self.cards.claim_dictionary_promotion(
                card_id,
                worker_id=self.worker_id,
            )
        if claim is None:
            return self._current_result(card_id)

        try:
            target = _promotion_target(claim)
            enrichment = await _resolve(self.enrich(target))
            if not isinstance(enrichment, PromotionEnrichment):
                raise ValueError("Promotion enrichment returned an invalid shape")
            if not enrichment.meaning.strip():
                raise ValueError("Promotion enrichment did not return a meaning")
            difficulty = round(float(self.difficulty(target.content)), 2)
            promoted = self.cards.complete_dictionary_promotion(
                card_id,
                worker_id=claim.job.worker_id,
                attempt_count=claim.job.attempt_count,
                meaning=enrichment.meaning.strip(),
                pos=enrichment.pos,
                note=enrichment.note,
                collocations=enrichment.collocations,
                difficulty=difficulty,
            )
        except PromotionLeaseLost:
            return self._current_result(card_id)
        except QuotaExceededError:
            try:
                failed = self.cards.fail_dictionary_promotion(
                    card_id,
                    worker_id=claim.job.worker_id,
                    attempt_count=claim.job.attempt_count,
                    error_code="quota_exhausted",
                    retryable=True,
                )
            except PromotionLeaseLost:
                return self._current_result(card_id)
            return PromotionRunResult(card=failed, error_code="quota_exhausted")
        except Exception:
            logger.warning(
                "Dictionary promotion Stage A failed card_id=%s",
                card_id,
                exc_info=True,
            )
            try:
                failed = self.cards.fail_dictionary_promotion(
                    card_id,
                    worker_id=claim.job.worker_id,
                    attempt_count=claim.job.attempt_count,
                    error_code="enrichment_failed",
                    retryable=True,
                )
            except PromotionLeaseLost:
                return self._current_result(card_id)
            return PromotionRunResult(card=failed, error_code="enrichment_failed")

        stage_b_succeeded: bool | None = None
        if self.stage_b is not None:
            try:
                await _resolve(self.stage_b(promoted))
                stage_b_succeeded = True
            except Exception:
                # Stage A already committed the valid learning card. Embedding
                # and auto-linking can be retried by the ordinary pipeline.
                logger.warning(
                    "Dictionary promotion Stage B failed card_id=%s",
                    card_id,
                    exc_info=True,
                )
                stage_b_succeeded = False
        return PromotionRunResult(
            card=promoted,
            stage_b_succeeded=stage_b_succeeded,
        )

    def _current_result(self, card_id: str) -> PromotionRunResult:
        card = self.cards.get(card_id)
        if card is None:
            raise ConflictError("Dictionary promotion card disappeared")
        job = self.cards.get_dictionary_promotion_job(card_id)
        return PromotionRunResult(
            card=card,
            error_code=job.error_code if job is not None else None,
        )


def _promotion_target(claim: PromotionClaim) -> Card:
    """Build a detached one-card enrich target using the pinned example."""
    entry = LexicalEntry.model_validate_json(claim.dictionary.payload_json)
    sense = next(
        (
            item
            for item in entry.senses
            if item.key == claim.dictionary.selected_sense_key
        ),
        None,
    )
    if sense is None:
        raise ValueError("Pinned dictionary sense is missing")
    example = next(
        (
            item
            for item in sense.examples
            if item.key == claim.dictionary.selected_example_key
        ),
        None,
    )
    if example is None:
        raise ValueError("Pinned dictionary example is missing")
    return claim.card.model_copy(update={"examples": [example.text]})


def promotion_enrichment_from_result(
    target: Card,
    result: dict[str, Any],
    *,
    normalize_pos: Callable[[str], str],
) -> PromotionEnrichment:
    """Map the existing enrich contract to promotion Stage A fields.

    ``meaning_fix=null`` is explicitly a successful result meaning that the
    current meaning needs no correction, so the pinned dictionary meaning is
    retained. Only a malformed non-null value is rejected.
    """
    raw_meaning = result.get("meaning_fix")
    if raw_meaning is None:
        meaning = target.meaning
    elif isinstance(raw_meaning, str) and raw_meaning.strip():
        meaning = raw_meaning.strip()
    else:
        raise ValueError("Dictionary promotion enrichment returned an invalid meaning_fix")
    raw_collocations = result.get("collocations")
    collocations = (
        [str(value) for value in raw_collocations]
        if isinstance(raw_collocations, list)
        else []
    )
    raw_pos = result.get("pos")
    return PromotionEnrichment(
        meaning=meaning,
        pos=(
            normalize_pos(raw_pos)
            if isinstance(raw_pos, str) and raw_pos
            else target.pos
        ),
        note=result.get("note") if isinstance(result.get("note"), str) else None,
        collocations=collocations,
    )


__all__ = [
    "DictionaryPromotionService",
    "PromotionEnrichment",
    "PromotionRequestResult",
    "PromotionRunResult",
    "promotion_enrichment_from_result",
]
