"""Immutable value objects shared by the delivery control plane."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import InvalidReceipt, InvalidScope

SCOPE_SCHEMA = "kg.worktree.scope.v1"
# This normalized envelope intentionally does not reuse the existing
# kg.worktree.handback.v1 wire schema.  The registry adapter validates and
# translates that legacy seal without changing its public contract.
HANDBACK_SCHEMA = "kg.delivery.handback.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ScopeOperation(StrEnum):
    ADD = "add"
    MODIFY = "modify"


def _safe_relative_path(value: str) -> str:
    if not value or value != value.strip() or "\\" in value:
        raise InvalidScope(f"unsafe Scope path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise InvalidScope(f"unsafe Scope path: {value!r}")
    if str(path) != value:
        raise InvalidScope(f"Scope path is not canonical: {value!r}")
    return value


def _require_sha(name: str, value: str) -> str:
    if not _SHA_RE.fullmatch(value):
        raise InvalidReceipt(f"{name} must be a lowercase 40-character Git SHA")
    return value


def _require_text(name: str, value: str) -> str:
    if not value or value != value.strip():
        raise InvalidReceipt(f"{name} must be non-empty canonical text")
    return value


@dataclass(frozen=True, order=True)
class ScopeFile:
    operation: ScopeOperation
    path: str

    def __post_init__(self) -> None:
        try:
            operation = ScopeOperation(self.operation)
        except ValueError as error:
            raise InvalidScope(
                f"unsupported Scope operation: {self.operation!r}"
            ) from error
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "path", _safe_relative_path(self.path))

    def to_payload(self) -> dict[str, str]:
        return {"operation": self.operation.value, "path": self.path}


@dataclass(frozen=True)
class Scope:
    files: tuple[ScopeFile, ...]
    schema: str = field(default=SCOPE_SCHEMA, init=False)

    def __post_init__(self) -> None:
        if not self.files:
            raise InvalidScope("Scope must contain at least one file")
        canonical = tuple(
            sorted(self.files, key=lambda item: (item.path, item.operation.value))
        )
        paths = [item.path for item in canonical]
        if len(paths) != len(set(paths)):
            raise InvalidScope("Scope contains a duplicate path")
        object.__setattr__(self, "files", canonical)

    @classmethod
    def from_paths(
        cls,
        *,
        add: Sequence[str] = (),
        modify: Sequence[str] = (),
    ) -> Scope:
        return cls(
            tuple(ScopeFile(ScopeOperation.ADD, path) for path in add)
            + tuple(ScopeFile(ScopeOperation.MODIFY, path) for path in modify)
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Scope:
        if payload.get("schema") != SCOPE_SCHEMA:
            raise InvalidScope(f"Scope schema must be {SCOPE_SCHEMA}")
        raw_files = payload.get("files")
        if not isinstance(raw_files, list):
            raise InvalidScope("Scope files must be a list")
        try:
            files = tuple(
                ScopeFile(
                    operation=ScopeOperation(item["operation"]),
                    path=str(item["path"]),
                )
                for item in raw_files
                if isinstance(item, Mapping)
            )
        except (KeyError, ValueError, TypeError) as error:
            raise InvalidScope("Scope files contain malformed entries") from error
        if len(files) != len(raw_files):
            raise InvalidScope("Scope files contain malformed entries")
        return cls(files=files)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "files": [item.to_payload() for item in self.files],
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.to_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.files)


@dataclass(frozen=True)
class ValidationEvidence:
    command: tuple[str, ...]
    exit_code: int
    duration_seconds: float
    observed_at: datetime
    log_path: str | None = None

    def __post_init__(self) -> None:
        if not self.command or any(not item for item in self.command):
            raise InvalidReceipt("validation command must be non-empty")
        if self.duration_seconds < 0:
            raise InvalidReceipt("validation duration cannot be negative")
        if self.observed_at.tzinfo is None:
            raise InvalidReceipt("validation timestamp must be timezone-aware")

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "command": list(self.command),
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "observed_at": self.observed_at.isoformat(),
        }
        if self.log_path is not None:
            payload["log_path"] = self.log_path
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ValidationEvidence:
        try:
            raw_command = payload["command"]
            if not isinstance(raw_command, list):
                raise TypeError("command must be a list")
            return cls(
                command=tuple(str(item) for item in raw_command),
                exit_code=int(payload["exit_code"]),
                duration_seconds=float(payload["duration_seconds"]),
                observed_at=datetime.fromisoformat(str(payload["observed_at"])),
                log_path=(
                    str(payload["log_path"])
                    if payload.get("log_path") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidReceipt("validation evidence is malformed") from error


@dataclass(frozen=True)
class HandbackReceipt:
    lane_id: str
    owner_thread_id: str
    branch: str
    worktree_path: str
    base_sha: str
    parent_sha: str
    head_sha: str
    origin_main_sha: str
    content_digest: str
    scope: Scope
    validation: tuple[ValidationEvidence, ...] = ()
    schema: str = field(default=HANDBACK_SCHEMA, init=False)

    def __post_init__(self) -> None:
        for name in ("lane_id", "owner_thread_id", "branch"):
            _require_text(name, getattr(self, name))
        _require_text("worktree_path", self.worktree_path)
        if not Path(self.worktree_path).is_absolute():
            raise InvalidReceipt("worktree_path must be absolute")
        for name in ("base_sha", "parent_sha", "head_sha", "origin_main_sha"):
            _require_sha(name, getattr(self, name))
        if not _DIGEST_RE.fullmatch(self.content_digest):
            raise InvalidReceipt("content_digest must be a lowercase SHA-256 digest")

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "lane_id": self.lane_id,
            "owner_thread_id": self.owner_thread_id,
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
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> HandbackReceipt:
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
            if not isinstance(raw_validation, list):
                raise TypeError("validation must be a list")
            validation = tuple(
                ValidationEvidence.from_payload(item)
                for item in raw_validation
                if isinstance(item, Mapping)
            )
            if len(validation) != len(raw_validation):
                raise TypeError("validation entries must be objects")
            return cls(
                lane_id=str(payload["lane_id"]),
                owner_thread_id=str(payload["owner_thread_id"]),
                branch=str(payload["branch"]),
                worktree_path=str(payload["worktree_path"]),
                base_sha=str(payload["base_sha"]),
                parent_sha=str(payload["parent_sha"]),
                head_sha=str(payload["head_sha"]),
                origin_main_sha=str(payload["origin_main_sha"]),
                content_digest=str(payload["content_digest"]),
                scope=scope,
                validation=validation,
            )
        except InvalidReceipt:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidReceipt("handback receipt is malformed") from error


@dataclass(frozen=True)
class WorktreeSnapshot:
    path: Path
    branch: str | None
    base_sha: str
    head_sha: str
    parent_sha: str
    clean: bool
    changed_paths: tuple[str, ...]


@dataclass(frozen=True)
class PhysicalWorktree:
    path: Path
    head_sha: str
    branch: str | None
    prunable: bool = False


@dataclass(frozen=True)
class InventoryProblem:
    source: str
    identity: str
    reason: str


@dataclass(frozen=True)
class RegistrySnapshot:
    lane_id: str
    branch: str
    path: Path
    status: str
    scope: Scope
    base_sha: str
    owner_thread_id: str | None = None
    handed_back_sha: str | None = None
    handback_valid: bool = False


@dataclass(frozen=True)
class RegistryInventory:
    records: tuple[RegistrySnapshot, ...]
    problems: tuple[InventoryProblem, ...] = ()


@dataclass(frozen=True)
class PullRequestSnapshot:
    number: int
    url: str
    branch: str
    base_sha: str
    head_sha: str
    state: str
    draft: bool
    mergeable: bool
