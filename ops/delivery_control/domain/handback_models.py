"""Typed handback receipt envelope and canonical wire representation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import InvalidReceipt
from .scope_models import Scope
from .validation_models import (
    HandbackOutcome,
    ValidationEvidence,
    _require_generation,
    _require_sha,
    _require_text,
)

# Internal normalized envelope. The existing kg.worktree.handback.v1 wire
# schema remains owned by worktree_registry.py and is translated by adapters.
HANDBACK_SCHEMA = "kg.delivery.handback.v1"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_INITIAL_HOLDS = frozenset({"p0", "p1", "security"})


@dataclass(frozen=True)
class HandbackReceipt:
    lane_id: str
    owner_thread_id: str
    claim_generation: int
    branch: str
    worktree_path: str
    base_sha: str
    parent_sha: str
    head_sha: str
    origin_main_sha: str
    content_digest: str
    scope: Scope
    validation: tuple[ValidationEvidence | HandbackOutcome, ...] = ()
    initial_holds: tuple[str, ...] = ()
    schema: str = field(default=HANDBACK_SCHEMA, init=False)

    def __post_init__(self) -> None:
        for name in ("lane_id", "owner_thread_id", "branch"):
            _require_text(name, getattr(self, name))
        _require_generation("claim_generation", self.claim_generation)
        _require_text("worktree_path", self.worktree_path)
        worktree_path = Path(self.worktree_path)
        if not worktree_path.is_absolute():
            raise InvalidReceipt("worktree_path must be absolute")
        object.__setattr__(self, "worktree_path", str(worktree_path.resolve()))
        for name in ("base_sha", "parent_sha", "head_sha", "origin_main_sha"):
            _require_sha(name, getattr(self, name))
        if type(self.content_digest) is not str or not _DIGEST_RE.fullmatch(
            self.content_digest
        ):
            raise InvalidReceipt("content_digest must be a lowercase SHA-256 digest")
        if type(self.validation) is not tuple or any(
            not isinstance(item, (ValidationEvidence, HandbackOutcome))
            for item in self.validation
        ):
            raise InvalidReceipt("validation must be a tuple of evidence")
        if (
            type(self.initial_holds) is not tuple
            or any(
                type(item) is not str or item not in _INITIAL_HOLDS
                for item in self.initial_holds
            )
            or len(set(self.initial_holds)) != len(self.initial_holds)
        ):
            raise InvalidReceipt("initial_holds must contain unique supported holds")
        object.__setattr__(self, "initial_holds", tuple(sorted(self.initial_holds)))

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "lane_id": self.lane_id,
            "owner_thread_id": self.owner_thread_id,
            "claim_generation": self.claim_generation,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "base_sha": self.base_sha,
            "parent_sha": self.parent_sha,
            "head_sha": self.head_sha,
            "origin_main_sha": self.origin_main_sha,
            "content_digest": self.content_digest,
            "scope": self.scope.to_payload(),
            "scope_digest": self.scope.digest,
            "validation": [item.to_payload() for item in self.validation],
            "initial_holds": list(self.initial_holds),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> HandbackReceipt:
        if not isinstance(payload, Mapping):
            raise InvalidReceipt("handback receipt payload must be an object")
        if payload.get("schema") != HANDBACK_SCHEMA:
            raise InvalidReceipt(f"handback schema must be {HANDBACK_SCHEMA}")
        try:
            raw_scope = payload["scope"]
            if not isinstance(raw_scope, Mapping):
                raise TypeError("scope must be an object")
            scope = Scope.from_payload(raw_scope)
            if payload.get("scope_digest") != scope.digest:
                raise InvalidReceipt("scope digest does not match Scope")
            raw_validation = payload.get("validation", [])
            if not isinstance(raw_validation, list) or any(
                not isinstance(item, Mapping) for item in raw_validation
            ):
                raise TypeError("validation entries must be objects")
            raw_initial_holds = payload.get("initial_holds", [])
            if not isinstance(raw_initial_holds, list) or any(
                type(item) is not str for item in raw_initial_holds
            ):
                raise TypeError("initial_holds must be a list of strings")
            string_fields = (
                "lane_id",
                "owner_thread_id",
                "branch",
                "worktree_path",
                "base_sha",
                "parent_sha",
                "head_sha",
                "origin_main_sha",
                "content_digest",
            )
            if any(type(payload.get(name)) is not str for name in string_fields):
                raise TypeError("handback string field has the wrong type")
            generation = payload["claim_generation"]
            if type(generation) is not int:
                raise TypeError("claim_generation must be an integer")
            return cls(
                lane_id=payload["lane_id"],
                owner_thread_id=payload["owner_thread_id"],
                claim_generation=generation,
                branch=payload["branch"],
                worktree_path=payload["worktree_path"],
                base_sha=payload["base_sha"],
                parent_sha=payload["parent_sha"],
                head_sha=payload["head_sha"],
                origin_main_sha=payload["origin_main_sha"],
                content_digest=payload["content_digest"],
                scope=scope,
                validation=tuple(
                    HandbackOutcome.from_payload(item)
                    if "status" in item
                    else ValidationEvidence.from_payload(item)
                    for item in raw_validation
                ),
                initial_holds=tuple(raw_initial_holds),
            )
        except InvalidReceipt:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidReceipt("handback receipt is malformed") from error
