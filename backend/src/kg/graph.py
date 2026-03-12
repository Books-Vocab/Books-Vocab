"""Graph storage for card relationships."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class LinkKind(StrEnum):
    """Types of relationships between cards."""

    CONFUSABLE = "confusable"
    CONTRASTS_WITH = "contrasts_with"
    SHARES_USAGE = "shares_usage"


LINK_LABELS: dict[LinkKind, str] = {
    LinkKind.CONFUSABLE: "易混",
    LinkKind.CONTRASTS_WITH: "對比",
    LinkKind.SHARES_USAGE: "相關",
}


class GraphLink(BaseModel):
    """A relationship between two cards."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    from_id: str
    to_id: str
    kind: LinkKind
    confidence: float
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: Literal["candidate", "active", "deprecated"] = "active"


class CandidatePair(BaseModel):
    """A pending pair awaiting LLM judgement."""

    from_id: str
    to_id: str
    similarity: float  # embedding similarity score
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GraphStore:
    """JSON-based graph storage."""

    def __init__(self, links_path: Path, candidates_path: Path) -> None:
        self.links_path = links_path
        self.candidates_path = candidates_path
        self._links: dict[str, GraphLink] = {}
        self._candidates: list[CandidatePair] = []
        self._from_index: dict[str, set[str]] = {}  # card_id → set of link_ids
        self._to_index: dict[str, set[str]] = {}    # card_id → set of link_ids
        self._load()

    def _index_link(self, link: GraphLink) -> None:
        self._from_index.setdefault(link.from_id, set()).add(link.id)
        self._to_index.setdefault(link.to_id, set()).add(link.id)

    def _unindex_link(self, link: GraphLink) -> None:
        self._from_index.get(link.from_id, set()).discard(link.id)
        self._to_index.get(link.to_id, set()).discard(link.id)

    def _rebuild_index(self) -> None:
        self._from_index = {}
        self._to_index = {}
        for link in self._links.values():
            self._index_link(link)

    def _load(self) -> None:
        if self.links_path.exists():
            data = json.loads(self.links_path.read_text())
            self._links = {lk["id"]: GraphLink.model_validate(lk) for lk in data}
        if self.candidates_path.exists():
            data = json.loads(self.candidates_path.read_text())
            self._candidates = [CandidatePair.model_validate(c) for c in data]
        self._rebuild_index()

    def _save_links(self) -> None:
        self.links_path.parent.mkdir(parents=True, exist_ok=True)
        data = [lk.model_dump(mode="json") for lk in self._links.values()]
        tmp_path = self.links_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        if self.links_path.exists():
            bak_path = self.links_path.with_suffix(".json.bak")
            self.links_path.replace(bak_path)
        tmp_path.replace(self.links_path)

    def _save_candidates(self) -> None:
        self.candidates_path.parent.mkdir(parents=True, exist_ok=True)
        data = [c.model_dump(mode="json") for c in self._candidates]
        tmp_path = self.candidates_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        if self.candidates_path.exists():
            bak_path = self.candidates_path.with_suffix(".json.bak")
            self.candidates_path.replace(bak_path)
        tmp_path.replace(self.candidates_path)

    # --- Links ---

    def add_link(
        self,
        from_id: str,
        to_id: str,
        kind: LinkKind,
        confidence: float,
        reason: str,
    ) -> GraphLink:
        """Create and store a new link."""
        link = GraphLink(
            from_id=from_id,
            to_id=to_id,
            kind=kind,
            confidence=confidence,
            reason=reason,
        )
        self._links[link.id] = link
        self._index_link(link)
        self._save_links()
        return link

    def get_links_for(self, card_id: str) -> list[GraphLink]:
        """Get all active links involving a card."""
        link_ids = self._from_index.get(card_id, set()) | self._to_index.get(card_id, set())
        return [self._links[lid] for lid in link_ids if self._links[lid].status == "active"]

    def has_link(self, id_a: str, id_b: str) -> bool:
        """Check if a link exists between two cards."""
        candidates = self._from_index.get(id_a, set()) | self._to_index.get(id_a, set())
        for lid in candidates:
            lk = self._links[lid]
            if lk.status != "active":
                continue
            if (lk.from_id == id_a and lk.to_id == id_b) or (
                lk.from_id == id_b and lk.to_id == id_a
            ):
                return True
        return False

    def all_links(self) -> Iterator[GraphLink]:
        yield from self._links.values()

    def link_count(self) -> int:
        return sum(1 for lk in self._links.values() if lk.status == "active")

    # --- Candidates ---

    def add_candidate(self, from_id: str, to_id: str, similarity: float) -> None:
        """Add a candidate pair for LLM judgement."""
        # Skip if already exists or link exists
        if self.has_link(from_id, to_id):
            return
        for c in self._candidates:
            if (c.from_id == from_id and c.to_id == to_id) or (
                c.from_id == to_id and c.to_id == from_id
            ):
                return
        self._candidates.append(CandidatePair(from_id=from_id, to_id=to_id, similarity=similarity))
        self._save_candidates()

    def pop_candidates(self) -> list[CandidatePair]:
        """Get and clear all pending candidates."""
        result = self._candidates[:]
        self._candidates.clear()
        self._save_candidates()
        return result

    def requeue_candidates(self, candidates: list[CandidatePair]) -> None:
        """Push unprocessed candidates back onto the list."""
        self._candidates.extend(candidates)
        self._save_candidates()

    def candidate_count(self) -> int:
        return len(self._candidates)

    # --- Cleanup ---

    def deprecate_links_for(self, card_id: str) -> int:
        """Deprecate all active links involving a card. Returns count of deprecated links."""
        link_ids = self._from_index.get(card_id, set()) | self._to_index.get(card_id, set())
        count = 0
        for lid in list(link_ids):
            lk = self._links.get(lid)
            if lk and lk.status == "active":
                lk.status = "deprecated"
                count += 1
        if count:
            self._save_links()
        return count
