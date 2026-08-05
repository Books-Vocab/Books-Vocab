"""Crash-recoverable graph mutations for dictionary-card lifecycle actions."""

from __future__ import annotations

import threading
from typing import Any

from .models import CandidatePair, GraphCardLifecycleSnapshot, GraphLink


class GraphLifecycleRollbackError(RuntimeError):
    """Graph apply failed and its exact snapshot could not be fully restored."""


class _LifecycleMixin:
    _lock: threading.Lock
    _links: dict[str, GraphLink]
    _candidates: list[CandidatePair]
    _pending_judge: set[str]
    _blocked_pairs: set[tuple[str, str]]
    _known_candidate_pairs: set[tuple[str, str]]
    _known_pending_judge: set[str]
    _known_blocked_pairs: set[tuple[str, str]]
    _from_index: dict[str, set[str]]
    _to_index: dict[str, set[str]]

    def _links_to_serializable(self) -> list[dict]: ...
    def _candidates_to_serializable(self) -> list[dict]: ...
    def _blocked_to_serializable(self) -> list[list[str]]: ...
    def _flush_links(self, snapshot: list[dict]) -> None: ...
    def _flush_candidates(self, snapshot: list[dict]) -> None: ...
    def _flush_pending_judge(self, snapshot: list[str]) -> None: ...
    def _flush_blocked(self, snapshot: list[list[str]]) -> None: ...
    def _rebuild_candidate_set(self) -> None: ...
    def _build_graph_event_draft(self, event_type: str, **kwargs): ...
    def _emit_graph_events(self, drafts: list[Any], *, links_snapshot=None) -> None: ...

    @staticmethod
    def _normalize_pair(a: str, b: str) -> tuple[str, str]: ...

    def capture_card_lifecycle_snapshot(
        self, card_id: str
    ) -> GraphCardLifecycleSnapshot:
        """Capture every graph plane a cleanup can change for ``card_id``."""
        with self._lock:
            link_ids = self._from_index.get(card_id, set()) | self._to_index.get(
                card_id, set()
            )
            return GraphCardLifecycleSnapshot(
                card_id=card_id,
                links=[self._links[link_id].model_copy(deep=True) for link_id in link_ids],
                candidates=[
                    candidate.model_copy(deep=True)
                    for candidate in self._candidates
                    if candidate.from_id == card_id or candidate.to_id == card_id
                ],
                pending_judge=card_id in self._pending_judge,
                blocked_pairs=[pair for pair in self._blocked_pairs if card_id in pair],
            )

    def apply_card_lifecycle(
        self,
        snapshot: GraphCardLifecycleSnapshot,
        *,
        action: str,
        link_ids: set[str],
        cards_store: Any,
        source: str = "manual",
    ) -> None:
        """Apply a saved plan; ordinary failures restore its exact snapshot.

        ``BaseException`` deliberately bypasses rollback to model abrupt process
        death. The cards DB retains the plan and a same-state retry re-applies it.
        """
        if action not in {"archive", "unarchive", "delete"}:
            raise ValueError(f"Unsupported dictionary lifecycle action: {action}")
        if not snapshot.card_id:
            raise ValueError("Lifecycle snapshot requires card_id")

        changed_links: list[tuple[GraphLink, str, str]] = []
        with self._lock:
            if action in {"archive", "delete"}:
                for link_id in link_ids:
                    link = self._links.get(link_id)
                    if link is not None and link.status == "active":
                        before = link.status
                        link.status = "deprecated"
                        changed_links.append((link.model_copy(deep=True), before, link.status))
                self._candidates = [
                    candidate
                    for candidate in self._candidates
                    if candidate.from_id != snapshot.card_id
                    and candidate.to_id != snapshot.card_id
                ]
                self._rebuild_candidate_set()
                self._pending_judge.discard(snapshot.card_id)
                if action == "delete":
                    self._blocked_pairs = {
                        pair for pair in self._blocked_pairs if snapshot.card_id not in pair
                    }
            else:
                for link_id in link_ids:
                    link = self._links.get(link_id)
                    if link is None or link.status != "deprecated":
                        continue
                    other_id = (
                        link.to_id if link.from_id == snapshot.card_id else link.from_id
                    )
                    other = cards_store.get(other_id)
                    if other is None or other.is_deleted or other.is_archived:
                        continue
                    before = link.status
                    link.status = "active"
                    changed_links.append((link.model_copy(deep=True), before, link.status))

            links_payload = self._links_to_serializable()
            candidates_payload = self._candidates_to_serializable()
            pending_payload = sorted(self._pending_judge)
            blocked_payload = self._blocked_to_serializable()

        try:
            self._flush_links(links_payload)
            self._flush_candidates(candidates_payload)
            self._flush_pending_judge(pending_payload)
            self._flush_blocked(blocked_payload)
        except Exception as exc:
            try:
                self.restore_card_lifecycle_snapshot(snapshot)
            except Exception as rollback_exc:
                raise GraphLifecycleRollbackError(
                    f"graph lifecycle rollback failed for {snapshot.card_id}"
                ) from rollback_exc
            raise exc

        drafts = []
        for link, before, after in changed_links:
            event_type = "link_deprecated" if after == "deprecated" else "link_restored"
            drafts.append(
                self._build_graph_event_draft(
                    event_type,
                    link_id=link.id,
                    from_id=link.from_id,
                    to_id=link.to_id,
                    kind=str(link.kind),
                    source=source,
                    confidence_before=link.confidence,
                    confidence_after=link.confidence,
                    status_before=before,
                    status_after=after,
                )
            )
        self._emit_graph_events(drafts, links_snapshot=links_payload)

    def restore_card_lifecycle_snapshot(
        self, snapshot: GraphCardLifecycleSnapshot
    ) -> None:
        """Restore exactly the planes captured for one card and persist all four."""
        with self._lock:
            for saved in snapshot.links:
                current = self._links.get(saved.id)
                if current is not None:
                    current.status = saved.status

            self._candidates = [
                candidate
                for candidate in self._candidates
                if candidate.from_id != snapshot.card_id
                and candidate.to_id != snapshot.card_id
            ]
            self._candidates.extend(
                candidate.model_copy(deep=True) for candidate in snapshot.candidates
            )
            for candidate in snapshot.candidates:
                self._known_candidate_pairs.add(
                    self._normalize_pair(candidate.from_id, candidate.to_id)
                )
            self._rebuild_candidate_set()

            if snapshot.pending_judge:
                self._pending_judge.add(snapshot.card_id)
                self._known_pending_judge.add(snapshot.card_id)
            else:
                self._pending_judge.discard(snapshot.card_id)

            self._blocked_pairs = {
                pair for pair in self._blocked_pairs if snapshot.card_id not in pair
            }
            self._blocked_pairs.update(snapshot.blocked_pairs)
            self._known_blocked_pairs.update(snapshot.blocked_pairs)

            links_payload = self._links_to_serializable()
            candidates_payload = self._candidates_to_serializable()
            pending_payload = sorted(self._pending_judge)
            blocked_payload = self._blocked_to_serializable()

        errors: list[Exception] = []
        for flush, payload in (
            (self._flush_links, links_payload),
            (self._flush_candidates, candidates_payload),
            (self._flush_pending_judge, pending_payload),
            (self._flush_blocked, blocked_payload),
        ):
            try:
                flush(payload)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise GraphLifecycleRollbackError(
                f"failed to persist {len(errors)} graph rollback plane(s)"
            ) from errors[0]
